"""Кабинет столовой: перемены дня, сводка «что собрать», массовая отметка."""
from __future__ import annotations

from datetime import timedelta

import pytest_asyncio
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services import campus_today
from tests.helpers import auth, login

DAY = None


@pytest_asyncio.fixture(scope="module")
async def client():
    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c


@pytest_asyncio.fixture(scope="module")
async def setup(client):
    """Отдельное окно и три оплаченных заказа на него через четыре дня."""
    admin = auth(await login(client, "admin@rosbiotech.ru", "admin"))
    student = auth(await login(client, "student@rosbiotech.ru", "student"))
    slot = (
        await client.post(
            "/api/admin/slots",
            json={"label": "Смена тест", "starts_at": "11:10", "ends_at": "11:30", "capacity": 50},
            headers=admin,
        )
    ).json()
    on = (campus_today() + timedelta(days=4)).isoformat()
    dishes = [d for d in (await client.get("/api/dishes")).json() if d["stock_qty"] >= 10]
    borsch, cutlet = dishes[0], dishes[1]
    orders = []
    for lines in ([(borsch, 2)], [(borsch, 1), (cutlet, 1)], [(cutlet, 3)]):
        await client.delete("/api/cart", headers=student)
        for dish, qty in lines:
            await client.post("/api/cart/items", json={"dish_id": dish["id"], "qty": qty}, headers=student)
        order = (
            await client.post("/api/orders", json={"slot_id": slot["id"], "pickup_date": on, "comment": "без лука"}, headers=student)
        ).json()
        await client.post(f"/api/orders/{order['id']}/pay", json={"method": "sbp"}, headers=student)
        orders.append(order)
    return {"slot": slot, "date": on, "orders": orders, "borsch": borsch, "cutlet": cutlet}


async def test_shift_groups_orders_by_slot_with_summary(client, setup):
    op = auth(await login(client, "operator@rosbiotech.ru", "operator"))
    r = await client.get(f"/api/operator/shift?date={setup['date']}", headers=op)
    assert r.status_code == 200, r.text
    data = r.json()
    section = next(s for s in data["slots"] if s["id"] == setup["slot"]["id"])
    assert section["total"] == 3
    assert section["counts"]["paid"] == 3
    assert section["deadline_time"] == "10:10"
    summary = {i["name"]: i["qty"] for i in section["to_collect"]}
    assert summary[setup["borsch"]["name"]] == 3
    assert summary[setup["cutlet"]["name"]] == 4
    # больше порций — выше в списке
    assert section["to_collect"][0]["name"] == setup["cutlet"]["name"]
    assert all(o["customer_name"] for o in section["orders"])
    assert section["orders"][0]["comment"] == "без лука"
    assert data["current_slot_id"] is not None


async def test_paid_order_can_go_straight_to_ready(client, setup):
    op = auth(await login(client, "operator@rosbiotech.ru", "operator"))
    order = setup["orders"][0]
    r = await client.patch(f"/api/operator/orders/{order['id']}/status", json={"status": "ready"}, headers=op)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ready"
    assert r.json()["ready_at"]
    # в ячейку — только через отдельное действие с назначением ячейки
    r = await client.patch(f"/api/operator/orders/{order['id']}/status", json={"status": "in_locker"}, headers=op)
    assert r.status_code == 409


async def test_mark_whole_slot_collected(client, setup):
    op = auth(await login(client, "operator@rosbiotech.ru", "operator"))
    slot_id = setup["slot"]["id"]
    r = await client.post(f"/api/operator/shift/{slot_id}/collected?date={setup['date']}", headers=op)
    assert r.status_code == 200
    assert r.json()["updated"] == 2  # один уже был собран
    section = next(
        s for s in (await client.get(f"/api/operator/shift?date={setup['date']}", headers=op)).json()["slots"]
        if s["id"] == slot_id
    )
    assert section["counts"]["ready"] == 3
    assert section["to_collect"] == []
    assert section["to_collect_count"] == 0
    # повтор ничего не ломает
    r = await client.post(f"/api/operator/shift/{slot_id}/collected?date={setup['date']}", headers=op)
    assert r.json()["updated"] == 0


async def test_student_cannot_open_shift(client, setup):
    student = auth(await login(client, "student@rosbiotech.ru", "student"))
    assert (await client.get("/api/operator/shift", headers=student)).status_code == 403
    r = await client.post(f"/api/operator/shift/{setup['slot']['id']}/collected", headers=student)
    assert r.status_code == 403
