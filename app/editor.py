"""Редактор кампании: синхронизация с Keitaro и правка офферов в потоках.

Все кнопки, кроме Fetch и Push, меняют только нашу базу (черновик).
Keitaro меняется только по Push — так же, как в существующей обёртке.
"""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.keitaro import KeitaroClient
from app.models import ACTIVE, REMOVED, Campaign, Stream, StreamOffer
from app.weights import Slot, WeightError, problems, rebalance


class EditorError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- Fetch


def sync_campaign(db: Session, kt: KeitaroClient, campaign: Campaign, offer_names: dict[int, str] | None = None) -> None:
    """Fetch streams: подтянуть потоки и офферы из Keitaro.

    Неопубликованные изменения при этом сбрасываются — после Fetch черновик
    совпадает с Keitaro. Офферы, которые обёртка знала, но которых в Keitaro
    больше нет, не удаляются, а уходят в архив (removed) с кнопкой Bring back.
    """
    info = kt.campaign(campaign.keitaro_id)
    campaign.name = info.get("name", campaign.name)
    campaign.alias = info.get("alias", campaign.alias)

    if offer_names is None:
        offer_names = {o["id"]: o.get("name", "") for o in kt.offers()}

    kt_streams = kt.campaign_streams(campaign.keitaro_id)
    local = {s.keitaro_id: s for s in campaign.streams}
    seen: set[int] = set()

    for data in kt_streams:
        kt_id = data["id"]
        seen.add(kt_id)
        stream = local.get(kt_id)
        if stream is None:
            stream = Stream(keitaro_id=kt_id)
            campaign.streams.append(stream)
        stream.name = data.get("name") or ""
        stream.type = data.get("type")
        stream.schema = data.get("schema")
        stream.position = data.get("position") or 0
        stream.state = data.get("state")
        reconcile_offers(stream, data.get("offers") or [], offer_names)

    # Потоки, удалённые в Keitaro, убираем и у себя.
    for kt_id, stream in local.items():
        if kt_id not in seen:
            campaign.streams.remove(stream)

    campaign.fetched_at = _now()
    db.flush()


def reconcile_offers(stream: Stream, kt_offers: list[dict], offer_names: dict[int, str]) -> None:
    """Привести офферы потока к тому, что сейчас лежит в Keitaro."""
    in_keitaro = {o["offer_id"]: o for o in kt_offers}
    rows = {row.offer_id: row for row in stream.offers}

    for row in list(stream.offers):
        if row.offer_id in in_keitaro:
            continue
        if row.pub_status is None:
            # добавлен в обёртке и не опубликован — такой привязки нет нигде
            stream.offers.remove(row)
            continue
        row.status = row.pub_status = REMOVED
        row.share = row.pub_share = 0
        row.pinned = False

    for index, data in enumerate(kt_offers):
        offer_id = data["offer_id"]
        row = rows.get(offer_id)
        if row is None:
            row = StreamOffer(offer_id=offer_id)
            stream.offers.append(row)
        row.status = row.pub_status = ACTIVE
        row.share = row.pub_share = int(data.get("share") or 0)
        row.position = index
        row.offer_name = offer_names.get(offer_id, row.offer_name or "")

    # Архивные — после активных, в прежнем порядке.
    archived = sorted((r for r in stream.offers if r.status == REMOVED), key=lambda r: r.position)
    for shift, row in enumerate(archived):
        row.position = len(kt_offers) + shift
    stream.offers.sort(key=lambda r: r.position)


# ---------------------------------------------------------------- черновик


def _rebalance(stream: Stream) -> None:
    slots = [Slot(r.status == ACTIVE, r.pinned, r.share) for r in stream.offers]
    for row, share in zip(stream.offers, rebalance(slots)):
        row.share = share


def add_offer(stream: Stream, offer_id: int, offer_name: str = "") -> StreamOffer:
    if not can_hold_offers(stream):
        raise EditorError("Этот поток не работает с офферами (редирект без офферов)")
    for row in stream.offers:
        if row.offer_id == offer_id:
            if row.status == ACTIVE:
                raise EditorError(f"Оффер {offer_id} уже есть в потоке")
            return bring_back(stream, row)

    row = StreamOffer(
        offer_id=offer_id,
        offer_name=offer_name,
        status=ACTIVE,
        pub_status=None,
        position=max((r.position for r in stream.offers), default=-1) + 1,
    )
    stream.offers.append(row)
    _rebalance(stream)
    return row


def remove_offer(stream: Stream, row: StreamOffer) -> None:
    if row.status != ACTIVE:
        raise EditorError("Оффер уже удалён")
    if row.pub_status is None:
        stream.offers.remove(row)  # не публиковался — просто убираем привязку
    else:
        row.status = REMOVED
        row.pinned = False
        row.share = 0
    _rebalance(stream)


def bring_back(stream: Stream, row: StreamOffer) -> StreamOffer:
    if row.status == ACTIVE:
        raise EditorError("Оффер и так активен")
    row.status = ACTIVE
    row.pinned = False
    _rebalance(stream)
    return row


def set_pinned(stream: Stream, row: StreamOffer, pinned: bool) -> None:
    if row.status != ACTIVE:
        raise EditorError("Закрепить можно только активный оффер")
    row.pinned = pinned
    _rebalance(stream)


def set_share(stream: Stream, row: StreamOffer, share: int) -> None:
    """Ручная доля = закреплённая доля, остальные делят остаток."""
    if row.status != ACTIVE:
        raise EditorError("Долю можно задать только активному офферу")
    if not 0 <= share <= 100:
        raise EditorError("Доля — целое число от 0 до 100")
    row.share = share
    row.pinned = True
    _rebalance(stream)


def cancel(stream: Stream) -> None:
    """Откатить черновик к опубликованному состоянию."""
    for row in list(stream.offers):
        if row.pub_status is None:
            stream.offers.remove(row)
        else:
            row.status = row.pub_status
            row.share = row.pub_share
            if row.status == REMOVED:
                row.pinned = False


def push(stream: Stream, kt: KeitaroClient) -> None:
    """Push to Keitaro: отправить активные офферы с долями, затем принять ответ как новый снимок."""
    issues = stream_problems(stream)
    if issues:
        raise EditorError("; ".join(issues))
    payload = {
        "offers": [
            {"offer_id": r.offer_id, "share": r.share, "state": "active"}
            for r in stream.offers
            if r.status == ACTIVE
        ]
    }
    updated = kt.update_stream(stream.keitaro_id, payload)
    names = {r.offer_id: r.offer_name for r in stream.offers}
    reconcile_offers(stream, updated.get("offers") or [], names)
    stream.pushed_at = _now()


# ---------------------------------------------------------------- вид


def can_hold_offers(stream: Stream) -> bool:
    return stream.schema == "landings" or bool(stream.offers)


def is_dirty(stream: Stream) -> bool:
    return any(r.is_dirty for r in stream.offers)


def stream_problems(stream: Stream) -> list[str]:
    if not can_hold_offers(stream):
        return []
    return problems([Slot(r.status == ACTIVE, r.pinned, r.share) for r in stream.offers])


__all__ = [
    "EditorError",
    "WeightError",
    "add_offer",
    "bring_back",
    "cancel",
    "can_hold_offers",
    "is_dirty",
    "push",
    "remove_offer",
    "set_pinned",
    "set_share",
    "stream_problems",
    "sync_campaign",
]
