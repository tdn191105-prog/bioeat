"""Бизнес-логика: корзина, оформление и оплата заказа."""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .models import (
    ACTIVE_STATUSES,
    Cart,
    CartItem,
    Dish,
    Order,
    OrderItem,
    OrderStatus,
    Payment,
    PaymentMethod,
    PaymentStatus,
    PickupSlot,
    User,
    utcnow,
)
from .security import make_pickup_code

STATUS_LABELS = {
    OrderStatus.created: "Ожидает оплаты",
    OrderStatus.paid: "Оплачен",
    OrderStatus.accepted: "Принят кухней",
    OrderStatus.cooking: "Комплектуется",
    OrderStatus.ready: "Готов к выдаче",
    OrderStatus.issued: "Выдан",
    OrderStatus.cancelled: "Отменён",
}

# Разрешённые переходы статусов — защищают от рассинхрона на экране оператора.
ALLOWED_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.created: {OrderStatus.paid, OrderStatus.cancelled},
    OrderStatus.paid: {OrderStatus.accepted, OrderStatus.cancelled},
    OrderStatus.accepted: {OrderStatus.cooking, OrderStatus.ready, OrderStatus.cancelled},
    OrderStatus.cooking: {OrderStatus.ready, OrderStatus.cancelled},
    OrderStatus.ready: {OrderStatus.issued, OrderStatus.cancelled},
    OrderStatus.issued: set(),
    OrderStatus.cancelled: set(),
}

MAX_BONUS_SHARE = Decimal("0.30")  # бонусами можно закрыть не больше 30% чека


def campus_now() -> datetime:
    """Текущее время кампуса (Москва) без таймзоны."""
    return datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(
        hours=settings.tz_offset_hours
    )


def campus_today() -> date:
    return campus_now().date()


def money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


# --------------------------------------------------------------------------- #
#  Корзина
# --------------------------------------------------------------------------- #
async def get_or_create_cart(session: AsyncSession, user: User) -> Cart:
    cart = await session.scalar(select(Cart).where(Cart.user_id == user.id))
    if cart is None:
        cart = Cart(user_id=user.id)
        session.add(cart)
        await session.commit()
        await session.refresh(cart)
    return cart


async def cart_payload(session: AsyncSession, user: User) -> dict:
    cart = await get_or_create_cart(session, user)
    await session.refresh(cart, ["items"])

    items, subtotal, count = [], Decimal("0.00"), 0
    for item in sorted(cart.items, key=lambda i: i.id):
        dish = item.dish
        if dish is None:
            continue
        price = money(dish.price)
        line = money(price * item.qty)
        subtotal += line
        count += item.qty
        items.append(
            {
                "dish_id": dish.id,
                "name": dish.name,
                "icon": dish.icon,
                "price": price,
                "qty": item.qty,
                "line_total": line,
                "stock_qty": dish.stock_qty,
                "is_active": dish.is_active,
            }
        )

    bonus = money(user.bonus_balance)
    max_bonus = min(bonus, money(subtotal * MAX_BONUS_SHARE))
    return {
        "items": items,
        "count": count,
        "subtotal": money(subtotal),
        "bonus_available": bonus,
        "max_bonus_applicable": max_bonus,
    }


async def set_cart_item(session: AsyncSession, user: User, dish_id: int, qty: int) -> dict:
    dish = await session.get(Dish, dish_id)
    if dish is None or not dish.is_active:
        raise HTTPException(status_code=404, detail="Блюдо недоступно")
    if qty > 0 and qty > dish.stock_qty:
        raise HTTPException(
            status_code=409,
            detail=f"Осталось всего {dish.stock_qty} порц. «{dish.name}»",
        )

    cart = await get_or_create_cart(session, user)
    item = await session.scalar(
        select(CartItem).where(CartItem.cart_id == cart.id, CartItem.dish_id == dish_id)
    )
    if qty <= 0:
        if item:
            await session.delete(item)
    elif item:
        item.qty = qty
    else:
        session.add(CartItem(cart_id=cart.id, dish_id=dish_id, qty=qty))
    cart.updated_at = utcnow()
    await session.commit()
    return await cart_payload(session, user)


async def add_to_cart(session: AsyncSession, user: User, dish_id: int, delta: int) -> dict:
    cart = await get_or_create_cart(session, user)
    item = await session.scalar(
        select(CartItem).where(CartItem.cart_id == cart.id, CartItem.dish_id == dish_id)
    )
    current = item.qty if item else 0
    return await set_cart_item(session, user, dish_id, max(0, current + delta))


async def clear_cart(session: AsyncSession, user: User) -> None:
    cart = await get_or_create_cart(session, user)
    await session.refresh(cart, ["items"])
    for item in list(cart.items):
        await session.delete(item)
    await session.commit()


