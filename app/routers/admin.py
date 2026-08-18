"""Админ-панель: управление меню, слотами, пользователями и отчётами."""
from __future__ import annotations

import re
from datetime import date, time
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import admin_required
from ..models import (
    ACTIVE_STATUSES,
    CartItem,
    Category,
    Dish,
    Order,
    OrderItem,
    OrderStatus,
    PickupSlot,
    User,
    UserRole,
)
from ..schemas import (
    CategoryIn,
    CategoryOut,
    CategoryPatch,
    DishIn,
    DishOut,
    DishPatch,
    SlotIn,
    SlotOut,
    StatsOut,
    UserOut,
)
from ..security import hash_password
from ..services import campus_today, money, slots_payload

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(admin_required)])

TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "c",
    "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
    "я": "ya", " ": "-",
}


def slugify(value: str) -> str:
    text = "".join(TRANSLIT.get(ch, ch) for ch in value.lower())
    text = re.sub(r"[^a-z0-9-]+", "-", text).strip("-")
    return text or "category"


def parse_time(value: str) -> time:
    try:
        hh, mm = value.strip().split(":")[:2]
        return time(int(hh), int(mm))
    except (ValueError, IndexError):
        raise HTTPException(status_code=422, detail=f"Некорректное время: {value}. Формат ЧЧ:ММ")


# --------------------------------------------------------------------------- #
#  Категории
# --------------------------------------------------------------------------- #
@router.get("/categories", response_model=list[CategoryOut])
async def all_categories(session: AsyncSession = Depends(get_session)):
    return (
        await session.scalars(select(Category).order_by(Category.sort_order, Category.id))
    ).all()


@router.post("/categories", response_model=CategoryOut, status_code=201)
async def create_category(data: CategoryIn, session: AsyncSession = Depends(get_session)):
    slug = slugify(data.slug or data.name)
    if await session.scalar(select(Category).where(Category.slug == slug)):
        raise HTTPException(status_code=409, detail="Категория с таким адресом уже есть")
    cat = Category(
        name=data.name.strip(),
        slug=slug,
        icon=data.icon,
        color=data.color,
        sort_order=data.sort_order,
        is_active=data.is_active,
    )
    session.add(cat)
    await session.commit()
    await session.refresh(cat)
    return cat


@router.patch("/categories/{category_id}", response_model=CategoryOut)
async def update_category(
    category_id: int, data: CategoryPatch, session: AsyncSession = Depends(get_session)
):
    cat = await session.get(Category, category_id)
    if cat is None:
        raise HTTPException(status_code=404, detail="Категория не найдена")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(cat, field, value)
    await session.commit()
    await session.refresh(cat)
    return cat


@router.delete("/categories/{category_id}")
async def delete_category(category_id: int, session: AsyncSession = Depends(get_session)):
    cat = await session.get(Category, category_id)
    if cat is None:
        raise HTTPException(status_code=404, detail="Категория не найдена")
    count = await session.scalar(
        select(func.count()).select_from(Dish).where(Dish.category_id == category_id)
    )
    if count:
        raise HTTPException(
            status_code=409,
            detail=f"В категории {count} блюд. Перенесите или удалите их сначала.",
        )
    await session.delete(cat)
    await session.commit()
    return {"ok": True}


# --------------------------------------------------------------------------- #
#  Блюда
# --------------------------------------------------------------------------- #
@router.get("/dishes", response_model=list[DishOut])
async def all_dishes(session: AsyncSession = Depends(get_session)):
    return (
        await session.scalars(
            select(Dish).order_by(Dish.category_id, Dish.sort_order, Dish.id)
        )
    ).all()


@router.post("/dishes", response_model=DishOut, status_code=201)
async def create_dish(data: DishIn, session: AsyncSession = Depends(get_session)):
    if await session.get(Category, data.category_id) is None:
        raise HTTPException(status_code=422, detail="Такой категории нет")
    dish = Dish(**data.model_dump())
    dish.name = dish.name.strip()
    session.add(dish)
    await session.commit()
    await session.refresh(dish)
    return dish


@router.patch("/dishes/{dish_id}", response_model=DishOut)
async def update_dish(dish_id: int, data: DishPatch, session: AsyncSession = Depends(get_session)):
    dish = await session.get(Dish, dish_id)
    if dish is None:
        raise HTTPException(status_code=404, detail="Блюдо не найдено")
    payload = data.model_dump(exclude_unset=True)
    if "category_id" in payload and await session.get(Category, payload["category_id"]) is None:
        raise HTTPException(status_code=422, detail="Такой категории нет")
    for field, value in payload.items():
        setattr(dish, field, value)
    await session.commit()
    await session.refresh(dish)
    return dish


