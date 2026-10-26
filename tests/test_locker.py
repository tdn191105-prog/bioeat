"""Постамат: ячейки, одноразовый QR и PIN, подпись запросов устройства, гонки."""
from __future__ import annotations

import asyncio
import secrets
import time
from datetime import timedelta

import pytest_asyncio
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db import SessionLocal
from app.lockers import device_secret, sign
from app.main import app
from app.models import LockerCell, PickupToken
from app.services import campus_today
from tests.helpers import auth, login

DEVICE = "locker-b1"
POINT = "Постамат, 1 этаж корпуса Б"


@pytest_asyncio.fixture(scope="module")
async def client():
    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c


@pytest_asyncio.fixture(scope="module")
async def people(client):
    return {
        "student": auth(await login(client, "student@rosbiotech.ru", "student")),
        "op": auth(await login(client, "operator@rosbiotech.ru", "operator")),
    }


def signed(payload: str, *, ts: int | None = None, nonce: str | None = None, secret: str | None = None):
    ts = int(time.time()) if ts is None else ts
    nonce = nonce or secrets.token_hex(8)
    secret = secret or device_secret(DEVICE, 1)
    return {"ts": ts, "nonce": nonce, "sig": sign(secret, DEVICE, ts, nonce, payload)}


async def device_scan(client, code, **kw):
    return await client.post(f"/api/device/lockers/{DEVICE}/scan", json={"code": code, **signed(code, **kw)})


async def device_event(client, kind, cell, empty=None):
    body = {"type": kind, "cell": cell, **signed(f"{kind}:{cell}")}
    if empty is not None:
        body["empty"] = empty
    return await client.post(f"/api/device/lockers/{DEVICE}/events", json=body)


async def device_commands(client):
    params = signed("commands")
    r = await client.get(f"/api/device/lockers/{DEVICE}/commands", params={**params, "wait": 0})
    assert r.status_code == 200, r.text
    return r.json()["commands"]


async def locker_order(client, people, *, place=True, index=0):
    """Оплаченный заказ на перемену с выдачей в постамате, по желанию — уже в ячейке."""
    on = (campus_today() + timedelta(days=5)).isoformat()
    slots = (await client.get(f"/api/slots?date={on}")).json()
    slot = next(s for s in slots if s["point"] == POINT and s["is_available"])
    dishes = [d for d in (await client.get("/api/dishes")).json() if d["stock_qty"] >= 3]
    h = people["student"]
    await client.delete("/api/cart", headers=h)
    await client.post("/api/cart/items", json={"dish_id": dishes[index]["id"], "qty": 1}, headers=h)
    order = (await client.post("/api/orders", json={"slot_id": slot["id"], "pickup_date": on}, headers=h)).json()
    assert order["pickup_kind"] == "locker"
    r = await client.post(f"/api/orders/{order['id']}/pay", json={"method": "sbp"}, headers=h)
    order = r.json()["order"]
    if place:
        r = await client.post(f"/api/operator/orders/{order['id']}/place", json={}, headers=people["op"])
        assert r.status_code == 200, r.text
        order = r.json()
    return order


async def token_for(client, people, order):
    r = await client.post(f"/api/orders/{order['id']}/pickup-token", headers=people["student"])
    assert r.status_code == 200, r.text
    return r.json()


# --------------------------------------------------------------------------- #
async def test_seeded_locker_has_24_cells(client, people):
    lockers = (await client.get("/api/operator/lockers", headers=people["op"])).json()
    locker = next(lk for lk in lockers if lk["device_id"] == DEVICE)
    assert locker["cells_total"] == 24
    assert {c["size"] for c in locker["cells"]} == {"S", "M", "L"}


