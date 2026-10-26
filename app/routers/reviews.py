"""Отзывы: студент оценивает заказ или столовую, столовая отвечает и модерирует."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import current_user, staff_required
from ..models import Order, OrderStatus, Review, ReviewStatus, User, utcnow
from ..schemas import ReviewIn, ReviewOut, ReviewPatch, ReviewReplyIn

router = APIRouter(prefix="/api/reviews", tags=["reviews"])
staff_router = APIRouter(
    prefix="/api/staff/reviews", tags=["reviews"], dependencies=[Depends(staff_required)]
)

# Теги — фиксированный список в коде: по ним столовая видит, что именно хвалят и ругают
REVIEW_TAGS: dict[str, dict] = {
    "tasty": {"label": "вкусно", "positive": True},
    "hot": {"label": "горячее", "positive": True},
    "fast": {"label": "быстро", "positive": True},
    "big_portion": {"label": "сытно", "positive": True},
    "polite": {"label": "вежливо", "positive": True},
    "small_portion": {"label": "порция маленькая", "positive": False},
    "cold": {"label": "остыло", "positive": False},
    "long_wait": {"label": "долго ждал", "positive": False},
    "wrong_order": {"label": "перепутали заказ", "positive": False},
    "not_tasty": {"label": "невкусно", "positive": False},
}

EDIT_WINDOW = timedelta(hours=24)
GENERAL_REVIEW_COOLDOWN = timedelta(hours=24)   # один общий отзыв в сутки


def _clean_tags(tags: list[str]) -> list[str]:
    unknown = [t for t in tags if t not in REVIEW_TAGS]
    if unknown:
        raise HTTPException(status_code=422, detail=f"Неизвестный тег: {unknown[0]}")
    return list(dict.fromkeys(tags))   # без повторов, порядок сохраняем


def review_payload(review: Review, viewer: User | None = None) -> dict:
    own = viewer is not None and viewer.id == review.user_id
    editable_until = review.created_at + EDIT_WINDOW
    order = review.__dict__.get("order")
    return {
        "id": review.id,
        "order_id": review.order_id,
        "order_number": order.number if order is not None else None,
        "rating": review.rating,
        "tags": list(review.tags or []),
        "tag_labels": [REVIEW_TAGS[t]["label"] for t in review.tags or [] if t in REVIEW_TAGS],
        "text": review.text or "",
        "is_anonymous": review.is_anonymous,
        # анонимный отзыв анонимен и для столовой; автор известен только системе (лимиты, модерация)
        "author": "Аноним" if review.is_anonymous and not own else (review.user.full_name if review.user else ""),
        "author_group": None if review.is_anonymous and not own else (review.user.group_name if review.user else None),
        "status": review.status.value,
        "staff_reply": review.staff_reply or "",
        "staff_reply_at": review.staff_reply_at,
        "created_at": review.created_at,
        "updated_at": review.updated_at,
        "editable_until": editable_until if own else None,
        "can_edit": own and utcnow() < editable_until,
    }


@router.get("/tags")
async def tags():
    return [{"code": code, **meta} for code, meta in REVIEW_TAGS.items()]


@router.post("", response_model=ReviewOut, status_code=201)
async def create_review(
    data: ReviewIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
):
    tags_ = _clean_tags(data.tags)
    if data.order_id is not None:
        order = await session.get(Order, data.order_id)
        if order is None:
            raise HTTPException(status_code=404, detail="Заказ не найден")
        if order.user_id != user.id:
            raise HTTPException(status_code=403, detail="Оставить отзыв может только тот, кто делал заказ")
        if order.status != OrderStatus.issued:
            raise HTTPException(status_code=409, detail="Отзыв можно оставить после выдачи заказа")
        if await session.scalar(select(Review.id).where(Review.order_id == order.id)):
            raise HTTPException(status_code=409, detail="Отзыв на этот заказ уже есть — его можно отредактировать")
    else:
        since = utcnow() - GENERAL_REVIEW_COOLDOWN
        recent = await session.scalar(
            select(Review.id).where(
                Review.user_id == user.id, Review.order_id.is_(None), Review.created_at >= since
            )
        )
        if recent:
            raise HTTPException(
                status_code=429, detail="Общий отзыв о столовой можно оставлять раз в сутки — отредактируйте прежний"
            )

    review = Review(
        user_id=user.id,
        order_id=data.order_id,
        rating=data.rating,
        tags=tags_,
        text=data.text.strip(),
        is_anonymous=data.is_anonymous,
    )
    session.add(review)
    try:
        await session.commit()
    except IntegrityError:
        # два одновременных запроса на один заказ: уникальный индекс пропустит только один
        await session.rollback()
        raise HTTPException(status_code=409, detail="Отзыв на этот заказ уже есть") from None
    await session.refresh(review, ["user", "order"])
    return review_payload(review, user)


@router.get("/mine", response_model=list[ReviewOut])
async def my_reviews(
    order_id: int | None = None,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(Review).where(Review.user_id == user.id)
    if order_id is not None:
        stmt = stmt.where(Review.order_id == order_id)
    rows = (await session.scalars(stmt.order_by(Review.created_at.desc()).limit(100))).unique().all()
    return [review_payload(r, user) for r in rows]


@router.patch("/{review_id}", response_model=ReviewOut)
async def edit_review(
    review_id: int,
    data: ReviewPatch,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    review = await session.get(Review, review_id)
    if review is None or review.user_id != user.id:
        raise HTTPException(status_code=404, detail="Отзыв не найден")
    if utcnow() >= review.created_at + EDIT_WINDOW:
        raise HTTPException(status_code=409, detail="Отзыв можно редактировать 24 часа после публикации")
    fields = data.model_dump(exclude_unset=True, exclude_none=True)
    if "tags" in fields:
        review.tags = _clean_tags(fields["tags"])
    if "text" in fields:
        review.text = fields["text"].strip()
    for name in ("rating", "is_anonymous"):
        if name in fields:
            setattr(review, name, fields[name])
    review.updated_at = utcnow()
    await session.commit()
    await session.refresh(review, ["user", "order"])
    return review_payload(review, user)


# --------------------------------------------------------------------------- #
#  Столовая: лента, сводка, ответ, модерация
# --------------------------------------------------------------------------- #
async def reviews_summary(session: AsyncSession, days: int | None) -> dict:
    stmt = select(Review).where(Review.status == ReviewStatus.published)
    if days:
        stmt = stmt.where(Review.created_at >= utcnow() - timedelta(days=days))
    rows = (await session.scalars(stmt)).unique().all()
    distribution = {str(n): 0 for n in range(1, 6)}
    tag_counts: dict[str, int] = {}
    for r in rows:
        distribution[str(r.rating)] += 1
        for t in r.tags or []:
            tag_counts[t] = tag_counts.get(t, 0) + 1
    count = len(rows)
    avg = round(sum(r.rating for r in rows) / count, 2) if count else None
    top = sorted(tag_counts.items(), key=lambda kv: -kv[1])[:6]
    return {
        "count": count,
        "avg": avg,
        "distribution": distribution,
        "top_tags": [
            {"code": c, "label": REVIEW_TAGS.get(c, {}).get("label", c),
             "positive": REVIEW_TAGS.get(c, {}).get("positive", True), "count": n}
            for c, n in top
        ],
        "with_text": sum(1 for r in rows if r.text),
        "unanswered": sum(1 for r in rows if not r.staff_reply and r.rating <= 3),
    }


@staff_router.get("")
async def staff_feed(
    period: str = Query(default="month", pattern="^(week|month|all)$"),
    rating: int | None = Query(default=None, ge=1, le=5),
    tag: str | None = None,
    status: str | None = Query(default=None, pattern="^(published|hidden)$"),
    only_unanswered: bool = False,
    session: AsyncSession = Depends(get_session),
):
    days = {"week": 7, "month": 30, "all": None}[period]
    stmt = select(Review)
    if days:
        stmt = stmt.where(Review.created_at >= utcnow() - timedelta(days=days))
    if rating:
        stmt = stmt.where(Review.rating == rating)
    if status:
        stmt = stmt.where(Review.status == ReviewStatus(status))
    if only_unanswered:
        stmt = stmt.where(Review.staff_reply == "")
    rows = (await session.scalars(stmt.order_by(Review.created_at.desc()).limit(300))).unique().all()
    if tag:
        rows = [r for r in rows if tag in (r.tags or [])]
    return {
        "summary": {"week": await reviews_summary(session, 7), "month": await reviews_summary(session, 30)},
        "items": [review_payload(r) for r in rows],
    }


@staff_router.post("/{review_id}/reply", response_model=ReviewOut)
async def reply(review_id: int, data: ReviewReplyIn, session: AsyncSession = Depends(get_session)):
    review = await session.get(Review, review_id)
    if review is None:
        raise HTTPException(status_code=404, detail="Отзыв не найден")
    review.staff_reply = data.text.strip()
    review.staff_reply_at = utcnow()
    await session.commit()
    await session.refresh(review, ["user", "order"])
    return review_payload(review)


@staff_router.post("/{review_id}/visibility", response_model=ReviewOut)
async def visibility(review_id: int, hidden: bool, session: AsyncSession = Depends(get_session)):
    review = await session.get(Review, review_id)
    if review is None:
        raise HTTPException(status_code=404, detail="Отзыв не найден")
    review.status = ReviewStatus.hidden if hidden else ReviewStatus.published
    await session.commit()
    await session.refresh(review, ["user", "order"])
    return review_payload(review)


async def average_rating(session: AsyncSession) -> tuple[float | None, int]:
    """Средняя оценка за 30 дней для дашборда отчётов."""
    since = utcnow() - timedelta(days=30)
    avg, count = (
        await session.execute(
            select(func.avg(Review.rating), func.count(Review.id)).where(
                Review.status == ReviewStatus.published, Review.created_at >= since
            )
        )
    ).one()
    return (round(float(avg), 2) if avg is not None else None), int(count or 0)