@router.delete("/dishes/{dish_id}")
async def delete_dish(
    dish_id: int,
    hard: bool = Query(default=False, description="удалить из БД, а не скрыть"),
    session: AsyncSession = Depends(get_session),
):
    """По умолчанию блюдо скрывается из меню — история заказов остаётся целой.

    hard=true удаляет запись физически (позиции в прошлых заказах сохранят название и цену).
    """
    dish = await session.get(Dish, dish_id)
    if dish is None:
        raise HTTPException(status_code=404, detail="Блюдо не найдено")

    in_active_orders = await session.scalar(
        select(func.count())
        .select_from(OrderItem)
        .join(Order, Order.id == OrderItem.order_id)
        .where(OrderItem.dish_id == dish_id, Order.status.in_(ACTIVE_STATUSES))
    )
    if in_active_orders:
        raise HTTPException(
            status_code=409,
            detail=f"Блюдо есть в {in_active_orders} активных заказах — сначала выдайте их.",
        )

    await session.execute(delete(CartItem).where(CartItem.dish_id == dish_id))
    if hard:
        await session.delete(dish)
        await session.commit()
        return {"ok": True, "mode": "deleted"}

    dish.is_active = False
    await session.commit()
    return {"ok": True, "mode": "hidden"}


@router.post("/dishes/{dish_id}/stock", response_model=DishOut)
async def set_stock(
    dish_id: int,
    qty: int = Query(ge=0, le=100000),
    session: AsyncSession = Depends(get_session),
):
    """Быстрое обновление остатка порций на день (стоп-лист = 0)."""
    dish = await session.get(Dish, dish_id)
    if dish is None:
        raise HTTPException(status_code=404, detail="Блюдо не найдено")
    dish.stock_qty = qty
    await session.commit()
    await session.refresh(dish)
    return dish


# --------------------------------------------------------------------------- #
#  Слоты выдачи
# --------------------------------------------------------------------------- #
@router.get("/slots", response_model=list[SlotOut])
async def all_slots(session: AsyncSession = Depends(get_session)):
    return await slots_payload(session)


@router.post("/slots", response_model=SlotOut, status_code=201)
async def create_slot(data: SlotIn, session: AsyncSession = Depends(get_session)):
    starts, ends = parse_time(data.starts_at), parse_time(data.ends_at)
    if ends <= starts:
        raise HTTPException(status_code=422, detail="Окончание должно быть позже начала")
    slot = PickupSlot(
        label=data.label.strip(),
        starts_at=starts,
        ends_at=ends,
        capacity=data.capacity,
        point=data.point,
        is_active=data.is_active,
        sort_order=data.sort_order,
    )
    session.add(slot)
    await session.commit()
    await session.refresh(slot)
    result = [s for s in await slots_payload(session) if s["id"] == slot.id]
    return result[0]


@router.patch("/slots/{slot_id}", response_model=SlotOut)
async def update_slot(slot_id: int, data: dict, session: AsyncSession = Depends(get_session)):
    slot = await session.get(PickupSlot, slot_id)
    if slot is None:
        raise HTTPException(status_code=404, detail="Слот не найден")
    for field in ("label", "point", "capacity", "is_active", "sort_order"):
        if field in data and data[field] is not None:
            setattr(slot, field, data[field])
    if data.get("starts_at"):
        slot.starts_at = parse_time(data["starts_at"])
    if data.get("ends_at"):
        slot.ends_at = parse_time(data["ends_at"])
    if slot.ends_at <= slot.starts_at:
        raise HTTPException(status_code=422, detail="Окончание должно быть позже начала")
    await session.commit()
    result = [s for s in await slots_payload(session) if s["id"] == slot.id]
    return result[0]


@router.delete("/slots/{slot_id}")
async def delete_slot(slot_id: int, session: AsyncSession = Depends(get_session)):
    slot = await session.get(PickupSlot, slot_id)
    if slot is None:
        raise HTTPException(status_code=404, detail="Слот не найден")
    active = await session.scalar(
        select(func.count())
        .select_from(Order)
        .where(Order.slot_id == slot_id, Order.status.in_(ACTIVE_STATUSES))
    )
    if active:
        raise HTTPException(
            status_code=409, detail=f"На слот оформлено {active} активных заказов"
        )
    slot.is_active = False
    await session.commit()
    return {"ok": True, "mode": "hidden"}


