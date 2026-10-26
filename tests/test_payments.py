"""Оплата: DemoProvider, YooKassaProvider с замоканным HTTP, вебхуки, возвраты, чек."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, time, timedelta
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.config import Settings
from app.db import SessionLocal
from app.main import app
from app.models import Order, Payment, User
from app.payments import DemoProvider, YooKassaProvider, set_provider
from app.payments.receipt import build_receipt, receipt_total
from app.payments.yookassa import is_yookassa_ip
from app.services import campus_today, freeze_campus_now
from tests.helpers import auth, login


class FakeYooKassa:
    """Сервер ЮKassa в памяти: платежи, возвраты, журнал запросов."""

    def __init__(self):
        self.payments: dict[str, dict] = {}
        self.refunds: list[dict] = []
        self.requests: list[httpx.Request] = []
        self.fail_refunds = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.headers["authorization"].startswith("Basic ")
        path = request.url.path.removeprefix("/v3")
        if request.method == "POST" and path == "/payments":
            body = json.loads(request.content)
            key = request.headers["Idempotence-Key"]
            existing = next((p for p in self.payments.values() if p["_key"] == key), None)
            if existing:  # идемпотентность как у настоящей ЮKassa
                return httpx.Response(200, json=existing)
            pid = str(uuid.uuid4())
            self.payments[pid] = {
                "_key": key,
                "id": pid,
                "status": "pending",
                "amount": body["amount"],
                "metadata": body["metadata"],
                "receipt": body.get("receipt"),
                "confirmation": {"type": "redirect", "confirmation_url": f"https://yoomoney.ru/checkout/{pid}"},
            }
            return httpx.Response(200, json=self.payments[pid])
        if request.method == "GET" and path.startswith("/payments/"):
            pid = path.split("/")[-1]
            if pid not in self.payments:
                return httpx.Response(404, json={"description": "not found"})
            return httpx.Response(200, json=self.payments[pid])
        if request.method == "POST" and path == "/refunds":
            if self.fail_refunds:
                return httpx.Response(500, json={"description": "internal error"})
            body = json.loads(request.content)
            refund = {"id": str(uuid.uuid4()), "status": "succeeded", **body}
            self.refunds.append(refund)
            return httpx.Response(200, json=refund)
        return httpx.Response(404, json={"description": "unknown"})

    def set_status(self, pid, status, **extra):
        self.payments[pid].update(status=status, **extra)


@pytest.fixture(scope="module")
def fake():
    return FakeYooKassa()


@pytest_asyncio.fixture(scope="module")
async def client(fake):
    async with LifespanManager(app):
        set_provider(YooKassaProvider("123456", "test_secret", "https://api.yookassa.ru/v3",
                                      check_ip=False, transport=httpx.MockTransport(fake.handler)))
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
        set_provider(None)
        freeze_campus_now(None)


@pytest_asyncio.fixture(scope="module")
async def student(client):
    return auth(await login(client, "student@rosbiotech.ru", "student"))


async def new_order(client, student, *, use_bonus=False, on=None, slot_id=None, qty=1):
    on = on or (campus_today() + timedelta(days=6)).isoformat()
    if slot_id is None:
        slot_id = next(s for s in (await client.get(f"/api/slots?date={on}")).json() if s["is_available"])["id"]
    dishes = [d for d in (await client.get("/api/dishes")).json() if d["stock_qty"] >= qty]
    await client.delete("/api/cart", headers=student)
    await client.post("/api/cart/items", json={"dish_id": dishes[0]["id"], "qty": qty}, headers=student)
    await client.post("/api/cart/items", json={"dish_id": dishes[1]["id"], "qty": 1}, headers=student)
    r = await client.post("/api/orders", json={"slot_id": slot_id, "pickup_date": on, "use_bonus": use_bonus}, headers=student)
    assert r.status_code == 201, r.text
    return r.json()


async def start_payment(client, student, order, method="card"):
    r = await client.post(f"/api/orders/{order['id']}/pay", json={"method": method}, headers=student)
    assert r.status_code == 200, r.text
    return r.json()


def ref_of(result):
    return result["provider_ref"]


async def webhook(client, pid, event="payment.succeeded", body_override=None):
    body = {"type": "notification", "event": event, "object": {"id": pid, **(body_override or {})}}
    return await client.post("/api/payments/webhook/yookassa", json=body)


async def balance():
    async with SessionLocal() as s:
        return (await s.scalar(select(User).where(User.email == "student@rosbiotech.ru"))).bonus_balance


# --------------------------------------------------------------------------- #
async def test_config_reports_real_provider(client):
    cfg = (await client.get("/api/payments/config")).json()
    assert cfg == {"provider": "yookassa", "demo": False, "configured": True, "methods": ["sbp", "card"]}


async def test_success_via_webhook_is_idempotent(client, student, fake):
    order = await new_order(client, student)
    result = await start_payment(client, student, order)
    assert result["ok"] is False and result["status"] == "pending"
    pid = ref_of(result)
    assert result["confirmation_url"].endswith(pid)

    req = next(r for r in fake.requests if r.method == "POST" and r.url.path.endswith("/payments"))
    assert req.headers["Idempotence-Key"].startswith("rospit-pay-")
    sent = json.loads(req.content)
    assert sent["capture"] is True
    assert sent["payment_method_data"] == {"type": "bank_card"}
    assert sent["confirmation"]["return_url"].endswith(f"/#/order/{order['id']}?payment=return")
    # чек 54-ФЗ: сумма позиций совпадает с суммой платежа
    assert receipt_total(sent["receipt"]) == Decimal(sent["amount"]["value"])
    assert sent["receipt"]["customer"]["email"] == "student@rosbiotech.ru"

    status = (await client.get(f"/api/orders/{order['id']}/payment-status", headers=student)).json()
    assert status["state"] == "pending"

    before = await balance()
    fake.set_status(pid, "succeeded")
    r = await webhook(client, pid)
    assert r.json()["result"] == "paid"
    fresh = (await client.get(f"/api/orders/{order['id']}", headers=student)).json()
    assert fresh["status"] == "paid"
    after_first = await balance()
    assert after_first == before + Decimal(fresh["bonus_earned"])

    # повторный вебхук ничего не ломает и не начисляет второй раз
    r = await webhook(client, pid)
    assert r.json()["result"] == "duplicate"
    assert await balance() == after_first


async def test_sbp_and_return_polling(client, student, fake):
    order = await new_order(client, student)
    result = await start_payment(client, student, order, method="sbp")
    pid = ref_of(result)
    assert fake.payments[pid]["metadata"]["order_id"] == str(order["id"])
    sent = json.loads(next(r for r in reversed(fake.requests) if r.url.path.endswith("/payments")).content)
    assert sent["payment_method_data"] == {"type": "sbp"}
    # вебхук не дошёл, студент вернулся из банка — опрос статуса сам спрашивает ЮKassa
    fake.set_status(pid, "succeeded")
    status = (await client.get(f"/api/orders/{order['id']}/payment-status", headers=student)).json()
    assert status["state"] == "paid"


async def test_declined_payment_keeps_order_unpaid(client, student, fake):
    order = await new_order(client, student)
    pid = ref_of(await start_payment(client, student, order))
    fake.set_status(pid, "canceled", cancellation_details={"reason": "insufficient_funds"})
    assert (await webhook(client, pid, "payment.canceled")).json()["result"] == "failed"
    status = (await client.get(f"/api/orders/{order['id']}/payment-status", headers=student)).json()
    assert status["state"] == "failed"
    assert (await client.get(f"/api/orders/{order['id']}", headers=student)).json()["status"] == "created"
    # можно попробовать снова — создаётся новый платёж
    retry = await start_payment(client, student, order)
    assert ref_of(retry) != pid


async def test_simulate_failure_is_ignored_outside_demo(client, student):
    order = await new_order(client, student)
    r = await client.post(
        f"/api/orders/{order['id']}/pay", json={"method": "card", "simulate_failure": True}, headers=student
    )
    assert r.json()["status"] == "pending"


async def test_forged_webhook_body_is_not_trusted(client, student, fake):
    order = await new_order(client, student)
    pid = ref_of(await start_payment(client, student, order))
    # тело «говорит», что оплачено, но ЮKassa по API отвечает pending
    r = await webhook(client, pid, body_override={"status": "succeeded", "amount": {"value": "1.00", "currency": "RUB"}})
    assert r.json()["result"] == "pending"
    assert (await client.get(f"/api/orders/{order['id']}", headers=student)).json()["status"] == "created"

    # если же у провайдера сумма не совпала с нашей — заказ не оплачивается, деньги возвращаются
    fake.set_status(pid, "succeeded", amount={"value": "1.00", "currency": "RUB"})
    r = await webhook(client, pid)
    assert r.json()["result"] == "mismatch_refunded"
    assert any(f["payment_id"] == pid for f in fake.refunds)
    assert (await client.get(f"/api/orders/{order['id']}", headers=student)).json()["status"] == "created"


async def test_unknown_or_foreign_webhooks(client, fake):
    assert (await webhook(client, "no-such-payment")).json()["result"] == "unknown_payment"
    r = await client.post("/api/payments/webhook/yookassa", content=b"not json")
    assert r.status_code == 400

    strict = YooKassaProvider("1", "k", check_ip=True, transport=httpx.MockTransport(fake.handler))
    set_provider(strict)
    try:
        # тестовый клиент приходит с 127.0.0.1 — это не адрес ЮKassa
        assert (await webhook(client, "x")).status_code == 400
    finally:
        set_provider(YooKassaProvider("123456", "test_secret", check_ip=False,
                                      transport=httpx.MockTransport(fake.handler)))
    assert is_yookassa_ip("185.71.76.10") and is_yookassa_ip("77.75.156.11")
    assert not is_yookassa_ip("8.8.8.8") and not is_yookassa_ip("garbage")


async def test_cancel_paid_order_refunds_through_provider(client, student, fake):
    order = await new_order(client, student, use_bonus=True)
    pid = ref_of(await start_payment(client, student, order))
    fake.set_status(pid, "succeeded")
    await webhook(client, pid)

    # провайдер не принял возврат — заказ не отменяется
    fake.fail_refunds = True
    r = await client.post(f"/api/orders/{order['id']}/cancel", headers=student)
    assert r.status_code == 502
    assert (await client.get(f"/api/orders/{order['id']}", headers=student)).json()["status"] == "paid"
    fake.fail_refunds = False

    r = await client.post(f"/api/orders/{order['id']}/cancel", headers=student)
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    refund = fake.refunds[-1]
    assert refund["payment_id"] == pid
    assert refund["amount"]["value"] == f"{Decimal(order['total']):.2f}"
    assert receipt_total(refund["receipt"]) == Decimal(refund["amount"]["value"])
    async with SessionLocal() as s:
        payment = await s.scalar(select(Payment).where(Payment.provider_ref == pid))
        assert payment.status == "refunded"
        assert payment.refund_status == "succeeded" and payment.refund_ref == refund["id"]


async def test_payment_after_cutoff_is_refunded(client, student, fake):
    on = campus_today() + timedelta(days=6)
    slot = next(s for s in (await client.get(f"/api/slots?date={on.isoformat()}")).json() if s["starts_at"] == "12:00")
    freeze_campus_now(datetime.combine(on, time(10, 50)))
    order = await new_order(client, student, on=on.isoformat(), slot_id=slot["id"])
    pid = ref_of(await start_payment(client, student, order))
    # банк подтвердил оплату в 11:03, уже после отсечки в 11:00
    freeze_campus_now(datetime.combine(on, time(11, 3)))
    fake.set_status(pid, "succeeded")
    r = await webhook(client, pid)
    assert r.json()["result"] == "late_refunded"
    fresh = (await client.get(f"/api/orders/{order['id']}", headers=student)).json()
    assert fresh["status"] == "cancelled" and fresh["cancel_reason"] == "deadline"
    assert any(f["payment_id"] == pid for f in fake.refunds)
    freeze_campus_now(None)


async def test_payment_for_expired_order_is_refunded(client, student, fake):
    order = await new_order(client, student)
    pid = ref_of(await start_payment(client, student, order))
    # банк ещё не ответил, а время на оплату вышло — перед отменой сервер спрашивает банк
    async with SessionLocal() as s:
        row = await s.get(Order, order["id"])
        row.created_at = row.created_at - timedelta(minutes=20)
        await s.commit()
    fresh = (await client.get(f"/api/orders/{order['id']}", headers=student)).json()
    assert fresh["status"] == "cancelled" and fresh["cancel_reason"] == "expired"
    # деньги всё же пришли позже — автоматический возврат
    fake.set_status(pid, "succeeded")
    assert (await webhook(client, pid)).json()["result"] == "refunded"
    assert any(f["payment_id"] == pid for f in fake.refunds)


async def test_late_success_before_expiry_check_counts(client, student, fake):
    order = await new_order(client, student)
    pid = ref_of(await start_payment(client, student, order))
    fake.set_status(pid, "succeeded")  # оплачено, но вебхук потерялся
    async with SessionLocal() as s:
        row = await s.get(Order, order["id"])
        row.created_at = row.created_at - timedelta(minutes=20)
        await s.commit()
    fresh = (await client.get(f"/api/orders/{order['id']}", headers=student)).json()
    assert fresh["status"] == "paid"


async def test_provider_without_keys_answers_503(client, student, fake):
    set_provider(YooKassaProvider("", "", transport=httpx.MockTransport(fake.handler)))
    try:
        order = await new_order(client, student)
        r = await client.post(f"/api/orders/{order['id']}/pay", json={"method": "sbp"}, headers=student)
        assert r.status_code == 503
    finally:
        set_provider(YooKassaProvider("123456", "test_secret", check_ip=False,
                                      transport=httpx.MockTransport(fake.handler)))


# --------------------------------------------------------------------------- #
def test_receipt_spreads_bonus_discount_to_the_kopek():
    items = [
        SimpleNamespace(id=1, name="Борщ с говядиной", qty=3, price=Decimal("139.00")),
        SimpleNamespace(id=2, name="Котлета по-киевски", qty=1, price=Decimal("259.00")),
        SimpleNamespace(id=3, name="Морс клюквенный", qty=2, price=Decimal("69.00")),
    ]
    subtotal = sum(i.qty * i.price for i in items)   # 814.00
    for discount in (Decimal("0"), Decimal("0.01"), Decimal("98.70"), Decimal("244.20"), Decimal("33.33")):
        order = SimpleNamespace(items=items, total=subtotal - discount)
        receipt = build_receipt(order, "s@rosbiotech.ru")
        assert receipt_total(receipt) == subtotal - discount
        assert sum(Decimal(i["quantity"]) for i in receipt["items"]) == 6
        assert all(i["vat_code"] == 1 and i["payment_mode"] == "full_payment" for i in receipt["items"])


def test_provider_selection_from_settings():
    assert Settings(payment_provider="", demo_payments=True).active_payment_provider == "demo"
    # старый флаг теперь реально переключает провайдера
    assert Settings(payment_provider="", demo_payments=False).active_payment_provider == "yookassa"
    assert Settings(payment_provider="YooKassa", demo_payments=True).active_payment_provider == "yookassa"


async def test_demo_provider_contract():
    from app.payments.base import PaymentRequest

    demo = DemoProvider()
    ok = await demo.create_payment(PaymentRequest(1, 1, "RP-1", Decimal("10"), "sbp", "", "x"))
    assert ok.status == "succeeded"
    bad = await demo.create_payment(PaymentRequest(2, 1, "RP-1", Decimal("10"), "sbp", "", "x", simulate_failure=True))
    assert bad.status == "canceled"
    assert (await demo.refund(ok.provider_ref, Decimal("10"))).status == "succeeded"
