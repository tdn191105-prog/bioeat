"""Переименование в РосПит: видимые названия и обратная совместимость."""
from __future__ import annotations

import json

import pytest_asyncio
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update

from app.db import SessionLocal
from app.main import app
from app.models import Order
from app.security import _pickup_signature, make_pickup_code, verify_pickup_code
from app.services import order_number_candidates
from tests.helpers import auth, login, place_order


@pytest_asyncio.fixture(scope="module")
async def client():
    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c


async def test_visible_names(client):
    assert (await client.get("/api/health")).json()["app"] == "rospit"
    manifest = json.loads((await client.get("/manifest.webmanifest")).text)
    assert manifest["short_name"] == "РосПит"
    assert manifest["name"] == "РосПит · Столовая РОСБИОТЕХ"
    assert any(i["purpose"] == "maskable" for i in manifest["icons"])
    page = (await client.get("/")).text
    assert '<meta name="apple-mobile-web-app-title" content="РосПит">' in page
    assert (await client.get("/api/openapi.json")).json()["info"]["title"] == "РосПит API"
    assert (await client.get("/favicon.ico")).status_code == 200


def test_pickup_code_prefixes():
    code = make_pickup_code("RP-1234")
    assert code.startswith("ROSPIT:")
    assert verify_pickup_code(code) == "RP-1234"
    # старые коды остаются действительными
    legacy = f"BIOEAT:BE-1234:abc:{_pickup_signature('BE-1234:abc')}"
    assert verify_pickup_code(legacy) == "BE-1234"
    assert verify_pickup_code("OTHER:BE-1234:abc:" + _pickup_signature("BE-1234:abc")) is None


def test_number_candidates():
    assert order_number_candidates("rp-0042") == ["RP-0042"]
    assert order_number_candidates("BE 0042") == ["BE-0042"]
    assert order_number_candidates("rp0042") == ["RP-0042"]
    assert order_number_candidates("0042") == ["RP-0042", "BE-0042"]


async def test_new_orders_use_rp_prefix_and_legacy_numbers_still_issue(client):
    student = auth(await login(client, "student@rosbiotech.ru", "student"))
    op = auth(await login(client, "operator@rosbiotech.ru", "operator"))

    order = await place_order(client, student, pay=True)
    assert order["number"].startswith("RP-")
    assert order["pickup_code"].startswith("ROSPIT:")

    # превращаем заказ в «старый»: номер BE- и QR с префиксом BIOEAT:
    legacy_number = "BE-" + order["number"].split("-")[1]
    legacy_code = f"BIOEAT:{legacy_number}:feed:{_pickup_signature(legacy_number + ':feed')}"
    async with SessionLocal() as s:
        await s.execute(
            update(Order)
            .where(Order.id == order["id"])
            .values(number=legacy_number, pickup_code=legacy_code)
        )
        await s.commit()

    digits = legacy_number.split("-")[1]
    for raw in (legacy_number, digits, legacy_code):
        r = await client.get(f"/api/operator/lookup/{raw}", headers=op)
        assert r.status_code == 200, raw
        assert r.json()["number"] == legacy_number

    for status in ("accepted", "ready"):
        r = await client.patch(
            f"/api/operator/orders/{order['id']}/status", json={"status": status}, headers=op
        )
        assert r.status_code == 200, r.text
    r = await client.post("/api/operator/issue", json={"code": legacy_code}, headers=op)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "issued"
    # повторно тот же код не принимается
    r = await client.post("/api/operator/issue", json={"code": legacy_code}, headers=op)
    assert r.status_code == 409

    async with SessionLocal() as s:
        assert await s.scalar(select(Order.status).where(Order.id == order["id"])) == "issued"


async def test_legacy_cookie_keeps_session(client):
    token = await login(client, "student@rosbiotech.ru", "student")
    client.cookies.clear()
    client.cookies.set("bioeat_token", token)
    r = await client.get("/api/auth/me")
    assert r.status_code == 200
    # сервер переносит сессию на новую cookie
    assert "rospit_token=" in r.headers.get("set-cookie", "")
    client.cookies.clear()