async def test_full_locker_flow_with_one_time_qr(client, people):
    order = await locker_order(client, people)
    assert order["status"] == "in_locker"
    assert order["cell_number"]
    assert order["locker_name"] == "Корпус Б, 1 этаж"
    cell = order["cell_number"]

    # студент видит ячейку, кухня — команду открыть дверцу для загрузки
    mine = (await client.get(f"/api/orders/{order['id']}", headers=people["student"])).json()
    assert mine["cell_number"] == cell and mine["status_label"] == "В ячейке постамата"
    commands = await device_commands(client)
    assert {"action": "open", "cell": cell, "reason": "load"}.items() <= commands[-1].items()
    # закрытие дверцы после загрузки заказ не выдаёт
    await device_event(client, "door_closed", cell)
    assert (await client.get(f"/api/orders/{order['id']}", headers=people["student"])).json()["status"] == "in_locker"

    first = await token_for(client, people, order)
    assert first["code"].startswith("ROSPIT:L:")
    assert len(first["pin"]) == 6 and first["pin"].isdigit()
    assert first["ttl_seconds"] == 120
    assert first["qr_svg"].startswith("<svg")
    second = await token_for(client, people, order)

    # старый код гаснет, как только экран запросил новый
    r = await device_scan(client, first["code"])
    assert r.json() == {"action": "deny", "reason": "expired", "message": "Код устарел — обновите QR в приложении"}

    r = await device_scan(client, second["code"])
    assert r.json()["action"] == "open"
    assert r.json()["cell"] == cell

    # тот же код второй раз не открывает, PIN этой пары тоже погас
    assert (await device_scan(client, second["code"])).json()["reason"] == "used"
    assert (await device_scan(client, second["pin"])).json()["action"] == "deny"

    await device_event(client, "door_opened", cell)
    r = await device_event(client, "door_closed", cell)
    assert r.json()["issued"] == order["number"]
    fresh = (await client.get(f"/api/orders/{order['id']}", headers=people["student"])).json()
    assert fresh["status"] == "issued"
    assert fresh["picked_up_at"]
    async with SessionLocal() as s:
        state = await s.scalar(select(LockerCell.state).where(LockerCell.number == cell))
        assert state == "free"


async def test_code_expires_after_ttl(client, people):
    order = await locker_order(client, people, index=1)
    token = await token_for(client, people, order)
    async with SessionLocal() as s:
        for row in (await s.scalars(select(PickupToken).where(PickupToken.order_id == order["id"]))).all():
            row.expires_at = row.expires_at - timedelta(seconds=121)
        await s.commit()
    assert (await device_scan(client, token["code"])).json()["reason"] == "expired"
    # свежий код работает
    token = await token_for(client, people, order)
    assert (await device_scan(client, token["code"])).json()["action"] == "open"


async def test_parallel_scans_open_once(client, people):
    order = await locker_order(client, people, index=2)
    token = await token_for(client, people, order)
    results = await asyncio.gather(*(device_scan(client, token["code"]) for _ in range(4)))
    actions = sorted(r.json()["action"] for r in results)
    assert actions == ["deny", "deny", "deny", "open"]


async def test_pin_works_and_attempts_are_limited(client, people):
    order = await locker_order(client, people, index=3)
    token = await token_for(client, people, order)
    assert (await device_scan(client, token["pin"])).json()["action"] == "open"

    other = await locker_order(client, people, index=4)
    good = await token_for(client, people, other)
    wrong = f"{(int(good['pin']) + 1) % 1_000_000:06d}"
    for _ in range(5):
        assert (await device_scan(client, wrong)).json()["action"] == "deny"
    blocked = (await device_scan(client, good["pin"])).json()
    assert blocked["reason"] == "too_many_attempts"
    # QR при этом работает — лимит касается только перебора PIN
    assert (await device_scan(client, good["code"])).json()["action"] == "open"


