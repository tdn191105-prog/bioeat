"""Общие помощники тестов: вход, заголовки, быстрый заказ."""
from __future__ import annotations

from datetime import timedelta

from app.services import campus_today


async def login(client, email, password):
    r = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def tomorrow() -> str:
    return (campus_today() + timedelta(days=1)).isoformat()


async def place_order(client, headers, *, slot_id=None, on_date=None, dish_index=0, qty=1,
                      pay=False):
    """Кладёт одно блюдо в корзину и оформляет заказ. Возвращает JSON заказа."""
    on_date = on_date or tomorrow()
    dishes = (await client.get("/api/dishes")).json()
    available = [d for d in dishes if d["stock_qty"] >= qty]
    dish = available[dish_index % len(available)]
    await client.delete("/api/cart", headers=headers)
    r = await client.post("/api/cart/items", json={"dish_id": dish["id"], "qty": qty}, headers=headers)
    assert r.status_code == 200, r.text
    if slot_id is None:
        slots = (await client.get(f"/api/slots?date={on_date}")).json()
        slot_id = next(s for s in slots if s["is_available"])["id"]
    r = await client.post(
        "/api/orders", json={"slot_id": slot_id, "pickup_date": on_date}, headers=headers
    )
    assert r.status_code == 201, r.text
    order = r.json()
    if pay:
        r = await client.post(f"/api/orders/{order['id']}/pay", json={"method": "sbp"}, headers=headers)
        assert r.status_code == 200 and r.json()["ok"], r.text
        order = r.json()["order"]
    return order
