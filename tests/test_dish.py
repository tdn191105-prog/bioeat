"""Тесты карточки блюда: новые поля, справочник аллергенов, фотографии,
популярное, повтор заказа и автомиграция.

Запуск:  pytest -q
База:    отдельная SQLite-файловая БД (реальный Postgres не требуется).
"""
from __future__ import annotations

import io
import os
import pathlib
import sys

import pytest
import pytest_asyncio

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TEST_DB = ROOT / "test_bioeat_dish.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_DB}"
os.environ["SECRET_KEY"] = "test-secret"

from asgi_lifespan import LifespanManager  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from PIL import Image  # noqa: E402

from app.images import MAX_UPLOAD_BYTES  # noqa: E402
from app.main import app  # noqa: E402
from app.reference import ALLERGENS  # noqa: E402

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


def make_image(width=900, height=700, fmt="JPEG") -> bytes:
    """Настоящая картинка нужного формата — не заглушка из байтов."""
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (120, 70, 40)).save(buffer, format=fmt)
    return buffer.getvalue()


# --------------------------------------------------------------------------- #
#  Новые поля блюда
# --------------------------------------------------------------------------- #
NEW_FIELDS = (
    "image_url", "image_thumb_url", "image_placeholder",
    "image_author", "image_license", "image_source_url",
    "ingredients", "allergens",
)


async def test_dish_list_exposes_new_fields(client):
    r = await client.get("/api/dishes")
    assert r.status_code == 200
    dishes = r.json()
    assert dishes
    for field in NEW_FIELDS:
        assert field in dishes[0], f"в списке блюд нет поля {field}"


async def test_single_dish_exposes_new_fields(client):
    dish_id = (await client.get("/api/dishes")).json()[0]["id"]
    dish = (await client.get(f"/api/dishes/{dish_id}")).json()
    for field in NEW_FIELDS:
        assert field in dish, f"в карточке блюда нет поля {field}"
    assert isinstance(dish["ingredients"], list)
    assert isinstance(dish["allergens"], list)


async def test_seed_fills_ingredients_and_allergens(client):
    """Состав должен быть у всех позиций, а аллергены — согласованы с ним."""
    dishes = (await client.get("/api/dishes")).json()
    without_ingredients = [d["name"] for d in dishes if not d["ingredients"]]
    assert not without_ingredients, f"без состава остались: {without_ingredients}"

    codes = set(ALLERGENS)
    for dish in dishes:
        unknown = set(dish["allergens"]) - codes
        assert not unknown, f"«{dish['name']}»: неизвестные коды аллергенов {unknown}"

    borsch = next(d for d in dishes if d["name"].startswith("Борщ"))
    assert "сметана" in borsch["ingredients"]
    assert borsch["allergens"] == ["milk"]

    syrniki = next(d for d in dishes if d["name"].startswith("Сырники"))
    assert set(syrniki["allergens"]) == {"milk", "eggs", "gluten"}

    cod = next(d for d in dishes if d["name"].startswith("Треска"))
    assert cod["allergens"] == ["fish"]

    plov = next(d for d in dishes if d["name"].startswith("Плов"))
    assert plov["allergens"] == []


async def test_diet_tags_do_not_contradict_ingredients(client):
    """Метка диеты не должна противоречить составу."""
    meat = ("говядин", "свинин", "барани", "куриное филе", "куриный", "фарш",
            "бекон", "ветчин", "колбас", "сосиск", "грудинк", "пепперони",
            "филе трески", "бульон мясной", "котлета мясная")
    dairy = ("молоко цельное", "сливк", "сметан", "творог", "сыр ", "масло сливочное",
             "фета", "пармезан", "моцарелл", "йогурт")
    gluten = ("мука пшеничная", "мука ржаная", "булгур", "спагетти", "макаронные",
              "лапша", "сухари", "гренки", "хлеб", "хлопья овсяные", "солод")

    problems = []
    for dish in (await client.get("/api/dishes")).json():
        items = [i.lower() for i in dish["ingredients"]]
        joined = " ; ".join(items)
        tags = dish["tags"]
        has_dairy = any(i == "молоко" or any(d in i for d in dairy) for i in items)
        if "veg" in tags and any(m in joined for m in meat):
            problems.append(f"{dish['name']}: veg, но в составе мясо или рыба")
        if "no_lactose" in tags and has_dairy:
            problems.append(f"{dish['name']}: no_lactose, но в составе молочное")
        if "no_gluten" in tags and any(g in joined for g in gluten):
            problems.append(f"{dish['name']}: no_gluten, но в составе злаки с глютеном")
    assert not problems, problems


