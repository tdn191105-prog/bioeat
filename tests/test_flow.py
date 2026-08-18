"""Сквозные тесты API BioEat.

Запуск:  pytest -q
База:    отдельная SQLite-файловая БД (реальный Postgres не требуется).
"""
from __future__ import annotations

import os
import pathlib
import sys
from datetime import date, timedelta

import pytest
import pytest_asyncio

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TEST_DB = ROOT / "test_bioeat.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_DB}"
os.environ["SECRET_KEY"] = "test-secret"

from asgi_lifespan import LifespanManager  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.main import app  # noqa: E402

TOMORROW = (date.today() + timedelta(days=1)).isoformat()

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(scope="module")
async def client():
    if TEST_DB.exists():
        TEST_DB.unlink()
    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
    if TEST_DB.exists():
        TEST_DB.unlink()


async def login(client, email, password):
    r = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def auth(token):
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------------- #
async def test_health(client):
    r = await client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


async def test_menu_seeded(client):
    cats = (await client.get("/api/categories")).json()
    dishes = (await client.get("/api/dishes")).json()
    assert len(cats) >= 8
    assert len(dishes) >= 40
    assert all(d["price"] for d in dishes)


async def test_menu_filters(client):
    pp = (await client.get("/api/dishes?tag=pp")).json()
    assert pp and all("pp" in d["tags"] for d in pp)

    soups = (await client.get("/api/dishes?category=soups")).json()
    assert soups and len({d["category_id"] for d in soups}) == 1

    found = (await client.get("/api/dishes?q=борщ")).json()
    assert any("Борщ" in d["name"] for d in found)


async def test_login_bad_password(client):
    r = await client.post(
        "/api/auth/login", json={"email": "student@rosbiotech.ru", "password": "wrong"}
    )
    assert r.status_code == 401


async def test_cart_requires_auth(client):
    r = await client.get("/api/cart", headers={"Authorization": "Bearer nonsense"})
    assert r.status_code == 401


async def test_cart_and_order_flow(client):
    token = await login(client, "student@rosbiotech.ru", "student")
    h = auth(token)

    dishes = (await client.get("/api/dishes")).json()
    first, second = dishes[0], dishes[5]

    await client.delete("/api/cart", headers=h)
    cart = (await client.post("/api/cart/items", json={"dish_id": first["id"], "qty": 2}, headers=h)).json()
    assert cart["count"] == 2
    cart = (await client.post("/api/cart/items", json={"dish_id": second["id"], "qty": 1}, headers=h)).json()
    assert cart["count"] == 3

    expected = float(first["price"]) * 2 + float(second["price"])
    assert abs(float(cart["subtotal"]) - expected) < 0.01

    # точное количество
    cart = (await client.put("/api/cart/items", json={"dish_id": first["id"], "qty": 1}, headers=h)).json()
    assert cart["count"] == 2
    # удаление
    cart = (await client.delete(f"/api/cart/items/{second['id']}", headers=h)).json()
    assert cart["count"] == 1

    slots = (await client.get(f"/api/slots?date={TOMORROW}")).json()
    slot = next(s for s in slots if s["is_available"])

    r = await client.post(
        "/api/orders",
        json={"slot_id": slot["id"], "comment": "без лука", "use_bonus": True, "pickup_date": TOMORROW},
        headers=h,
    )
    assert r.status_code == 201, r.text
    order = r.json()
    assert order["status"] == "created"
    assert order["comment"] == "без лука"
    assert float(order["bonus_used"]) > 0
    assert float(order["total"]) == pytest.approx(
        float(order["subtotal"]) - float(order["bonus_used"]), abs=0.01
    )

    # корзина очищена
    assert (await client.get("/api/cart", headers=h)).json()["count"] == 0

    # оплата
    r = await client.post(f"/api/orders/{order['id']}/pay", json={"method": "sbp"}, headers=h)
    assert r.status_code == 200
    assert r.json()["ok"] is True
    paid = r.json()["order"]
    assert paid["status"] == "paid"

    # повторная оплата не списывает второй раз
    r = await client.post(f"/api/orders/{order['id']}/pay", json={"method": "sbp"}, headers=h)
    assert r.json()["ok"] is True
    assert "уже оплачен" in r.json()["message"]

    # QR доступен
    r = await client.get(f"/api/orders/{order['id']}/qr.svg", headers=h)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/svg")

    globals()["_ORDER"] = order
    globals()["_STUDENT_TOKEN"] = token


