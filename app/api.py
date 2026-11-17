import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import editor
from app.config import Settings, get_settings
from app.creator import CreatorError, create_campaign
from app.db import get_db
from app.keitaro import KeitaroClient, get_keitaro
from app.models import Campaign, Stream, StreamOffer

router = APIRouter(prefix="/api")


# ---------------------------------------------------------------- схемы


class CreateCampaignIn(BaseModel):
    name: str
    geo: str = Field(description="Коды стран через запятую: AU или MX,AU,RO")
    offer_id: int
    domain_id: int
    group_id: int
    traffic_source_id: int


class AddOfferIn(BaseModel):
    offer_id: int
    offer_name: str = ""


class UpdateOfferIn(BaseModel):
    pinned: bool | None = None
    share: int | None = None


# ---------------------------------------------------------------- справочники

_offers_cache: dict = {"at": 0.0, "items": []}


def _offers(kt: KeitaroClient) -> list[dict]:
    """Список офферов кэшируем на минуту: автокомплит дёргает его на каждый ввод."""
    if time.monotonic() - _offers_cache["at"] > 60:
        items = [o for o in kt.offers() if o.get("state", "active") == "active"]
        _offers_cache.update(at=time.monotonic(), items=items)
    return _offers_cache["items"]


@router.get("/offers")
def search_offers(q: str = "", limit: int = 20, kt: KeitaroClient = Depends(get_keitaro)):
    q = q.strip().lower()
    found = [
        {"id": o["id"], "name": o.get("name", "")}
        for o in _offers(kt)
        if not q or q in o.get("name", "").lower() or q == str(o["id"])
    ]
    return found[:limit]


@router.get("/settings")
def creator_settings(kt: KeitaroClient = Depends(get_keitaro), settings: Settings = Depends(get_settings)):
    """Домены, группы, источники для формы + что выбрать по умолчанию."""
    domains = [{"id": d["id"], "name": d["name"]} for d in kt.domains() if d.get("state", "active") == "active"]
    groups = [{"id": g["id"], "name": g["name"]} for g in kt.campaign_groups()]
    sources = [{"id": s["id"], "name": s["name"]} for s in kt.traffic_sources() if s.get("state", "active") == "active"]

    def pick(items: list[dict], wanted: str):
        wanted = wanted.lower().strip("/").removeprefix("https://").removeprefix("http://")
        for item in items:
            if item["name"].lower().strip("/").removeprefix("https://").removeprefix("http://") == wanted:
                return item["id"]
        return None

    return {
        "prefix": settings.campaign_prefix,
        "keitaro_url": settings.keitaro_url.rstrip("/"),
        "domains": domains,
        "groups": groups,
        "sources": sources,
        "defaults": {
            "domain_id": pick(domains, settings.default_domain),
            "group_id": pick(groups, settings.default_group),
            "traffic_source_id": pick(sources, settings.default_source),
        },
    }


# ---------------------------------------------------------------- кампании


def campaign_view(c: Campaign) -> dict:
    return {
        "id": c.id,
        "keitaro_id": c.keitaro_id,
        "name": c.name,
        "alias": c.alias,
        "geo": c.geo,
        "created_by_wrapper": c.created_by_wrapper,
        "fetched_at": c.fetched_at,
        "streams": [stream_view(s) for s in c.streams],
    }


def stream_view(s: Stream) -> dict:
    return {
        "id": s.id,
        "keitaro_id": s.keitaro_id,
        "name": s.name,
        "type": s.type,
        "schema": s.schema,
        "position": s.position,
        "state": s.state,
        "can_hold_offers": editor.can_hold_offers(s),
        "dirty": editor.is_dirty(s),
        "problems": editor.stream_problems(s),
        "pushed_at": s.pushed_at,
        "offers": [
            {
                "id": r.id,
                "offer_id": r.offer_id,
                "offer_name": r.offer_name,
                "status": r.status,
                "share": r.share,
                "pinned": r.pinned,
                "pub_status": r.pub_status,
                "pub_share": r.pub_share,
                "dirty": r.is_dirty,
            }
            for r in s.offers
        ],
    }


@router.post("/campaigns", status_code=201)
def create(
    body: CreateCampaignIn,
    db: Session = Depends(get_db),
    kt: KeitaroClient = Depends(get_keitaro),
    settings: Settings = Depends(get_settings),
):
    try:
        campaign = create_campaign(db, kt, settings, **body.model_dump())
    except CreatorError as exc:
        raise HTTPException(422, str(exc)) from exc
    return campaign_view(campaign)