# --------------------------------------------------------------------------- #
#  Справочник аллергенов
# --------------------------------------------------------------------------- #
async def test_allergen_reference_has_14_groups(client):
    r = await client.get("/api/reference/allergens")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 14, "в ТР ТС 022/2011 ровно 14 групп аллергенов"

    codes = [a["code"] for a in data]
    assert codes == list(ALLERGENS)
    for item in data:
        assert item["name"] and item["icon"] and item["color"]


# --------------------------------------------------------------------------- #
#  Фотография блюда
# --------------------------------------------------------------------------- #
async def test_image_upload_success(client):
    token = await login(client, "admin@rosbiotech.ru", "admin")
    dish_id = (await client.get("/api/dishes")).json()[0]["id"]

    r = await client.post(
        f"/api/admin/dishes/{dish_id}/image",
        headers=auth(token),
        files={"file": ("photo.jpg", make_image(), "image/jpeg")},
    )
    assert r.status_code == 200, r.text
    dish = r.json()
    assert dish["image_url"].startswith("/static/uploads/dishes/")
    assert dish["image_thumb_url"].endswith("-thumb.webp")
    assert dish["image_placeholder"].startswith("#") and len(dish["image_placeholder"]) == 7

    # файлы действительно записаны на диск
    assert (ROOT / dish["image_url"].lstrip("/")).exists()
    assert (ROOT / dish["image_thumb_url"].lstrip("/")).exists()


async def test_image_upload_rejects_wrong_content_type(client):
    token = await login(client, "admin@rosbiotech.ru", "admin")
    dish_id = (await client.get("/api/dishes")).json()[0]["id"]
    r = await client.post(
        f"/api/admin/dishes/{dish_id}/image",
        headers=auth(token),
        files={"file": ("doc.pdf", make_image(), "application/pdf")},
    )
    assert r.status_code == 415


async def test_image_upload_rejects_fake_image(client):
    """Расширение и Content-Type подделать легко — формат проверяет Pillow."""
    token = await login(client, "admin@rosbiotech.ru", "admin")
    dish_id = (await client.get("/api/dishes")).json()[0]["id"]
    r = await client.post(
        f"/api/admin/dishes/{dish_id}/image",
        headers=auth(token),
        files={"file": ("photo.jpg", b"PK\x03\x04 not an image at all" * 40, "image/jpeg")},
    )
    assert r.status_code == 422


async def test_image_upload_rejects_too_large(client):
    token = await login(client, "admin@rosbiotech.ru", "admin")
    dish_id = (await client.get("/api/dishes")).json()[0]["id"]
    oversized = b"\xff\xd8\xff\xe0" + b"\x00" * (MAX_UPLOAD_BYTES + 1024)
    r = await client.post(
        f"/api/admin/dishes/{dish_id}/image",
        headers=auth(token),
        files={"file": ("big.jpg", oversized, "image/jpeg")},
    )
    assert r.status_code == 413


async def test_image_upload_forbidden_for_non_admin(client):
    dish_id = (await client.get("/api/dishes")).json()[0]["id"]

    # вход кладёт токен и в cookie, поэтому «анонимный» запрос без явной
    # очистки унёс бы права предыдущего теста
    client.cookies.clear()
    r = await client.post(
        f"/api/admin/dishes/{dish_id}/image",
        files={"file": ("photo.jpg", make_image(), "image/jpeg")},
    )
    assert r.status_code == 401

    student = await login(client, "student@rosbiotech.ru", "student")
    r = await client.post(
        f"/api/admin/dishes/{dish_id}/image",
        headers=auth(student),
        files={"file": ("photo.jpg", make_image(), "image/jpeg")},
    )
    assert r.status_code == 403