async def test_device_requests_must_be_signed_fresh_and_unique(client):
    code = "ROSPIT:L:whatever"
    bad = signed(code, secret="not-the-secret")
    r = await client.post(f"/api/device/lockers/{DEVICE}/scan", json={"code": code, **bad})
    assert r.status_code == 401

    stale = signed(code, ts=int(time.time()) - 31)
    r = await client.post(f"/api/device/lockers/{DEVICE}/scan", json={"code": code, **stale})
    assert r.status_code == 401 and r.json()["detail"] == "stale_request"

    once = signed(code)
    assert (await client.post(f"/api/device/lockers/{DEVICE}/scan", json={"code": code, **once})).status_code == 200
    r = await client.post(f"/api/device/lockers/{DEVICE}/scan", json={"code": code, **once})
    assert r.status_code == 409 and r.json()["detail"] == "replayed_nonce"

    r = await client.post("/api/device/lockers/nope/scan", json={"code": code, **signed(code)})
    assert r.status_code == 404


async def test_window_code_is_refused_at_locker(client, people):
    order = await locker_order(client, people, place=False, index=5)
    r = await device_scan(client, order["pickup_code"])
    assert r.json()["reason"] == "window_code"
    # пока заказ не в ячейке, одноразового кода нет
    r = await client.post(f"/api/orders/{order['id']}/pickup-token", headers=people["student"])
    assert r.status_code == 409


async def test_two_operators_never_get_the_same_cell(client, people):
    a = await locker_order(client, people, place=False, index=6)
    b = await locker_order(client, people, place=False, index=7)
    results = await asyncio.gather(
        client.post(f"/api/operator/orders/{a['id']}/place", json={}, headers=people["op"]),
        client.post(f"/api/operator/orders/{b['id']}/place", json={}, headers=people["op"]),
    )
    assert all(r.status_code == 200 for r in results), [r.text for r in results]
    assert results[0].json()["cell_number"] != results[1].json()["cell_number"]

    # конкретная занятая ячейка — отказ
    c = await locker_order(client, people, place=False, index=8)
    busy = results[0].json()["cell_number"]
    r = await client.post(
        f"/api/operator/orders/{c['id']}/place", json={"cell_number": busy}, headers=people["op"]
    )
    assert r.status_code == 409


async def test_cancel_and_unload_free_the_cell(client, people):
    order = await locker_order(client, people, index=9)
    cell = order["cell_number"]
    await device_commands(client)
    r = await client.patch(
        f"/api/operator/orders/{order['id']}/status", json={"status": "cancelled"}, headers=people["op"]
    )
    assert r.status_code == 200
    commands = await device_commands(client)
    assert any(c["cell"] == cell and c["reason"] == "unload" for c in commands)

    # не забрал до конца дня: достаём, заказ возвращается в окно
    order = await locker_order(client, people, index=10)
    r = await client.post(f"/api/operator/orders/{order['id']}/unload", headers=people["op"])
    assert r.status_code == 200
    assert r.json()["status"] == "ready" and r.json()["cell_number"] is None
    # а в окне выдаётся по номеру
    r = await client.post("/api/operator/issue", json={"code": order["number"]}, headers=people["op"])
    assert r.status_code == 200 and r.json()["status"] == "issued"


async def test_heartbeat_marks_locker_online(client, people):
    r = await client.post(
        f"/api/device/lockers/{DEVICE}/heartbeat", json={"firmware": "0.1.0", **signed("heartbeat")}
    )
    assert r.status_code == 200
    shift = (await client.get("/api/operator/shift", headers=people["op"])).json()
    locker = next(lk for lk in shift["lockers"] if lk["device_id"] == DEVICE)
    assert locker["is_online"] is True
    section = next(s for s in shift["slots"] if s["point"] == POINT)
    assert section["is_locker"] is True


async def test_token_only_for_owner(client, people):
    order = await locker_order(client, people, index=11)
    r = await client.post(
        "/api/auth/register",
        json={"email": "stranger@rosbiotech.ru", "password": "secret", "full_name": "Чужой Студент"},
    )
    stranger = auth(r.json()["token"])
    r = await client.post(f"/api/orders/{order['id']}/pickup-token", headers=stranger)
    assert r.status_code == 403
