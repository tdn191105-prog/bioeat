"""Публичное меню и слоты выдачи."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import Category, Dish
from ..schemas import CategoryOut, DishOut, SlotOut
from ..services import slots_payload

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
