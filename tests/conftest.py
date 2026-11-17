"""Фикстуры: приложение на SQLite в памяти и поддельный Keitaro."""

import copy
import itertools

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings, get_settings
from app.db import Base, get_db
from app.keitaro import KeitaroError, get_keitaro
from app.main import app


class FakeKeitaro:
    """Минимальная модель Keitaro в памяти: кампании, потоки, офферы."""

    def __init__(self):
        self._ids = itertools.count(100)
        self.offer_list = [
            {"id": 11, "name": "Offer Alpha", "state": "active"},
            {"id": 12, "name": "Offer Beta", "state": "active"},
            {"id": 13, "name": "Offer Gamma", "state": "active"},
            {"id": 14, "name": "Offer Delta", "state": "active"},
            {"id": 15, "name": "Old offer", "state": "deleted"},
        ]
        self.campaigns_db: dict[int, dict] = {}
        self.streams_db: dict[int, dict] = {}
        self.archived: list[int] = []
        self.fail_stream_create = False
        self.pushes: list[tuple[int, dict]] = []

    # справочники
    def domains(self):
        return [{"id": 1, "name": "https://in.posdk.xyz/", "state": "active"}]

    def campaign_groups(self):
        return [{"id": 2, "name": "FORTESTS"}, {"id": 3, "name": "Other"}]

    def traffic_sources(self):
        return [{"id": 4, "name": "FORTESTS", "state": "active"}]

    def offers(self):
        return copy.deepcopy(self.offer_list)

    # кампании
    def campaigns(self):
        return [copy.deepcopy(c) for c in self.campaigns_db.values()]

    def campaign(self, campaign_id):
        if campaign_id not in self.campaigns_db:
            raise KeitaroError("Keitaro HTTP 404: Not found", 404)
        return copy.deepcopy(self.campaigns_db[campaign_id])

    def create_campaign(self, payload):
        cid = next(self._ids)
        self.campaigns_db[cid] = {"id": cid, "state": "active", **payload}
        return copy.deepcopy(self.campaigns_db[cid])

    def archive_campaign(self, campaign_id):
        self.archived.append(campaign_id)
        self.campaigns_db.pop(campaign_id, None)

    # потоки
    def campaign_streams(self, campaign_id):
        streams = [s for s in self.streams_db.values() if s["campaign_id"] == campaign_id]
        return copy.deepcopy(sorted(streams, key=lambda s: s["position"]))

    def create_stream(self, payload):
        if self.fail_stream_create:
            raise KeitaroError("Keitaro HTTP 422: bad stream", 422)
        sid = next(self._ids)
        stream = {"id": sid, **copy.deepcopy(payload)}
        stream["offers"] = [self._offer_link(sid, o) for o in payload.get("offers", [])]
        self.streams_db[sid] = stream
        return copy.deepcopy(stream)

    def update_stream(self, stream_id, payload):
        self.pushes.append((stream_id, copy.deepcopy(payload)))
        stream = self.streams_db[stream_id]
        if "offers" in payload:
            stream["offers"] = [self._offer_link(stream_id, o) for o in payload["offers"]]
        return copy.deepcopy(stream)

    def _offer_link(self, stream_id, o):
        return {"id": next(self._ids), "stream_id": stream_id, "offer_id": o["offer_id"], "share": o["share"], "state": "active"}

    # помощники для тестов: «пользователь поправил что-то прямо в Keitaro»
    def kt_offers(self, stream_id):
        return {o["offer_id"]: o["share"] for o in self.streams_db[stream_id]["offers"]}

    def kt_delete_offer(self, stream_id, offer_id):
        s = self.streams_db[stream_id]
        s["offers"] = [o for o in s["offers"] if o["offer_id"] != offer_id]

    def close(self):
        pass


@pytest.fixture
def fake():
    return FakeKeitaro()


@pytest.fixture
def client(fake):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def _db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_keitaro] = lambda: fake
    app.dependency_overrides[get_settings] = lambda: Settings(campaign_prefix="test_ivanov_", _env_file=None)

    import app.api as api_module

    api_module._offers_cache.update(at=0.0, items=[])
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
