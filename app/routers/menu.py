"""Публичное меню и слоты выдачи."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import Category, Dish
from ..reference import ALLERGENS
from ..schemas import AllergenOut, CategoryOut, DishOut, SlotOut
from ..services import popular_dish_ids, slots_payload

router = APIRouter(prefix="/api", tags=["menu"])


@router.get("/categories", response_model=list[CategoryOut])
async def list_categories(session: AsyncSession = Depends(get_session)):
    return (
        await session.scalars(
            select(Category)
            .where(Category.is_active.is_(True))
            .order_by(Category.sort_order, Category.id)
        )
    ).all()


@router.get("/dishes", response_model=list[DishOut])
async def list_dishes(
    category: str | None = Query(default=None, description="slug категории"),
    q: str | None = Query(default=None, description="поиск по названию"),
    tag: str | None = Query(default=None, description="фильтр по диете: pp/veg/no_lactose/..."),
    include_hidden: bool = False,
    session: AsyncSession = Depends(get_session),
):
    stmt = select(Dish).join(Category)
    if not include_hidden:
        stmt = stmt.where(Dish.is_active.is_(True), Category.is_active.is_(True))
    if category:
        stmt = stmt.where(Category.slug == category)
    stmt = stmt.order_by(Category.sort_order, Dish.sort_order, Dish.id)

    dishes = list((await session.scalars(stmt)).all())
    if tag:
        dishes = [d for d in dishes if tag in (d.tags or [])]
    if q:
        # регистронезависимый поиск делаем в Python: LIKE в SQLite не понимает кириллицу
        needle = q.strip().lower()
        dishes = [
            d for d in dishes
            if needle in d.name.lower() or needle in (d.description or "").lower()
        ]
    return dishes


@router.get("/dishes/popular", response_model=list[DishOut])
async def popular_dishes(
    limit: int = Query(default=6, ge=1, le=24),
    days: int = Query(default=7, ge=1, le=90),
    session: AsyncSession = Depends(get_session),
):
    """Хиты по фактическим продажам за последние `days` дней.

    Если продаж ещё нет (свежая база, начало семестра) — откатываемся на тег «hit»,
    а затем просто на первые позиции меню, чтобы блок на главной никогда не пустовал.
    """
    ranked_ids = await popular_dish_ids(session, days=days, limit=limit)

    stmt = select(Dish).join(Category).where(
        Dish.is_active.is_(True), Category.is_active.is_(True)
    )
    available = list((await session.scalars(stmt)).all())
    by_id = {d.id: d for d in available}

    result = [by_id[i] for i in ranked_ids if i in by_id]
    chosen = {d.id for d in result}
    for pool in (
        [d for d in available if "hit" in (d.tags or [])],
        available,
    ):
        for dish in pool:
            if len(result) >= limit:
                break
            if dish.id not in chosen:
                result.append(dish)
                chosen.add(dish.id)
    return result[:limit]


@router.get("/dishes/{dish_id}", response_model=DishOut)
async def get_dish(dish_id: int, session: AsyncSession = Depends(get_session)):
    dish = await session.get(Dish, dish_id)
    if dish is None:
        raise HTTPException(status_code=404, detail="Блюдо не найдено")
    return dish


@router.get("/slots", response_model=list[SlotOut])
async def list_slots(
    on_date: date | None = Query(default=None, alias="date"),
    session: AsyncSession = Depends(get_session),
):
    slots = await slots_payload(session, on_date)
    return [s for s in slots if s["is_active"]]


@router.get("/reference/allergens", response_model=list[AllergenOut])
async def list_allergens():
    """Справочник аллергенов по ТР ТС 022/2011 — 14 групп.

    Отдаём с сервера, чтобы названия и цвета не дублировались на клиенте.
    """
    return [{"code": code, **data} for code, data in ALLERGENS.items()]
