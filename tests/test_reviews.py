"""Отзывы: права, правка 24 часа, частота общих отзывов, сводка и модерация."""
from __future__ import annotations

from datetime import timedelta

import pytest_asyncio
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from app.db import SessionLocal
from app.main import app
from app.models import Review
from tests.helpers import auth, login, place_order


@pytest_asyncio.fixture(scope="module")
async def client():
    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c


@pytest_asyncio.fixture(scope="module")
async def people(client):
    r = await client.post(
        "/api/auth/register",
        json={"email": "critic@rosbiotech.ru", "password": "secret", "full_name": "Критик Отзывов", "group_name": "24о-1"},
    )
    return {
        "student": auth(r.json()["token"]),
        "other": auth(await login(client, "student@rosbiotech.ru", "student")),
        "op": auth(await login(client, "operator@rosbiotech.ru", "operator")),
        "admin": auth(await login(client, "admin@rosbiotech.ru", "admin")),
    }


async def issued_order(client, people, index=0):
    order = await place_order(client, people["student"], pay=True, dish_index=index)
    for status in ("ready", "issued"):
        r = await client.patch(
            f"/api/operator/orders/{order['id']}/status", json={"status": status}, headers=people["op"]
        )
        assert r.status_code == 200, r.text
    return order


async def test_tags_are_listed(client):
    tags = (await client.get("/api/reviews/tags")).json()
    labels = {t["label"] for t in tags}
    assert {"вкусно", "горячее", "быстро", "порция маленькая", "долго ждал", "перепутали заказ"} <= labels


async def test_review_only_after_issue_and_only_by_owner(client, people):
    pending = await place_order(client, people["student"], pay=True, dish_index=1)
    r = await client.post("/api/reviews", json={"order_id": pending["id"], "rating": 5}, headers=people["student"])
    assert r.status_code == 409

    order = await issued_order(client, people, index=2)
    r = await client.post("/api/reviews", json={"order_id": order["id"], "rating": 5}, headers=people["other"])
    assert r.status_code == 403

    r = await client.post(
        "/api/reviews",
        json={"order_id": order["id"], "rating": 4, "tags": ["tasty", "hot"], "text": "Борщ огонь"},
        headers=people["student"],
    )
    assert r.status_code == 201, r.text
    review = r.json()
    assert review["tag_labels"] == ["вкусно", "горячее"]
    assert review["can_edit"] is True
    assert review["order_number"] == order["number"]

    # один отзыв на заказ
    r = await client.post("/api/reviews", json={"order_id": order["id"], "rating": 1}, headers=people["student"])
    assert r.status_code == 409
    # заказ знает о своём отзыве — клиент не предлагает оценить ещё раз
    fresh = (await client.get(f"/api/orders/{order['id']}", headers=people["student"])).json()
    assert fresh["review"] == {"id": review["id"], "rating": 4}

    # неизвестный тег и длинный текст отклоняются
    other = await issued_order(client, people, index=3)
    r = await client.post("/api/reviews", json={"order_id": other["id"], "rating": 5, "tags": ["spam"]}, headers=people["student"])
    assert r.status_code == 422
    r = await client.post("/api/reviews", json={"order_id": other["id"], "rating": 5, "text": "x" * 1001}, headers=people["student"])
    assert r.status_code == 422
    r = await client.post("/api/reviews", json={"order_id": other["id"], "rating": 6}, headers=people["student"])
    assert r.status_code == 422


async def test_edit_within_24_hours_only(client, people):
    order = await issued_order(client, people, index=4)
    review = (
        await client.post("/api/reviews", json={"order_id": order["id"], "rating": 2, "tags": ["cold"]}, headers=people["student"])
    ).json()
    r = await client.patch(f"/api/reviews/{review['id']}", json={"rating": 3, "text": "Подогрели"}, headers=people["student"])
    assert r.status_code == 200
    assert r.json()["rating"] == 3 and r.json()["text"] == "Подогрели"

    # чужой отзыв не правится
    r = await client.patch(f"/api/reviews/{review['id']}", json={"rating": 5}, headers=people["other"])
    assert r.status_code == 404

    async with SessionLocal() as s:
        row = await s.get(Review, review["id"])
        row.created_at = row.created_at - timedelta(hours=25)
        await s.commit()
    r = await client.patch(f"/api/reviews/{review['id']}", json={"rating": 5}, headers=people["student"])
    assert r.status_code == 409


async def test_general_review_is_rate_limited(client, people):
    r = await client.post(
        "/api/reviews", json={"rating": 5, "text": "Спасибо столовой!", "is_anonymous": True}, headers=people["student"]
    )
    assert r.status_code == 201
    assert r.json()["order_id"] is None
    r = await client.post("/api/reviews", json={"rating": 4}, headers=people["student"])
    assert r.status_code == 429


async def test_staff_summary_reply_and_hide(client, people):
    feed = (await client.get("/api/staff/reviews?period=week", headers=people["op"])).json()
    week = feed["summary"]["week"]
    assert week["count"] >= 3
    assert sum(week["distribution"].values()) == week["count"]
    assert week["avg"] is not None
    assert any(t["label"] == "вкусно" for t in week["top_tags"])

    # анонимный отзыв анонимен и для столовой
    anon = next(i for i in feed["items"] if i["is_anonymous"])
    assert anon["author"] == "Аноним" and anon["author_group"] is None
    named = next(i for i in feed["items"] if not i["is_anonymous"])
    assert named["author"] == "Критик Отзывов"

    r = await client.post(f"/api/staff/reviews/{named['id']}/reply", json={"text": "Спасибо, передадим повару!"}, headers=people["op"])
    assert r.status_code == 200 and r.json()["staff_reply"].startswith("Спасибо")
    mine = (await client.get("/api/reviews/mine", headers=people["student"])).json()
    assert any(m["staff_reply"] for m in mine)

    r = await client.post(f"/api/staff/reviews/{anon['id']}/visibility?hidden=true", headers=people["op"])
    assert r.json()["status"] == "hidden"
    after = (await client.get("/api/staff/reviews?period=week", headers=people["op"])).json()["summary"]["week"]
    assert after["count"] == week["count"] - 1

    only_four = (await client.get("/api/staff/reviews?period=all&rating=4", headers=people["op"])).json()["items"]
    assert only_four and all(i["rating"] == 4 for i in only_four)
    tagged = (await client.get("/api/staff/reviews?period=all&tag=cold", headers=people["op"])).json()["items"]
    assert tagged and all("cold" in i["tags"] for i in tagged)


async def test_students_cannot_moderate_and_dashboard_has_rating(client, people):
    assert (await client.get("/api/staff/reviews", headers=people["student"])).status_code == 403
    stats = (await client.get("/api/admin/stats", headers=people["admin"])).json()
    assert stats["reviews_count"] >= 1
    assert 1 <= stats["rating_avg"] <= 5