@router.get("/campaigns")
def list_campaigns(
    all: bool = False,
    kt: KeitaroClient = Depends(get_keitaro),
    settings: Settings = Depends(get_settings),
):
    """Кампании из Keitaro; по умолчанию только с нашим префиксом."""
    items = [
        {"keitaro_id": c["id"], "name": c["name"], "state": c.get("state")}
        for c in kt.campaigns()
        if all or c["name"].startswith(settings.campaign_prefix)
    ]
    return sorted(items, key=lambda c: -c["keitaro_id"])


@router.get("/campaigns/{keitaro_id}")
def get_campaign(keitaro_id: int, db: Session = Depends(get_db), kt: KeitaroClient = Depends(get_keitaro)):
    """Открыть кампанию. Если обёртка видит её впервые — сразу делаем Fetch."""
    campaign = db.scalar(select(Campaign).where(Campaign.keitaro_id == keitaro_id))
    if campaign is None:
        campaign = Campaign(keitaro_id=keitaro_id, name="")
        db.add(campaign)
        editor.sync_campaign(db, kt, campaign)
        db.commit()
    return campaign_view(campaign)


@router.post("/campaigns/{keitaro_id}/fetch")
def fetch_streams(keitaro_id: int, db: Session = Depends(get_db), kt: KeitaroClient = Depends(get_keitaro)):
    campaign = db.scalar(select(Campaign).where(Campaign.keitaro_id == keitaro_id))
    if campaign is None:
        campaign = Campaign(keitaro_id=keitaro_id, name="")
        db.add(campaign)
    editor.sync_campaign(db, kt, campaign)
    db.commit()
    return campaign_view(campaign)


# ---------------------------------------------------------------- потоки и офферы


def _stream(db: Session, stream_id: int) -> Stream:
    stream = db.get(Stream, stream_id)
    if stream is None:
        raise HTTPException(404, "Поток не найден — нажмите Fetch streams")
    return stream


def _row(db: Session, stream: Stream, row_id: int) -> StreamOffer:
    row = db.get(StreamOffer, row_id)
    if row is None or row.stream_id != stream.id:
        raise HTTPException(404, "Оффер в потоке не найден")
    return row


def _apply(db: Session, stream: Stream, action) -> dict:
    """Выполнить действие над черновиком; ошибка — откат и 400/409."""
    try:
        action()
    except (editor.EditorError, editor.WeightError) as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc
    db.commit()
    db.refresh(stream)
    return stream_view(stream)


@router.post("/streams/{stream_id}/offers")
def add_offer(stream_id: int, body: AddOfferIn, db: Session = Depends(get_db), kt: KeitaroClient = Depends(get_keitaro)):
    stream = _stream(db, stream_id)
    name = body.offer_name or next((o["name"] for o in _offers(kt) if o["id"] == body.offer_id), None)
    if name is None:
        raise HTTPException(404, f"Оффер {body.offer_id} не найден в Keitaro")
    return _apply(db, stream, lambda: editor.add_offer(stream, body.offer_id, name))


@router.post("/streams/{stream_id}/offers/{row_id}/remove")
def remove_offer(stream_id: int, row_id: int, db: Session = Depends(get_db)):
    stream = _stream(db, stream_id)
    row = _row(db, stream, row_id)
    return _apply(db, stream, lambda: editor.remove_offer(stream, row))


@router.post("/streams/{stream_id}/offers/{row_id}/bring-back")
def bring_back(stream_id: int, row_id: int, db: Session = Depends(get_db)):
    stream = _stream(db, stream_id)
    row = _row(db, stream, row_id)
    return _apply(db, stream, lambda: editor.bring_back(stream, row))


@router.patch("/streams/{stream_id}/offers/{row_id}")
def update_offer(stream_id: int, row_id: int, body: UpdateOfferIn, db: Session = Depends(get_db)):
    stream = _stream(db, stream_id)
    row = _row(db, stream, row_id)

    def action():
        if body.share is not None:
            editor.set_share(stream, row, body.share)
        elif body.pinned is not None:
            editor.set_pinned(stream, row, body.pinned)

    return _apply(db, stream, action)


@router.post("/streams/{stream_id}/cancel")
def cancel(stream_id: int, db: Session = Depends(get_db)):
    stream = _stream(db, stream_id)
    return _apply(db, stream, lambda: editor.cancel(stream))


@router.post("/streams/{stream_id}/push")
def push(stream_id: int, db: Session = Depends(get_db), kt: KeitaroClient = Depends(get_keitaro)):
    stream = _stream(db, stream_id)
    return _apply(db, stream, lambda: editor.push(stream, kt))
