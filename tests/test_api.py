"""Сценарии из видео с существующей обёрткой — на поддельном Keitaro."""

CREATE = {
    "name": "campaign1",
    "geo": "au, mx",
    "offer_id": 11,
    "domain_id": 1,
    "group_id": 2,
    "traffic_source_id": 4,
}


def create(client):
    r = client.post("/api/campaigns", json=CREATE)
    assert r.status_code == 201, r.text
    return r.json()


def offer_stream(campaign):
    return next(s for s in campaign["streams"] if s["can_hold_offers"])


def shares(stream):
    return {o["offer_id"]: o["share"] for o in stream["offers"] if o["status"] == "active"}


# ---------------------------------------------------------------- создаватор


def test_create_campaign_with_two_streams(client, fake):
    c = create(client)
    assert c["name"] == "test_ivanov_campaign1"
    kt = fake.campaigns_db[c["keitaro_id"]]
    assert (kt["domain_id"], kt["group_id"], kt["traffic_source_id"]) == (1, 2, 4)

    geo, offers = fake.campaign_streams(c["keitaro_id"])
    assert geo["position"] == 1
    assert geo["schema"] == "redirect"
    assert geo["action_payload"].startswith("https://www.google.")
    assert geo["filters"] == [{"name": "country", "mode": "accept", "payload": ["AU", "MX"]}]
    assert offers["position"] == 2
    assert [(o["offer_id"], o["share"]) for o in offers["offers"]] == [(11, 100)]

    # обёртка сразу видит оба потока; поток без офферов — просто поток
    assert [s["can_hold_offers"] for s in c["streams"]] == [False, True]
    assert offer_stream(c)["offers"][0]["offer_name"] == "Offer Alpha"


def test_prefix_is_not_duplicated(client):
    r = client.post("/api/campaigns", json={**CREATE, "name": "test_ivanov_x"})
    assert r.json()["name"] == "test_ivanov_x"


def test_bad_geo_is_rejected_before_keitaro(client, fake):
    r = client.post("/api/campaigns", json={**CREATE, "geo": "Australia"})
    assert r.status_code == 422
    assert fake.campaigns_db == {}


def test_failed_stream_archives_half_created_campaign(client, fake):
    fake.fail_stream_create = True
    r = client.post("/api/campaigns", json=CREATE)
    assert r.status_code == 502
    assert len(fake.archived) == 1
    assert fake.campaigns_db == {}


def test_settings_pick_defaults_by_name(client):
    s = client.get("/api/settings").json()
    assert s["defaults"] == {"domain_id": 1, "group_id": 2, "traffic_source_id": 4}
    assert s["prefix"] == "test_ivanov_"


def test_offer_search_skips_deleted(client):
    names = [o["name"] for o in client.get("/api/offers", params={"q": "offer"}).json()]
    assert "Old offer" not in names
    assert client.get("/api/offers", params={"q": "12"}).json() == [{"id": 12, "name": "Offer Beta"}]


# ---------------------------------------------------------------- редактор


def test_add_offer_recalculates_and_waits_for_push(client, fake):
    c = create(client)
    s = offer_stream(c)

    for offer_id in (12, 13):
        s = client.post(f"/api/streams/{s['id']}/offers", json={"offer_id": offer_id}).json()
    assert shares(s) == {11: 34, 12: 33, 13: 33}
    assert s["dirty"] is True
    # в Keitaro пока ничего не поменялось
    assert fake.kt_offers(s["keitaro_id"]) == {11: 100}

    s = client.post(f"/api/streams/{s['id']}/offers", json={"offer_id": 14}).json()
    assert shares(s) == {11: 25, 12: 25, 13: 25, 14: 25}

    s = client.post(f"/api/streams/{s['id']}/push").json()
    assert s["dirty"] is False
    assert fake.kt_offers(s["keitaro_id"]) == {11: 25, 12: 25, 13: 25, 14: 25}


def test_cancel_drops_unpublished_offers(client):
    s = offer_stream(create(client))
    s = client.post(f"/api/streams/{s['id']}/offers", json={"offer_id": 12}).json()
    s = client.post(f"/api/streams/{s['id']}/cancel").json()
    assert s["dirty"] is False
    assert [o["offer_id"] for o in s["offers"]] == [11]
    assert shares(s) == {11: 100}


def test_remove_then_push_keeps_offer_in_archive_and_bring_back(client, fake):
    s = offer_stream(create(client))
    for offer_id in (12, 13):
        s = client.post(f"/api/streams/{s['id']}/offers", json={"offer_id": offer_id}).json()
    s = client.post(f"/api/streams/{s['id']}/push").json()

    beta = next(o for o in s["offers"] if o["offer_id"] == 12)
    s = client.post(f"/api/streams/{s['id']}/offers/{beta['id']}/remove").json()
    removed = next(o for o in s["offers"] if o["offer_id"] == 12)
    assert removed["status"] == "removed" and removed["share"] == 0
    assert shares(s) == {11: 50, 13: 50}
    assert s["dirty"] is True

    s = client.post(f"/api/streams/{s['id']}/push").json()
    assert fake.kt_offers(s["keitaro_id"]) == {11: 50, 13: 50}
    # в обёртке оффер остался — серый, в архиве
    assert [o["status"] for o in s["offers"] if o["offer_id"] == 12] == ["removed"]

    s = client.post(f"/api/streams/{s['id']}/offers/{beta['id']}/bring-back").json()
    assert s["dirty"] is True
    s = client.post(f"/api/streams/{s['id']}/push").json()
    assert fake.kt_offers(s["keitaro_id"]) == {11: 34, 13: 33, 12: 33}