# --------------------------------------------------------------------------- #
#  Слоты
# --------------------------------------------------------------------------- #
async def slot_load(session: AsyncSession, slot_id: int, on_date: date) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(Order)
            .where(
                Order.slot_id == slot_id,
                Order.pickup_date == on_date,
                Order.status.in_(ACTIVE_STATUSES),
            )
        )
        or 0
    )


async def slots_payload(session: AsyncSession, on_date: date | None = None) -> list[dict]:
    on_date = on_date or campus_today()
    now = campus_now()
    slots = (
        await session.scalars(
            select(PickupSlot).order_by(PickupSlot.sort_order, PickupSlot.starts_at)
        )
    ).all()

    out = []
    for slot in slots:
        taken = await slot_load(session, slot.id, on_date)
        left = max(0, slot.capacity - taken)
        # слот на сегодня закрывается за 10 минут до начала выдачи
        deadline = datetime.combine(on_date, slot.starts_at) - timedelta(minutes=10)
        in_future = now < deadline
        available = slot.is_active and left > 0 and in_future
        out.append(
            {
                "id": slot.id,
                "label": slot.label,
                "time_range": slot.time_range,
                "starts_at": slot.starts_at.strftime("%H:%M"),
                "ends_at": slot.ends_at.strftime("%H:%M"),
                "point": slot.point,
                "capacity": slot.capacity,
                "taken": taken,
                "left": left,
                "is_available": available,
                "is_active": slot.is_active,
            }
        )
    return out


# --------------------------------------------------------------------------- #
#  Заказы
# --------------------------------------------------------------------------- #
async def generate_order_number(session: AsyncSession) -> str:
    for _ in range(20):
        number = f"BE-{random.randint(1000, 9999)}"
        exists = await session.scalar(select(Order.id).where(Order.number == number))
        if not exists:
            return number
    count = await session.scalar(select(func.count()).select_from(Order)) or 0
    return f"BE-{10000 + count}"


def order_payload(order: Order, *, with_customer: bool = False) -> dict:
    data = {
        "id": order.id,
        "number": order.number,
        "status": order.status,
        "status_label": STATUS_LABELS.get(order.status, order.status.value),
        "slot_label": order.slot_label,
        "pickup_point": order.pickup_point,
        "pickup_date": order.pickup_date,
        "subtotal": money(order.subtotal),
        "bonus_used": money(order.bonus_used),
        "total": money(order.total),
        "bonus_earned": money(order.bonus_earned),
        "comment": order.comment,
        "pickup_code": order.pickup_code,
        "created_at": order.created_at,
        "paid_at": order.paid_at,
        "ready_at": order.ready_at,
        "issued_at": order.issued_at,
        "items": sorted(order.items, key=lambda i: i.id),
    }
    if with_customer and order.user is not None:
        data["customer_name"] = order.user.full_name
        data["customer_group"] = order.user.group_name
    return data


async def create_order(
    session: AsyncSession,
    user: User,
    slot_id: int,
    comment: str,
    use_bonus: bool,
    pickup_date: date | None = None,
) -> Order:
    """Оформляет заказ: проверяет слот, резервирует порции, считает сумму."""
    on_date = pickup_date or campus_today()
    if on_date < campus_today():
        raise HTTPException(status_code=400, detail="Нельзя заказать на прошедшую дату")
    if on_date > campus_today() + timedelta(days=7):
        raise HTTPException(status_code=400, detail="Предзаказ доступен максимум на неделю вперёд")

    slot = await session.get(PickupSlot, slot_id)
    if slot is None or not slot.is_active:
        raise HTTPException(status_code=404, detail="Время выдачи недоступно")

    if on_date == campus_today():
        deadline = datetime.combine(on_date, slot.starts_at) - timedelta(minutes=10)
        if campus_now() >= deadline:
            raise HTTPException(
                status_code=409,
                detail=f"Приём заказов на «{slot.label}» уже закрыт. Выберите другое время.",
            )

    taken = await slot_load(session, slot.id, on_date)
    if taken >= slot.capacity:
        raise HTTPException(
            status_code=409, detail=f"На «{slot.label}» закончились места. Выберите другое время."
        )

    cart = await get_or_create_cart(session, user)
    await session.refresh(cart, ["items"])
    if not cart.items:
        raise HTTPException(status_code=400, detail="Корзина пуста")

    # блокируем строки блюд, чтобы два студента не забрали последнюю порцию
    dish_ids = [i.dish_id for i in cart.items]
    stmt = select(Dish).where(Dish.id.in_(dish_ids))
    if not settings.is_sqlite:
        stmt = stmt.with_for_update()
    dishes = {d.id: d for d in (await session.scalars(stmt)).all()}

    subtotal = Decimal("0.00")
    order_items: list[OrderItem] = []
    for item in cart.items:
        dish = dishes.get(item.dish_id)
        if dish is None or not dish.is_active:
            raise HTTPException(
                status_code=409, detail="Часть блюд больше недоступна — обновите корзину"
            )
        if item.qty > dish.stock_qty:
            raise HTTPException(
                status_code=409,
                detail=f"«{dish.name}»: осталось {dish.stock_qty} порц., в корзине {item.qty}",
            )
        dish.stock_qty -= item.qty
        price = money(dish.price)
        subtotal += money(price * item.qty)
        order_items.append(
            OrderItem(dish_id=dish.id, name=dish.name, icon=dish.icon, price=price, qty=item.qty)
        )

    bonus_used = Decimal("0.00")
    if use_bonus:
        bonus_used = min(money(user.bonus_balance), money(subtotal * MAX_BONUS_SHARE))
    total = money(subtotal - bonus_used)
    bonus_earned = money(total * Decimal(settings.loyalty_percent) / Decimal(100))

    number = await generate_order_number(session)
    order = Order(
        number=number,
        user_id=user.id,
        slot_id=slot.id,
        slot_label=f"{slot.label} · {slot.time_range}",
        pickup_point=slot.point,
        pickup_date=on_date,
        status=OrderStatus.created,
        subtotal=money(subtotal),
        bonus_used=bonus_used,
        total=total,
        bonus_earned=bonus_earned,
        comment=comment.strip()[:300],
        pickup_code=make_pickup_code(number),
        items=order_items,
    )
    session.add(order)

    if bonus_used:
        user.bonus_balance = money(money(user.bonus_balance) - bonus_used)

    for item in list(cart.items):
        await session.delete(item)

    await session.commit()
    await session.refresh(order, ["items", "user"])
    return order