async def test_payment_failure_keeps_order_unpaid(client):
    token = await login(client, "student@rosbiotech.ru", "student")
    h = auth(token)
    dishes = (await client.get("/api/dishes")).json()
    await client.post("/api/cart/items", json={"dish_id": dishes[2]["id"], "qty": 1}, headers=h)

    slots = (await client.get(f"/api/slots?date={TOMORROW}")).json()
    slot = next(s for s in slots if s["is_available"])
    order = (
        await client.post(
            "/api/orders", json={"slot_id": slot["id"], "pickup_date": TOMORROW}, headers=h
        )
    ).json()

    r = await client.post(
        f"/api/orders/{order['id']}/pay", json={"method": "card", "simulate_failure": True}, headers=h
    )
    assert r.status_code == 200
    assert r.json()["ok"] is False

    fresh = (await client.get(f"/api/orders/{order['id']}", headers=h)).json()
    assert fresh["status"] == "created"

    # отмена возвращает порции
    r = await client.post(f"/api/orders/{order['id']}/cancel", headers=h)
    assert r.json()["status"] == "cancelled"


async def test_stock_is_reserved_and_restored(client):
    token = await login(client, "student@rosbiotech.ru", "student")
    h = auth(token)
    dish = (await client.get("/api/dishes?category=desserts")).json()[0]
    before = (await client.get(f"/api/dishes/{dish['id']}")).json()["stock_qty"]

    await client.delete("/api/cart", headers=h)
    await client.post("/api/cart/items", json={"dish_id": dish["id"], "qty": 3}, headers=h)
    slots = (await client.get(f"/api/slots?date={TOMORROW}")).json()
    slot = next(s for s in slots if s["is_available"])
    order = (
        await client.post(
            "/api/orders", json={"slot_id": slot["id"], "pickup_date": TOMORROW}, headers=h
        )
    ).json()

    during = (await client.get(f"/api/dishes/{dish['id']}")).json()["stock_qty"]
    assert during == before - 3

    await client.post(f"/api/orders/{order['id']}/cancel", headers=h)
    after = (await client.get(f"/api/dishes/{dish['id']}")).json()["stock_qty"]
    assert after == before


async def test_cannot_order_more_than_stock(client):
    admin = await login(client, "admin@rosbiotech.ru", "admin")
    student = await login(client, "student@rosbiotech.ru", "student")

    dish = (await client.get("/api/dishes?category=drinks")).json()[0]
    await client.post(f"/api/admin/dishes/{dish['id']}/stock?qty=2", headers=auth(admin))

    r = await client.post(
        "/api/cart/items", json={"dish_id": dish["id"], "qty": 5}, headers=auth(student)
    )
    assert r.status_code == 409
    assert "Осталось" in r.json()["detail"]

    await client.post(f"/api/admin/dishes/{dish['id']}/stock?qty=100", headers=auth(admin))


async def test_empty_cart_rejected(client):
    token = await login(client, "student@rosbiotech.ru", "student")
    h = auth(token)
    await client.delete("/api/cart", headers=h)
    slots = (await client.get(f"/api/slots?date={TOMORROW}")).json()
    slot = next(s for s in slots if s["is_available"])
    r = await client.post(
        "/api/orders", json={"slot_id": slot["id"], "pickup_date": TOMORROW}, headers=h
    )
    assert r.status_code == 400


async def test_past_date_rejected(client):
    token = await login(client, "student@rosbiotech.ru", "student")
    h = auth(token)
    dishes = (await client.get("/api/dishes")).json()
    await client.post("/api/cart/items", json={"dish_id": dishes[1]["id"], "qty": 1}, headers=h)
    slots = (await client.get(f"/api/slots?date={TOMORROW}")).json()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    r = await client.post(
        "/api/orders", json={"slot_id": slots[0]["id"], "pickup_date": yesterday}, headers=h
    )
    assert r.status_code == 400
    await client.delete("/api/cart", headers=h)


