"""Создаватор кампаний: кампания + 2 потока.

1. «Geo XX → Google»: принимает трафик из указанных стран и редиректит на Google.
2. «Offers»: всё, что не поймал первый поток, отправляет на выбранный оффер (100%).
"""

import re
import secrets
import string

from sqlalchemy.orm import Session

from app.config import Settings
from app.keitaro import KeitaroClient, KeitaroError
from app.models import Campaign
from app.editor import sync_campaign

GEO_CODE = re.compile(r"^[A-Z]{2}$")


class CreatorError(ValueError):
    pass


def parse_geo(raw: str) -> list[str]:
    """'mx, au,RO' → ['MX', 'AU', 'RO'] (ISO 3166-1 alpha-2, без повторов)."""
    codes: list[str] = []
    for part in re.split(r"[\s,;]+", raw.strip().upper()):
        if not part:
            continue
        if not GEO_CODE.match(part):
            raise CreatorError(f"«{part}» — не двухбуквенный код страны (пример: AU, MX, RO)")
        if part not in codes:
            codes.append(part)
    if not codes:
        raise CreatorError("Укажите хотя бы одну страну")
    return codes


def with_prefix(name: str, prefix: str) -> str:
    name = name.strip()
    if not name:
        raise CreatorError("Укажите название кампании")
    return name if name.startswith(prefix) else prefix + name


def random_alias(length: int = 8) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def geo_stream_payload(campaign_id: int, geo: list[str], redirect_url: str) -> dict:
    return {
        "campaign_id": campaign_id,
        "name": f"Geo {','.join(geo)} → Google",
        "type": "regular",
        "position": 1,
        "schema": "redirect",
        "action_type": "http",
        "action_payload": redirect_url,
        "filters": [{"name": "country", "mode": "accept", "payload": geo}],
        "state": "active",
    }


def offer_stream_payload(campaign_id: int, offer_id: int) -> dict:
    return {
        "campaign_id": campaign_id,
        "name": "Offers",
        "type": "regular",
        "position": 2,
        "schema": "landings",
        "action_type": "http",
        "offers": [{"offer_id": offer_id, "share": 100, "state": "active"}],
        "state": "active",
    }


def create_campaign(
    db: Session,
    kt: KeitaroClient,
    settings: Settings,
    *,
    name: str,
    geo: str,
    offer_id: int,
    domain_id: int,
    group_id: int,
    traffic_source_id: int,
) -> Campaign:
    full_name = with_prefix(name, settings.campaign_prefix)
    countries = parse_geo(geo)

    created = kt.create_campaign(
        {
            "name": full_name,
            "alias": random_alias(),
            "type": "position",
            "state": "active",
            "domain_id": domain_id,
            "group_id": group_id,
            "traffic_source_id": traffic_source_id,
        }
    )
    kt_id = created["id"]

    # Если поток не создался, кампанию-полуфабрикат убираем в архив Keitaro,
    # чтобы не оставлять «пустых» кампаний.
    try:
        kt.create_stream(geo_stream_payload(kt_id, countries, settings.geo_redirect_url))
        kt.create_stream(offer_stream_payload(kt_id, offer_id))
    except KeitaroError:
        try:
            kt.archive_campaign(kt_id)
        except KeitaroError:
            pass
        raise

    campaign = Campaign(
        keitaro_id=kt_id,
        name=created.get("name", full_name),
        alias=created.get("alias"),
        geo=",".join(countries),
        offer_id=offer_id,
        domain_id=domain_id,
        group_id=group_id,
        traffic_source_id=traffic_source_id,
        created_by_wrapper=True,
    )
    db.add(campaign)
    db.flush()
    sync_campaign(db, kt, campaign)
    db.commit()
    return campaign
