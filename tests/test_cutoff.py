"""Отсечка приёма заказов, срок жизни неоплаченного заказа, отмена и бонусы."""
from __future__ import annotations

from datetime import datetime, time, timedelta

import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update

from app.db import SessionLocal
from app.main import app
from app.models import Order, Payment, PaymentStatus, User
from app.services import campus_today, freeze_campus_now
from tests.helpers import auth, login

SLOT_START = time(13, 0)


@pytest_asyncio.fixture(scope="module")
async def client():
    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c


@pytest.fixture(autouse=True)
def real_clock_after_test():
    yield
    freeze_campus_now(None)


@pytest_asyncio.fixture(scope="module")
async def slot_id(client):
    admin = auth(await login(client, "admin@rosbiotech.ru", "admin"))
    r = await client.post(
        "/api/admin/slots",
        json={
            "label": "Тест отсечки",
            "starts_at": "13:00",
            "ends_at": "13:20",
            "capacity": 500,
            "order_cutoff_minutes": 60,
        },
        headers=admin,
    )
    assert r.status_code == 201, r.text
    assert r.json()["order_cutoff_minutes"] == 60
    return r.json()["id"]


@pytest_asyncio.fixture(scope="module")
async def student(client):
    return auth(await login(client, "student@rosbiotech.ru", "student"))


def day():
    """День перемены — послезавтра, чтобы не зависеть от реального времени запуска."""
    return campus_today() + timedelta(days=2)


def at(minutes_before_start: int, on=None) -> datetime:
    return datetime.combine(on or day(), SLOT_START) - timedelta(minutes=minutes_before_start)


async def fill_cart(client, headers, qty=1, index=0):
    dishes = [d for d in (await client.get("/api/dishes")).json() if d["stock_qty"] >= qty]
    dish = dishes[index]
    await client.delete("/api/cart", headers=headers)
    r = await client.post("/api/cart/items", json={"dish_id": dish["id"], "qty": qty}, headers=headers)
    assert r.status_code == 200, r.text
    return dish


async def order_on(client, headers, slot, on, **extra):
    return await client.post(
        "/api/orders",
        json={"slot_id": slot, "pickup_date": on.isoformat(), **extra},
        headers=headers,
    )


async def age_order(order_id: int, minutes: int) -> None:
    """Сдвигает момент оформления заказа в прошлое."""
    async with SessionLocal() as s:
        order = await s.get(Order, order_id)
        order.created_at = order.created_at - timedelta(minutes=minutes)
        await s.commit()


async def stock_of(client, dish_id):
    return (await client.get(f"/api/dishes/{dish_id}")).json()["stock_qty"]


async def balance(user_email="student@rosbiotech.ru"):
    async with SessionLocal() as s:
        user = await s.scalar(select(User).where(User.email == user_email))
        return float(user.bonus_balance)


# --------------------------------------------------------------------------- #
async def test_order_61_minutes_before_is_accepted(client, slot_id, student):
    on = day()
    freeze_campus_now(at(61, on))
    await fill_cart(client, student)
    r = await order_on(client, student, slot_id, on)
    assert r.status_code == 201, r.text
    assert r.json()["deadline_time"] == "12:00"


async def test_order_59_minutes_before_is_rejected(client, slot_id, student):
    on = day()
    freeze_campus_now(at(59, on))
    await fill_cart(client, student)
    r = await order_on(client, student, slot_id, on)
    assert r.status_code == 409
    assert "закрыт в 12:00" in r.json()["detail"]
    await client.delete("/api/cart", headers=student)