def test_cancel_after_remove_restores_published_state(client):
    s = offer_stream(create(client))
    s = client.post(f"/api/streams/{s['id']}/offers", json={"offer_id": 12}).json()
    s = client.post(f"/api/streams/{s['id']}/push").json()
    alpha = s["offers"][0]
    s = client.post(f"/api/streams/{s['id']}/offers/{alpha['id']}/remove").json()
    s = client.post(f"/api/streams/{s['id']}/cancel").json()
    assert shares(s) == {11: 50, 12: 50}
    assert s["dirty"] is False


def test_offers_deleted_in_keitaro_become_removed_on_fetch(client, fake):
    c = create(client)
    s = offer_stream(c)
    for offer_id in (12, 13):
        s = client.post(f"/api/streams/{s['id']}/offers", json={"offer_id": offer_id}).json()
    s = client.post(f"/api/streams/{s['id']}/push").json()

    # пользователь удалил два оффера прямо в Keitaro
    fake.kt_delete_offer(s["keitaro_id"], 12)
    fake.kt_delete_offer(s["keitaro_id"], 13)

    c = client.post(f"/api/campaigns/{c['keitaro_id']}/fetch").json()
    s = offer_stream(c)
    statuses = {o["offer_id"]: o["status"] for o in s["offers"]}
    assert statuses == {11: "active", 12: "removed", 13: "removed"}
    assert s["dirty"] is False

    gamma = next(o for o in s["offers"] if o["offer_id"] == 13)
    s = client.post(f"/api/streams/{s['id']}/offers/{gamma['id']}/bring-back").json()
    assert shares(s) == {11: 50, 13: 50}


def test_pinned_weight_survives_recalculation(client, fake):
    s = offer_stream(create(client))
    for offer_id in (12, 13, 14):
        s = client.post(f"/api/streams/{s['id']}/offers", json={"offer_id": offer_id}).json()
    s = client.post(f"/api/streams/{s['id']}/push").json()

    alpha = next(o for o in s["offers"] if o["offer_id"] == 11)
    s = client.patch(f"/api/streams/{s['id']}/offers/{alpha['id']}", json={"pinned": True}).json()
    assert shares(s) == {11: 25, 12: 25, 13: 25, 14: 25}

    delta = next(o for o in s["offers"] if o["offer_id"] == 14)
    s = client.post(f"/api/streams/{s['id']}/offers/{delta['id']}/remove").json()
    # закреплённые 25% остались, остальные 75% поделили двое
    assert shares(s) == {11: 25, 12: 38, 13: 37}

    s = client.post(f"/api/streams/{s['id']}/offers/{delta['id']}/bring-back").json()
    assert shares(s) == {11: 25, 12: 25, 13: 25, 14: 25}

    s = client.post(f"/api/streams/{s['id']}/push").json()
    assert sum(fake.kt_offers(s["keitaro_id"]).values()) == 100


def test_manual_share_pins_offer(client):
    s = offer_stream(create(client))
    for offer_id in (12, 13):
        s = client.post(f"/api/streams/{s['id']}/offers", json={"offer_id": offer_id}).json()
    alpha = s["offers"][0]
    s = client.patch(f"/api/streams/{s['id']}/offers/{alpha['id']}", json={"share": 60}).json()
    assert shares(s) == {11: 60, 12: 20, 13: 20}
    assert s["offers"][0]["pinned"] is True


def test_pinned_over_100_is_rejected_and_rolled_back(client):
    s = offer_stream(create(client))
    s = client.post(f"/api/streams/{s['id']}/offers", json={"offer_id": 12}).json()
    a, b = s["offers"]
    client.patch(f"/api/streams/{s['id']}/offers/{a['id']}", json={"share": 70})
    r = client.patch(f"/api/streams/{s['id']}/offers/{b['id']}", json={"share": 40})
    assert r.status_code == 409
    s = client.post(f"/api/streams/{s['id']}/cancel").json()
    assert shares(s) == {11: 100}


def test_push_blocked_when_not_100(client, fake):
    s = offer_stream(create(client))
    s = client.post(f"/api/streams/{s['id']}/offers", json={"offer_id": 12}).json()
    a, b = s["offers"]
    client.patch(f"/api/streams/{s['id']}/offers/{a['id']}", json={"share": 60})
    s = client.patch(f"/api/streams/{s['id']}/offers/{b['id']}", json={"share": 30}).json()
    assert s["problems"]
    r = client.post(f"/api/streams/{s['id']}/push")
    assert r.status_code == 409
    assert fake.pushes == []


def test_duplicate_offer_is_rejected(client):
    s = offer_stream(create(client))
    r = client.post(f"/api/streams/{s['id']}/offers", json={"offer_id": 11})
    assert r.status_code == 409


def test_redirect_stream_does_not_accept_offers(client):
    c = create(client)
    geo = c["streams"][0]
    r = client.post(f"/api/streams/{geo['id']}/offers", json={"offer_id": 12})
    assert r.status_code == 409


def test_list_campaigns_filters_by_prefix(client, fake):
    create(client)
    fake.create_campaign({"name": "someone_else"})
    names = [c["name"] for c in client.get("/api/campaigns").json()]
    assert names == ["test_ivanov_campaign1"]
    assert len(client.get("/api/campaigns", params={"all": True}).json()) == 2