async def restore_stock(session: AsyncSession, order: Order) -> None:
    for item in order.items:
        if item.dish_id is None:
            continue
        dish = await session.get(Dish, item.dish_id)
        if dish is not None:
            dish.stock_qty += item.qty


async def cancel_order(session: AsyncSession, order: Order, refund: bool = True) -> Order:
    if order.status in (OrderStatus.issued, OrderStatus.cancelled):
        raise HTTPException(status_code=409, detail="Заказ уже закрыт")

    await restore_stock(session, order)

    if order.bonus_used and refund:
        user = await session.get(User, order.user_id)
        if user:
            user.bonus_balance = money(money(user.bonus_balance) + money(order.bonus_used))

    if order.status != OrderStatus.created and refund:
        for payment in order.payments:
            if payment.status == PaymentStatus.succeeded:
                payment.status = PaymentStatus.refunded

    order.status = OrderStatus.cancelled
    order.cancelled_at = utcnow()
    await session.commit()
    await session.refresh(order, ["items", "payments", "user"])
    return order


# --------------------------------------------------------------------------- #
#  Оплата (демо-режим)
# --------------------------------------------------------------------------- #
async def pay_order(
    session: AsyncSession,
    order: Order,
    method: PaymentMethod,
    simulate_failure: bool = False,
) -> tuple[bool, str, str]:
    """Имитация эквайринга. Реальные системы не подключаются.

    Возвращает (успех, сообщение, номер транзакции).
    """
    if order.status == OrderStatus.cancelled:
        raise HTTPException(status_code=409, detail="Заказ отменён")
    if order.status != OrderStatus.created:
        # идемпотентность: повторный запрос не списывает второй раз
        return True, "Заказ уже оплачен", ""

    provider_ref = f"DEMO-{random.randint(100000, 999999)}"
    payment = Payment(
        order_id=order.id,
        method=method,
        amount=money(order.total),
        status=PaymentStatus.pending,
        provider_ref=provider_ref,
    )
    session.add(payment)

    if simulate_failure:
        payment.status = PaymentStatus.failed
        await session.commit()
        return False, "Банк отклонил операцию. Попробуйте другой способ оплаты.", provider_ref

    payment.status = PaymentStatus.succeeded
    order.status = OrderStatus.paid
    order.paid_at = utcnow()

    user = await session.get(User, order.user_id)
    if user and order.bonus_earned:
        user.bonus_balance = money(money(user.bonus_balance) + money(order.bonus_earned))

    await session.commit()
    await session.refresh(order, ["items", "payments", "user"])
    label = {PaymentMethod.sbp: "СБП", PaymentMethod.card: "картой", PaymentMethod.bonus: "бонусами"}
    amount = money(order.total)
    pretty = f"{amount:.2f}"
    if pretty.endswith(".00"):  # целые суммы показываем без копеек
        pretty = pretty[:-3]
    return True, f"Оплачено {label.get(method, '')} — {pretty} ₽", provider_ref