async def test_slots_report_deadline_for_any_date(client, slot_id):
    on = day()
    # накануне вечером: заказ на завтра ещё принимается, отсечка — завтра в 12:00
    freeze_campus_now(datetime.combine(on - timedelta(days=1), time(23, 0)))
    slots = (await client.get(f"/api/slots?date={on.isoformat()}")).json()
    slot = next(s for s in slots if s["id"] == slot_id)
    assert slot["is_open"] and slot["is_available"]
    assert slot["deadline_time"] == "12:00"
    assert slot["order_deadline"].startswith(f"{on.isoformat()}T12:00")
    assert slot["closes_in_minutes"] == 13 * 60

    # в тот же день за 25 минут до отсечки
    freeze_campus_now(at(85, on))
    slot = next(s for s in (await client.get(f"/api/slots?date={on.isoformat()}")).json() if s["id"] == slot_id)
    assert slot["closes_in_minutes"] == 25

    # после отсечки окно закрыто, хотя места есть
    freeze_campus_now(at(30, on))
    slot = next(s for s in (await client.get(f"/api/slots?date={on.isoformat()}")).json() if s["id"] == slot_id)
    assert not slot["is_open"] and not slot["is_available"]
    assert slot["left"] > 0

    # утренняя перемена 9:30 на завтра закрывается завтра в 8:30
    freeze_campus_now(datetime.combine(on, time(8, 31)))
    morning = next(
        s for s in (await client.get(f"/api/slots?date={on.isoformat()}")).json()
        if s["starts_at"] == "09:30"
    )
    assert morning["deadline_time"] == "08:30"
    assert not morning["is_open"]


async def test_cutoff_is_editable_by_admin(client, slot_id):
    admin = auth(await login(client, "admin@rosbiotech.ru", "admin"))
    r = await client.patch(
        f"/api/admin/slots/{slot_id}", json={"order_cutoff_minutes": 30}, headers=admin
    )
    assert r.status_code == 200, r.text
    assert r.json()["order_cutoff_minutes"] == 30
    assert r.json()["deadline_time"] == "12:30"
    r = await client.patch(
        f"/api/admin/slots/{slot_id}", json={"order_cutoff_minutes": 60}, headers=admin
    )
    assert r.json()["deadline_time"] == "12:00"
    r = await client.patch(
        f"/api/admin/slots/{slot_id}", json={"order_cutoff_minutes": -5}, headers=admin
    )
    assert r.status_code == 422


async def test_student_cancels_before_cutoff_but_not_after(client, slot_id, student):
    op = auth(await login(client, "operator@rosbiotech.ru", "operator"))
    on = day()

    freeze_campus_now(at(120, on))
    await fill_cart(client, student)
    first = (await order_on(client, student, slot_id, on)).json()
    await fill_cart(client, student, index=1)
    second = (await order_on(client, student, slot_id, on)).json()
    for o in (first, second):
        r = await client.post(f"/api/orders/{o['id']}/pay", json={"method": "sbp"}, headers=student)
        assert r.json()["ok"], r.text
    assert r.json()["order"]["can_cancel"] is True

    # до отсечки — сам
    r = await client.post(f"/api/orders/{first['id']}/cancel", headers=student)
    assert r.status_code == 200 and r.json()["status"] == "cancelled"

    # после отсечки — нет, только через оператора
    freeze_campus_now(at(59, on))
    fresh = (await client.get(f"/api/orders/{second['id']}", headers=student)).json()
    assert fresh["can_cancel"] is False
    r = await client.post(f"/api/orders/{second['id']}/cancel", headers=student)
    assert r.status_code == 409
    assert "оператора" in r.json()["detail"]
    r = await client.patch(
        f"/api/operator/orders/{second['id']}/status", json={"status": "cancelled"}, headers=op
    )
    assert r.status_code == 200 and r.json()["status"] == "cancelled"


async def test_payment_after_cutoff_is_refused_and_order_released(client, slot_id, student):
    on = day()
    freeze_campus_now(at(61, on))
    dish = await fill_cart(client, student, qty=2)
    before = await stock_of(client, dish["id"])  # корзина порции не резервирует
    order = (await order_on(client, student, slot_id, on)).json()
    assert await stock_of(client, dish["id"]) == before - 2

    # открыл оплату за минуту до отсечки, нажал «Оплатить» через две минуты после
    freeze_campus_now(at(58, on))
    r = await client.post(f"/api/orders/{order['id']}/pay", json={"method": "card"}, headers=student)
    assert r.status_code == 409
    assert "деньги не списаны" in r.json()["detail"]

    fresh = (await client.get(f"/api/orders/{order['id']}", headers=student)).json()
    assert fresh["status"] == "cancelled"
    assert fresh["cancel_reason"] == "deadline"
    assert await stock_of(client, dish["id"]) == before
    async with SessionLocal() as s:
        paid = await s.scalar(
            select(Payment).where(
                Payment.order_id == order["id"], Payment.status == PaymentStatus.succeeded
            )
        )
        assert paid is None