async def test_operator_flow_and_issue(client):
    order = globals()["_ORDER"]
    student_token = globals()["_STUDENT_TOKEN"]
    op = await login(client, "operator@rosbiotech.ru", "operator")
    h = auth(op)

    board = (await client.get(f"/api/operator/board?date={TOMORROW}", headers=h)).json()
    assert board["counts"]["paid"] >= 1

    # выдать неготовый заказ нельзя
    r = await client.post("/api/operator/issue", json={"code": order["pickup_code"]}, headers=h)
    assert r.status_code == 409

    # недопустимый переход статуса
    r = await client.patch(
        f"/api/operator/orders/{order['id']}/status", json={"status": "issued"}, headers=h
    )
    assert r.status_code == 409

    for status in ("accepted", "cooking", "ready"):
        r = await client.patch(
            f"/api/operator/orders/{order['id']}/status", json={"status": status}, headers=h
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == status

    r = await client.post("/api/operator/issue", json={"code": order["pickup_code"]}, headers=h)
    assert r.status_code == 200
    assert r.json()["status"] == "issued"

    # повторная выдача запрещена
    r = await client.post("/api/operator/issue", json={"code": order["pickup_code"]}, headers=h)
    assert r.status_code == 409

    # подделанный код не проходит
    r = await client.post("/api/operator/issue", json={"code": "BIOEAT:BE-0001:aaa:bbb"}, headers=h)
    assert r.status_code in (404, 409)

    # студент больше не может отменить выданный заказ
    r = await client.post(f"/api/orders/{order['id']}/cancel", headers=auth(student_token))
    assert r.status_code == 409


async def test_student_cannot_reach_staff_endpoints(client):
    token = await login(client, "student@rosbiotech.ru", "student")
    h = auth(token)
    assert (await client.get("/api/operator/queue", headers=h)).status_code == 403
    assert (await client.get("/api/admin/dishes", headers=h)).status_code == 403
    assert (await client.get("/api/admin/stats", headers=h)).status_code == 403


async def test_operator_cannot_edit_menu(client):
    token = await login(client, "operator@rosbiotech.ru", "operator")
    r = await client.get("/api/admin/dishes", headers=auth(token))
    assert r.status_code == 403


async def test_admin_menu_crud(client):
    token = await login(client, "admin@rosbiotech.ru", "admin")
    h = auth(token)

    cats = (await client.get("/api/admin/categories", headers=h)).json()

    r = await client.post(
        "/api/admin/dishes",
        json={
            "category_id": cats[0]["id"],
            "name": "Тестовое блюдо",
            "description": "только для теста",
            "price": 123.5,
            "weight_g": 200,
            "kcal": 300,
            "icon": "🧪",
            "tags": ["pp"],
            "stock_qty": 7,
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    dish = r.json()
    assert dish["name"] == "Тестовое блюдо"
    assert float(dish["price"]) == 123.5

    # появилось в публичном меню
    assert any(d["id"] == dish["id"] for d in (await client.get("/api/dishes")).json())

    # правка
    r = await client.patch(f"/api/admin/dishes/{dish['id']}", json={"price": 200}, headers=h)
    assert float(r.json()["price"]) == 200

    # скрытие
    r = await client.delete(f"/api/admin/dishes/{dish['id']}", headers=h)
    assert r.json()["mode"] == "hidden"
    assert not any(d["id"] == dish["id"] for d in (await client.get("/api/dishes")).json())

    # полное удаление
    r = await client.delete(f"/api/admin/dishes/{dish['id']}?hard=true", headers=h)
    assert r.json()["mode"] == "deleted"
    assert (await client.get(f"/api/dishes/{dish['id']}")).status_code == 404


async def test_admin_category_and_slot_crud(client):
    token = await login(client, "admin@rosbiotech.ru", "admin")
    h = auth(token)

    r = await client.post(
        "/api/admin/categories", json={"name": "Завтраки тест", "icon": "🍳"}, headers=h
    )
    assert r.status_code == 201
    cat = r.json()
    assert cat["slug"] == "zavtraki-test"

    r = await client.delete(f"/api/admin/categories/{cat['id']}", headers=h)
    assert r.status_code == 200

    r = await client.post(
        "/api/admin/slots",
        json={"label": "Тестовое окно", "starts_at": "20:00", "ends_at": "20:30", "capacity": 5},
        headers=h,
    )
    assert r.status_code == 201, r.text
    slot = r.json()
    assert slot["capacity"] == 5

    r = await client.patch(f"/api/admin/slots/{slot['id']}", json={"capacity": 9}, headers=h)
    assert r.json()["capacity"] == 9

    # окончание раньше начала — ошибка
    r = await client.post(
        "/api/admin/slots",
        json={"label": "Кривое", "starts_at": "12:00", "ends_at": "11:00"},
        headers=h,
    )
    assert r.status_code == 422

    assert (await client.delete(f"/api/admin/slots/{slot['id']}", headers=h)).status_code == 200


async def test_slot_capacity_is_enforced(client):
    admin = await login(client, "admin@rosbiotech.ru", "admin")
    r = await client.post(
        "/api/admin/slots",
        json={"label": "Узкое окно", "starts_at": "21:00", "ends_at": "21:15", "capacity": 1},
        headers=auth(admin),
    )
    slot_id = r.json()["id"]

    student = await login(client, "student@rosbiotech.ru", "student")
    h = auth(student)
    dishes = (await client.get("/api/dishes")).json()

    await client.delete("/api/cart", headers=h)
    await client.post("/api/cart/items", json={"dish_id": dishes[3]["id"], "qty": 1}, headers=h)
    r1 = await client.post(
        "/api/orders", json={"slot_id": slot_id, "pickup_date": TOMORROW}, headers=h
    )
    assert r1.status_code == 201
    await client.post(f"/api/orders/{r1.json()['id']}/pay", json={"method": "sbp"}, headers=h)

    await client.post("/api/cart/items", json={"dish_id": dishes[4]["id"], "qty": 1}, headers=h)
    r2 = await client.post(
        "/api/orders", json={"slot_id": slot_id, "pickup_date": TOMORROW}, headers=h
    )
    assert r2.status_code == 409
    assert "мест" in r2.json()["detail"]

    await client.post(f"/api/orders/{r1.json()['id']}/cancel", headers=h)
    await client.delete("/api/cart", headers=h)


async def test_admin_stats(client):
    token = await login(client, "admin@rosbiotech.ru", "admin")
    stats = (await client.get(f"/api/admin/stats?date={TOMORROW}", headers=auth(token))).json()
    assert stats["orders_today"] >= 1
    assert "top_dishes" in stats and isinstance(stats["top_dishes"], list)
    assert stats["users_total"] >= 3


async def test_registration_and_role_change(client):
    r = await client.post(
        "/api/auth/register",
        json={
            "email": "newbie@rosbiotech.ru",
            "password": "secret",
            "full_name": "Новиков Пётр",
            "group_name": "24о-000000-ТТ/1",
        },
    )
    assert r.status_code == 201
    user = r.json()["user"]
    assert user["role"] == "student"

    # повторная регистрация с той же почтой
    r = await client.post(
        "/api/auth/register",
        json={"email": "newbie@rosbiotech.ru", "password": "secret", "full_name": "Дубль"},
    )
    assert r.status_code == 409

    admin = await login(client, "admin@rosbiotech.ru", "admin")
    r = await client.patch(f"/api/admin/users/{user['id']}/role?role=operator", headers=auth(admin))
    assert r.json()["role"] == "operator"

    # новая учётная запись оператора
    r = await client.post(
        "/api/admin/users?email=kitchen@rosbiotech.ru&password=kitchen&full_name=Повар+Иванов&role=operator",
        headers=auth(admin),
    )
    assert r.status_code == 201
    assert r.json()["role"] == "operator"


async def test_spa_fallback_and_unknown_api(client):
    r = await client.get("/some/deep/route")
    assert r.status_code == 200
    assert "BioEat" in r.text

    r = await client.get("/api/definitely-missing")
    assert r.status_code == 404