async def test_image_delete_resets_fields(client):
    token = await login(client, "admin@rosbiotech.ru", "admin")
    dish_id = (await client.get("/api/dishes")).json()[0]["id"]

    uploaded = (
        await client.post(
            f"/api/admin/dishes/{dish_id}/image",
            headers=auth(token),
            files={"file": ("photo.png", make_image(fmt="PNG"), "image/png")},
        )
    ).json()
    stored = ROOT / uploaded["image_url"].lstrip("/")
    assert stored.exists()

    r = await client.delete(f"/api/admin/dishes/{dish_id}/image", headers=auth(token))
    assert r.status_code == 200
    dish = r.json()
    assert dish["image_url"] == ""
    assert dish["image_thumb_url"] == ""
    assert dish["image_placeholder"] == ""
    assert dish["image_author"] == ""
    assert dish["image_license"] == ""
    assert not stored.exists(), "файл загруженного фото должен удаляться"


# --------------------------------------------------------------------------- #
#  Популярное
# --------------------------------------------------------------------------- #
async def test_popular_survives_empty_sales(client):
    """На свежей базе продаж нет — эндпоинт обязан отвечать, а не падать."""
    r = await client.get("/api/dishes/popular")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list) and data, "нужен откат на тег hit и на меню"
    assert "name" in data[0] and "image_thumb_url" in data[0]


async def test_popular_respects_limit(client):
    r = await client.get("/api/dishes/popular?limit=3")
    assert r.status_code == 200
    assert len(r.json()) == 3
    # «popular» не должен попасть в маршрут /api/dishes/{dish_id}
    assert r.json()[0]["id"] > 0


# --------------------------------------------------------------------------- #
#  Повтор заказа
# --------------------------------------------------------------------------- #
async def _make_paid_order(client, token) -> dict:
    dishes = (await client.get("/api/dishes")).json()
    first, second = dishes[0], dishes[1]
    for dish in (first, second):
        r = await client.post(
            "/api/cart/items", json={"dish_id": dish["id"], "qty": 2}, headers=auth(token)
        )
        assert r.status_code == 200, r.text

    slots = (await client.get("/api/slots")).json()
    slot = next((s for s in slots if s["is_available"]), None)
    if slot is None:  # приём на сегодня закрыт — оформляем на завтра
        from datetime import date, timedelta

        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        slots = (await client.get(f"/api/slots?date={tomorrow}")).json()
        slot = next(s for s in slots if s["is_available"])
        payload = {"slot_id": slot["id"], "pickup_date": tomorrow}
    else:
        payload = {"slot_id": slot["id"]}

    r = await client.post("/api/orders", json=payload, headers=auth(token))
    assert r.status_code == 201, r.text
    order = r.json()
    await client.post(f"/api/orders/{order['id']}/pay", json={"method": "sbp"}, headers=auth(token))
    return order


async def test_repeat_order_fills_cart(client):
    token = await login(client, "student@rosbiotech.ru", "student")
    order = await _make_paid_order(client, token)

    await client.delete("/api/cart", headers=auth(token))
    r = await client.post(f"/api/orders/{order['id']}/repeat", headers=auth(token))
    assert r.status_code == 200, r.text
    result = r.json()

    assert len(result["added"]) == 2
    assert result["skipped"] == []
    assert result["cart"]["count"] == 4  # по 2 порции каждой позиции

    ordered = {i["name"] for i in order["items"]}
    assert {i["name"] for i in result["cart"]["items"]} == ordered