async def test_unpaid_order_expires_and_returns_stock_and_bonus(client, student):
    on = campus_today() + timedelta(days=3)
    slots = (await client.get(f"/api/slots?date={on.isoformat()}")).json()
    slot = next(s for s in slots if s["is_available"])
    dish = await fill_cart(client, student, qty=3, index=2)
    stock_before = await stock_of(client, dish["id"])
    bonus_before = await balance()
    r = await order_on(client, student, slot["id"], on, use_bonus=True)
    assert r.status_code == 201, r.text
    order = r.json()
    assert order["pay_until"]
    assert float(order["bonus_used"]) > 0
    assert await stock_of(client, dish["id"]) == stock_before - 3

    # «ушёл со страницы банка» 16 минут назад
    await age_order(order["id"], minutes=16)

    fresh = (await client.get(f"/api/orders/{order['id']}", headers=student)).json()
    assert fresh["status"] == "cancelled"
    assert fresh["cancel_reason"] == "expired"
    assert await stock_of(client, dish["id"]) == stock_before
    assert await balance() == pytest.approx(bonus_before)

    r = await client.post(f"/api/orders/{order['id']}/pay", json={"method": "sbp"}, headers=student)
    assert r.status_code == 409
    assert "Время на оплату вышло" in r.json()["detail"]


async def test_background_sweep_expires_without_requests(client, student):
    from app.services import expire_unpaid_orders

    on = campus_today() + timedelta(days=3)
    slot = next(s for s in (await client.get(f"/api/slots?date={on.isoformat()}")).json() if s["is_available"])
    await fill_cart(client, student, index=3)
    order = (await order_on(client, student, slot["id"], on)).json()
    await age_order(order["id"], minutes=30)
    async with SessionLocal() as s:
        assert await expire_unpaid_orders(s) >= 1
        assert await s.scalar(select(Order.status).where(Order.id == order["id"])) == "cancelled"


async def test_cancel_takes_back_cashback(client, student):
    on = campus_today() + timedelta(days=3)
    slot = next(s for s in (await client.get(f"/api/slots?date={on.isoformat()}")).json() if s["is_available"])
    await fill_cart(client, student, index=4)
    start = await balance()
    order = (await order_on(client, student, slot["id"], on)).json()
    r = await client.post(f"/api/orders/{order['id']}/pay", json={"method": "sbp"}, headers=student)
    earned = float(r.json()["order"]["bonus_earned"])
    assert earned > 0
    assert await balance() == pytest.approx(start + earned)

    r = await client.post(f"/api/orders/{order['id']}/cancel", headers=student)
    assert r.status_code == 200
    assert await balance() == pytest.approx(start)


async def test_cashback_clawback_never_goes_negative(client, student):
    on = campus_today() + timedelta(days=3)
    slot = next(s for s in (await client.get(f"/api/slots?date={on.isoformat()}")).json() if s["is_available"])
    await fill_cart(client, student, index=5)
    order = (await order_on(client, student, slot["id"], on)).json()
    await client.post(f"/api/orders/{order['id']}/pay", json={"method": "sbp"}, headers=student)
    # кэшбэк уже потрачен на другой заказ
    async with SessionLocal() as s:
        await s.execute(update(User).where(User.email == "student@rosbiotech.ru").values(bonus_balance=0))
        await s.commit()
    r = await client.post(f"/api/orders/{order['id']}/cancel", headers=student)
    assert r.status_code == 200
    assert await balance() == 0
    async with SessionLocal() as s:
        await s.execute(update(User).where(User.email == "student@rosbiotech.ru").values(bonus_balance=250))
        await s.commit()