# --------------------------------------------------------------------------- #
#  Пользователи
# --------------------------------------------------------------------------- #
@router.get("/users", response_model=list[UserOut])
async def all_users(session: AsyncSession = Depends(get_session)):
    return (await session.scalars(select(User).order_by(User.id))).all()


@router.patch("/users/{user_id}/role", response_model=UserOut)
async def set_role(user_id: int, role: UserRole, session: AsyncSession = Depends(get_session)):
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    user.role = role
    await session.commit()
    await session.refresh(user)
    return user


@router.post("/users", response_model=UserOut, status_code=201)
async def create_staff(
    email: str,
    password: str,
    full_name: str,
    role: UserRole = UserRole.operator,
    session: AsyncSession = Depends(get_session),
):
    """Создание операторской или административной учётной записи."""
    email = email.lower().strip()
    if await session.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="Такая почта уже занята")
    if len(password) < 4:
        raise HTTPException(status_code=422, detail="Пароль слишком короткий")
    user = User(
        email=email,
        password_hash=hash_password(password),
        full_name=full_name.strip(),
        role=role,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


# --------------------------------------------------------------------------- #
#  Отчёты
# --------------------------------------------------------------------------- #
@router.get("/stats", response_model=StatsOut)
async def stats(
    on_date: date | None = Query(default=None, alias="date"),
    session: AsyncSession = Depends(get_session),
):
    on_date = on_date or campus_today()

    paid_statuses = [
        OrderStatus.paid,
        OrderStatus.accepted,
        OrderStatus.cooking,
        OrderStatus.ready,
        OrderStatus.issued,
    ]

    orders_today = int(
        await session.scalar(
            select(func.count()).select_from(Order).where(Order.pickup_date == on_date)
        ) or 0
    )
    revenue_today = money(
        await session.scalar(
            select(func.coalesce(func.sum(Order.total), 0)).where(
                Order.pickup_date == on_date, Order.status.in_(paid_statuses)
            )
        ) or 0
    )
    active_orders = int(
        await session.scalar(
            select(func.count())
            .select_from(Order)
            .where(Order.pickup_date == on_date, Order.status.in_(ACTIVE_STATUSES))
        ) or 0
    )
    issued_today = int(
        await session.scalar(
            select(func.count())
            .select_from(Order)
            .where(Order.pickup_date == on_date, Order.status == OrderStatus.issued)
        ) or 0
    )
    paid_count = int(
        await session.scalar(
            select(func.count())
            .select_from(Order)
            .where(Order.pickup_date == on_date, Order.status.in_(paid_statuses))
        ) or 0
    )
    avg_check = money(revenue_today / paid_count) if paid_count else Decimal("0.00")

    top_rows = (
        await session.execute(
            select(
                OrderItem.name,
                OrderItem.icon,
                func.sum(OrderItem.qty).label("qty"),
                func.sum(OrderItem.qty * OrderItem.price).label("sum"),
            )
            .join(Order, Order.id == OrderItem.order_id)
            .where(Order.pickup_date == on_date, Order.status.in_(paid_statuses))
            .group_by(OrderItem.name, OrderItem.icon)
            .order_by(func.sum(OrderItem.qty).desc())
            .limit(8)
        )
    ).all()

    slot_rows = (
        await session.execute(
            select(Order.slot_label, func.count(Order.id), func.coalesce(func.sum(Order.total), 0))
            .where(Order.pickup_date == on_date, Order.status.in_(paid_statuses))
            .group_by(Order.slot_label)
            .order_by(Order.slot_label)
        )
    ).all()

    return {
        "orders_today": orders_today,
        "revenue_today": revenue_today,
        "active_orders": active_orders,
        "issued_today": issued_today,
        "avg_check": avg_check,
        "top_dishes": [
            {"name": r[0], "icon": r[1], "qty": int(r[2] or 0), "sum": float(r[3] or 0)}
            for r in top_rows
        ],
        "by_slot": [
            {"slot": r[0], "orders": int(r[1] or 0), "sum": float(r[2] or 0)} for r in slot_rows
        ],
        "users_total": int(await session.scalar(select(func.count()).select_from(User)) or 0),
        "dishes_active": int(
            await session.scalar(
                select(func.count()).select_from(Dish).where(Dish.is_active.is_(True))
            ) or 0
        ),
    }