async def test_repeat_order_skips_unavailable(client):
    """Позиция в стоп-листе пропускается, остальное всё равно попадает в корзину."""
    token = await login(client, "student@rosbiotech.ru", "student")
    admin = await login(client, "admin@rosbiotech.ru", "admin")
    order = await _make_paid_order(client, token)

    missing = order["items"][0]
    r = await client.post(
        f"/api/admin/dishes/{missing['dish_id']}/stock?qty=0", headers=auth(admin)
    )
    assert r.status_code == 200

    await client.delete("/api/cart", headers=auth(token))
    result = (await client.post(f"/api/orders/{order['id']}/repeat", headers=auth(token))).json()

    assert missing["name"] not in result["added"]
    skipped_names = [s["name"] for s in result["skipped"]]
    assert missing["name"] in skipped_names
    assert result["skipped"][0]["reason"], "причина пропуска должна быть заполнена"
    assert len(result["added"]) == 1, "доступная позиция обязана добавиться"

    # возвращаем остаток, чтобы не мешать другим тестам
    await client.post(f"/api/admin/dishes/{missing['dish_id']}/stock?qty=50", headers=auth(admin))


async def test_repeat_order_is_not_available_for_other_user(client):
    token = await login(client, "student@rosbiotech.ru", "student")
    order = await _make_paid_order(client, token)

    admin = await login(client, "admin@rosbiotech.ru", "admin")
    r = await client.post(f"/api/orders/{order['id']}/repeat", headers=auth(admin))
    assert r.status_code == 403


# --------------------------------------------------------------------------- #
#  Автомиграция
# --------------------------------------------------------------------------- #
async def test_ensure_columns_adds_missing_column(tmp_path):
    """Таблица без новой колонки должна получить её при старте приложения."""
    import sqlalchemy as sa
    from sqlalchemy.ext.asyncio import create_async_engine

    import app.db as db_module

    db_file = tmp_path / "legacy.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")

    # старая схема: dishes без ingredients, allergens и полей фотографии
    async with engine.begin() as conn:
        await conn.execute(
            sa.text(
                """
                CREATE TABLE dishes (
                    id INTEGER PRIMARY KEY,
                    category_id INTEGER NOT NULL,
                    name VARCHAR(160) NOT NULL,
                    description TEXT,
                    price NUMERIC(10, 2) NOT NULL,
                    weight_g INTEGER,
                    kcal INTEGER,
                    protein NUMERIC(6, 1),
                    fat NUMERIC(6, 1),
                    carbs NUMERIC(6, 1),
                    icon VARCHAR(16),
                    tags TEXT,
                    stock_qty INTEGER,
                    is_active BOOLEAN,
                    sort_order INTEGER,
                    created_at TIMESTAMP
                )
                """
            )
        )
        await conn.execute(
            sa.text("INSERT INTO dishes (id, category_id, name, price) VALUES (1, 1, 'Борщ', 139)")
        )

    def columns(sync_conn):
        return {c["name"] for c in sa.inspect(sync_conn).get_columns("dishes")}

    async with engine.begin() as conn:
        before = await conn.run_sync(columns)
    assert "ingredients" not in before
    assert "image_url" not in before

    # подменяем движок приложения на подготовленную «старую» базу
    original = db_module.engine
    db_module.engine = engine
    try:
        added = await db_module.ensure_columns()
    finally:
        db_module.engine = original

    async with engine.begin() as conn:
        after = await conn.run_sync(columns)

    for column in ("ingredients", "allergens", "image_url", "image_thumb_url",
                   "image_placeholder", "image_author", "image_license", "image_source_url"):
        assert column in after, f"автомиграция не добавила колонку {column}"
        assert f"dishes.{column}" in added

    # существующая строка не потеряна, новые колонки получили значения по умолчанию
    async with engine.begin() as conn:
        row = (await conn.execute(sa.text("SELECT name, ingredients, image_url FROM dishes"))).one()
    assert row[0] == "Борщ"
    assert row[1] == "[]"
    assert row[2] == ""

    await engine.dispose()


async def test_ensure_columns_is_idempotent(tmp_path):
    """Повторный вызов на актуальной схеме ничего не добавляет и не падает."""
    import app.db as db_module

    added = await db_module.ensure_columns()
    assert added == []
