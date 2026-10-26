"""Бизнес-логика: корзина, оформление и оплата заказа."""
from __future__ import annotations

import logging
import random
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .lockers import (
    lockers_status,
    pickup_snapshot,
    refresh_locker_points,
    release_cell,
)
from .models import (
    ACTIVE_STATUSES,
    TO_COLLECT_STATUSES,
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
from .payments import PaymentError, PaymentRequest, PaymentState, build_provider, get_provider
from .payments.receipt import build_receipt
from .security import make_pickup_code

STATUS_LABELS = {
    OrderStatus.created: "Ожидает оплаты",
    OrderStatus.paid: "Оплачен",
    OrderStatus.accepted: "Принят кухней",
    OrderStatus.cooking: "Комплектуется",
    OrderStatus.ready: "Готов к выдаче",
    OrderStatus.in_locker: "В ячейке постамата",
    OrderStatus.issued: "Выдан",
    OrderStatus.cancelled: "Отменён",
}

# Разрешённые переходы статусов — защищают от рассинхрона на экране оператора.
# Шаги accepted / cooking необязательны: после отсечки кухня собирает перемену
# разом и сразу отмечает «Собран» (paid → ready).
ALLOWED_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.created: {OrderStatus.paid, OrderStatus.cancelled},
    OrderStatus.paid: {OrderStatus.accepted, OrderStatus.cooking, OrderStatus.ready, OrderStatus.cancelled},
    OrderStatus.accepted: {OrderStatus.cooking, OrderStatus.ready, OrderStatus.cancelled},
    OrderStatus.cooking: {OrderStatus.ready, OrderStatus.cancelled},
    # в ячейку кладут только через отдельное действие с назначением ячейки
    OrderStatus.ready: {OrderStatus.issued, OrderStatus.in_locker, OrderStatus.cancelled},
    OrderStatus.in_locker: {OrderStatus.issued, OrderStatus.cancelled},
    OrderStatus.issued: set(),
    OrderStatus.cancelled: set(),
}

log = logging.getLogger("rospit")

MAX_BONUS_SHARE = Decimal("0.30")  # бонусами можно закрыть не больше 30% чека


# Остановленные часы кампуса — только для тестов и записи демо-ролика.
_frozen_now: datetime | None = None


def campus_now() -> datetime:
    """Текущее время кампуса (Москва) без таймзоны."""
    if _frozen_now is not None:
        return _frozen_now
    return datetime.now(UTC).replace(tzinfo=None) + timedelta(
        hours=settings.tz_offset_hours
    )


def freeze_campus_now(value: datetime | None) -> None:
    """Подменяет «сейчас» кампуса. None возвращает настоящие часы."""
    global _frozen_now
    _frozen_now = value


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
                "image_thumb_url": dish.image_thumb_url or "",
                "image_placeholder": dish.image_placeholder or "",
                "category_id": dish.category_id,
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
#  Слоты и отсечка приёма заказов
# --------------------------------------------------------------------------- #
def slot_cutoff_minutes(slot: PickupSlot) -> int:
    value = slot.order_cutoff_minutes
    return settings.default_order_cutoff_minutes if value is None else int(value)


def slot_deadline(slot: PickupSlot, on_date: date) -> datetime:
    """Момент (время кампуса), после которого заказ на эту перемену не принимается.

    Единственное место, где считается отсечка: её используют список окон,
    оформление, оплата и проверка отмены. Действует для любой даты —
    заказ на завтрашнюю 9:30 при отсечке 60 минут закрывается завтра в 8:30.
    """
    return datetime.combine(on_date, slot.starts_at) - timedelta(minutes=slot_cutoff_minutes(slot))


def _loaded_slot(order: Order) -> PickupSlot | None:
    """Окно заказа, если оно уже загружено, — без ленивого запроса в async-коде."""
    state = inspect(order)
    if "slot" in state.unloaded:
        return None
    return order.slot


def order_deadline(order: Order) -> datetime | None:
    slot = _loaded_slot(order)
    if slot is None:
        return None
    return slot_deadline(slot, order.pickup_date)


def is_past_deadline(order: Order) -> bool:
    deadline = order_deadline(order)
    return deadline is not None and campus_now() >= deadline


def hhmm(moment: datetime) -> str:
    return moment.strftime("%H:%M")


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
        deadline = slot_deadline(slot, on_date)
        is_open = now < deadline
        available = slot.is_active and left > 0 and is_open
        # округляем вверх: «осталось 1 мин», пока приём ещё идёт
        seconds_left = (deadline - now).total_seconds()
        closes_in = max(0, int(-(-seconds_left // 60))) if is_open else 0
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
                "is_open": is_open,
                "order_cutoff_minutes": slot_cutoff_minutes(slot),
                "order_deadline": deadline,
                "deadline_time": hhmm(deadline),
                "closes_in_minutes": closes_in,
            }
        )
    return out


# --------------------------------------------------------------------------- #
#  Заказы
# --------------------------------------------------------------------------- #
ORDER_PREFIX = "RP"
# заказы, оформленные до переименования, имеют номера BE-xxxx
LEGACY_ORDER_PREFIXES = ("BE",)


async def generate_order_number(session: AsyncSession) -> str:
    for _ in range(20):
        number = f"{ORDER_PREFIX}-{random.randint(1000, 9999)}"
        exists = await session.scalar(select(Order.id).where(Order.number == number))
        if not exists:
            return number
    count = await session.scalar(select(func.count()).select_from(Order)) or 0
    return f"{ORDER_PREFIX}-{10000 + count}"


def order_number_candidates(raw: str) -> list[str]:
    """Варианты номера заказа для ручного ввода на выдаче.

    Принимаем «RP-1234», «rp 1234», старый «BE-1234» и просто «1234»
    (тогда сначала ищем новый номер, потом старый).
    """
    text = (raw or "").upper().replace(" ", "").replace("–", "-")
    for prefix in (ORDER_PREFIX, *LEGACY_ORDER_PREFIXES):
        if text.startswith(f"{prefix}-"):
            return [text]
        if text.startswith(prefix) and text[len(prefix):].isdigit():
            return [f"{prefix}-{text[len(prefix):]}"]
    digits = text.lstrip("-")
    if digits.isdigit():
        return [f"{p}-{digits}" for p in (ORDER_PREFIX, *LEGACY_ORDER_PREFIXES)]
    return [text] if text else []


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
        "cancel_reason": order.cancel_reason or "",
        **pickup_snapshot(order),
    }
    review = None if "review" in inspect(order).unloaded else order.review
    data["review"] = (
        {"id": review.id, "rating": review.rating} if review is not None else None
    )
    deadline = order_deadline(order)
    data["order_deadline"] = deadline
    data["deadline_time"] = hhmm(deadline) if deadline else None
    data["can_cancel"] = student_can_cancel(order)
    if order.status == OrderStatus.created and order.created_at:
        # время UTC, как и created_at: клиент показывает обратный отсчёт оплаты
        data["pay_until"] = order.created_at + timedelta(minutes=settings.unpaid_order_ttl_minutes)
    if with_customer and order.user is not None:
        data["customer_name"] = order.user.full_name
        data["customer_group"] = order.user.group_name
    return data


def student_can_cancel(order: Order) -> bool:
    """Правило отмены самим студентом.

    Неоплаченный заказ можно отменить всегда — денег ещё нет. Оплаченный — только
    до отсечки перемены: после неё кухня собирает заказы, и отмена означает возврат
    денег за уже собранное. Тогда отменяет оператор столовой.
    """
    if order.status == OrderStatus.created:
        return True
    if order.status not in (OrderStatus.paid, OrderStatus.accepted):
        return False
    return not is_past_deadline(order)


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

    deadline = slot_deadline(slot, on_date)
    if campus_now() >= deadline:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Приём заказов на «{slot.label}» закрыт в {hhmm(deadline)}. "
                "Выберите другое время."
            ),
        )

    # брошенные неоплаченные заказы не должны держать порции и места
    await expire_unpaid_orders(session)

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
            OrderItem(
                dish_id=dish.id,
                name=dish.name,
                icon=dish.icon,
                image_thumb_url=dish.image_thumb_url or "",
                image_placeholder=dish.image_placeholder or "",
                category_id=dish.category_id,
                price=price,
                qty=item.qty,
            )
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
    order.slot = slot
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


async def cancel_order(
    session: AsyncSession, order: Order, refund: bool = True, reason: str = ""
) -> Order:
    if order.status in (OrderStatus.issued, OrderStatus.cancelled):
        raise HTTPException(status_code=409, detail="Заказ уже закрыт")

    was_paid = order.status != OrderStatus.created
    # сначала деньги: если провайдер не принял возврат, заказ не отменяем —
    # иначе студент останется и без заказа, и без денег
    if refund:
        for payment in order.payments:
            if payment.status == PaymentStatus.succeeded and payment.refund_status != "succeeded":
                await refund_payment(session, order, payment, reason=reason or "cancelled")
    if order.status == OrderStatus.in_locker:
        # заказ лежит в ячейке: освобождаем её и открываем дверцу, чтобы забрать
        await release_cell(session, order, open_reason="unload")
    await restore_stock(session, order)

    user = await session.get(User, order.user_id)
    if user is not None:
        balance = money(user.bonus_balance)
        if order.bonus_used and refund:
            balance += money(order.bonus_used)
        # кэшбэк начислялся при оплате — забираем его обратно, но не в минус:
        # бонусы могли быть уже потрачены на другой заказ
        if was_paid and order.bonus_earned:
            balance = max(Decimal("0.00"), balance - money(order.bonus_earned))
        user.bonus_balance = money(balance)

    order.status = OrderStatus.cancelled
    order.cancelled_at = utcnow()
    order.cancel_reason = reason
    await session.commit()
    await session.refresh(order, ["items", "payments", "user"])
    return order


def _has_pending_payment(order: Order) -> bool:
    return any(p.status == PaymentStatus.pending and p.provider != "demo" for p in order.payments)


def unpaid_is_stale(order: Order, now_utc: datetime | None = None) -> bool:
    """Неоплаченный заказ просрочен: вышло время на оплату или прошла отсечка."""
    if order.status != OrderStatus.created:
        return False
    now_utc = now_utc or utcnow()
    ttl = timedelta(minutes=settings.unpaid_order_ttl_minutes)
    return (order.created_at and order.created_at + ttl <= now_utc) or is_past_deadline(order)


async def expire_order_if_stale(session: AsyncSession, order: Order) -> bool:
    if not unpaid_is_stale(order):
        return False
    if _has_pending_payment(order):
        # деньги могли уже прийти, а вебхук — задержаться: сначала спросим банк
        await refresh_pending_payments(session, order)
        if order.status != OrderStatus.created:
            return order.status == OrderStatus.cancelled
    reason = "deadline" if is_past_deadline(order) else "expired"
    await cancel_order(session, order, reason=reason)
    return True


async def expire_unpaid_orders(session: AsyncSession) -> int:
    """Отменяет брошенные неоплаченные заказы и возвращает порции и бонусы.

    Вызывается лениво (при оформлении, просмотре заказа, на экране кухни)
    и фоновой задачей из lifespan — без Celery.
    """
    created = (
        await session.scalars(select(Order).where(Order.status == OrderStatus.created))
    ).unique().all()
    expired = 0
    now_utc = utcnow()
    for order in created:
        if unpaid_is_stale(order, now_utc) and await expire_order_if_stale(session, order):
            expired += 1
    return expired


def cancelled_message(order: Order) -> str:
    if order.cancel_reason == "deadline":
        deadline = order_deadline(order)
        when = f" в {hhmm(deadline)}" if deadline else ""
        return (
            f"Приём заказов на эту перемену закрылся{when}. Заказ отменён, "
            "деньги не списаны, порции и бонусы возвращены."
        )
    if order.cancel_reason == "expired":
        return (
            f"Время на оплату вышло ({settings.unpaid_order_ttl_minutes} мин). "
            "Заказ отменён — оформите его заново."
        )
    return "Заказ отменён"


# --------------------------------------------------------------------------- #
#  Оплата (демо-режим)
# --------------------------------------------------------------------------- #
def _pretty_amount(amount: Decimal) -> str:
    pretty = f"{money(amount):.2f}"
    return pretty[:-3] if pretty.endswith(".00") else pretty  # целые суммы без копеек


METHOD_LABELS = {PaymentMethod.sbp: "СБП", PaymentMethod.card: "картой", PaymentMethod.bonus: "бонусами"}


async def pay_order(
    session: AsyncSession,
    order: Order,
    method: PaymentMethod,
    simulate_failure: bool = False,
    return_url: str = "",
) -> dict:
    """Создаёт платёж у провайдера (PAYMENT_PROVIDER).

    Демо-провайдер отвечает сразу. Реальный — возвращает confirmation_url:
    клиент уходит на страницу банка (карта, 3-D Secure) или в банковское
    приложение (СБП), а заказ станет «Оплачен» только по подтверждённому
    статусу — из вебхука или перезапроса статуса у провайдера.
    """
    provider = get_provider()
    if order.status == OrderStatus.cancelled:
        raise HTTPException(status_code=409, detail=cancelled_message(order))
    if order.status != OrderStatus.created:
        # идемпотентность: повторный запрос не списывает второй раз
        return {"ok": True, "status": "succeeded", "message": "Заказ уже оплачен", "provider_ref": ""}
    # отсечку и срок оплаты проверяем до списания: открыл оплату в 10:59,
    # нажал «Оплатить» в 11:02 — деньги не списываются
    if await expire_order_if_stale(session, order):
        raise HTTPException(status_code=409, detail=cancelled_message(order))
    if not provider.configured:
        raise HTTPException(status_code=503, detail="Онлайн-оплата временно недоступна: провайдер не настроен")
    # отказ банка можно смоделировать только в демо-режиме
    simulate_failure = simulate_failure and provider.name == "demo"

    payment = Payment(
        order_id=order.id,
        method=method,
        amount=money(order.total),
        status=PaymentStatus.pending,
        provider=provider.name,
    )
    session.add(payment)
    await session.flush()
    payment.idempotence_key = f"rospit-pay-{payment.id}"

    receipt = None
    if settings.receipt_enabled and provider.name != "demo":
        receipt = build_receipt(order, order.user.email)
    try:
        created = await provider.create_payment(
            PaymentRequest(
                payment_id=payment.id,
                order_id=order.id,
                order_number=order.number,
                amount=money(order.total),
                method=method.value,
                return_url=return_url,
                description=f"Заказ {order.number} в столовой РОСБИОТЕХ",
                receipt=receipt,
                simulate_failure=simulate_failure,
            )
        )
    except PaymentError as exc:
        payment.status = PaymentStatus.failed
        payment.failure_reason = str(exc)[:120]
        await session.commit()
        raise HTTPException(status_code=502, detail="Банк сейчас недоступен. Попробуйте ещё раз через минуту.") from exc

    payment.provider_ref = created.provider_ref
    payment.confirmation_url = created.confirmation_url
    payment.updated_at = utcnow()
    if created.status == "succeeded":
        await apply_payment_state(
            session, payment, PaymentState(created.provider_ref, "succeeded", money(order.total),
                                           metadata={"order_id": str(order.id)})
        )
    elif created.status == "canceled":
        payment.status = PaymentStatus.failed
        payment.failure_reason = created.failure_reason
    await session.commit()
    await session.refresh(order, ["items", "payments", "user"])

    if payment.status == PaymentStatus.succeeded:
        message = f"Оплачено {METHOD_LABELS.get(method, '')} — {_pretty_amount(order.total)} ₽"
        return {"ok": True, "status": "succeeded", "message": message, "provider_ref": payment.provider_ref}
    if payment.status == PaymentStatus.failed:
        return {"ok": False, "status": "failed", "provider_ref": payment.provider_ref,
                "message": "Банк отклонил операцию. Попробуйте другой способ оплаты."}
    return {
        "ok": False,
        "status": "pending",
        "provider_ref": payment.provider_ref,
        "confirmation_url": payment.confirmation_url,
        "message": "Подтвердите оплату в банке",
    }


async def mark_order_paid(session: AsyncSession, order: Order) -> None:
    order.status = OrderStatus.paid
    order.paid_at = utcnow()
    user = await session.get(User, order.user_id)
    if user and order.bonus_earned:
        user.bonus_balance = money(money(user.bonus_balance) + money(order.bonus_earned))


async def refund_payment(session: AsyncSession, order: Order, payment: Payment, reason: str) -> None:
    """Возврат через провайдера. Статус возврата хранится в платеже."""
    if payment.refund_status in ("pending", "succeeded"):
        return
    provider = get_provider() if payment.provider == get_provider().name else build_provider(payment.provider)
    receipt = None
    if settings.receipt_enabled and provider.name != "demo" and order.user is not None:
        receipt = build_receipt(order, order.user.email, total=payment.amount)
    try:
        result = await provider.refund(
            payment.provider_ref, money(payment.amount), receipt, idempotence_key=f"rospit-refund-{payment.id}"
        )
    except PaymentError as exc:
        payment.refund_status = "failed"
        payment.refund_reason = reason[:40]
        await session.commit()
        raise HTTPException(
            status_code=502, detail="Не удалось оформить возврат в банке. Попробуйте позже или обратитесь в столовую."
        ) from exc
    payment.refund_ref = result.refund_ref
    payment.refund_status = "succeeded" if result.status == "succeeded" else "pending"
    payment.refund_reason = reason[:40]
    payment.refunded_at = utcnow()
    payment.status = PaymentStatus.refunded
    payment.updated_at = utcnow()


async def apply_payment_state(session: AsyncSession, payment: Payment, state: PaymentState) -> str:
    """Применяет подтверждённый провайдером статус. Идемпотентно.

    Источник истины — статус, перезапрошенный у провайдера, а не тело вебхука.
    Сумма и заказ сверяются; оплата пришла к отменённому, просроченному или уже
    оплаченному заказу — деньги автоматически возвращаются.
    """
    order = await session.get(Order, payment.order_id)
    if order is None:
        return "no_order"
    payment.updated_at = utcnow()

    if state.status == "succeeded":
        if payment.status in (PaymentStatus.succeeded, PaymentStatus.refunded):
            return "duplicate"
        payment.status = PaymentStatus.succeeded
        meta_order = str(state.metadata.get("order_id", order.id))
        if money(state.amount) != money(payment.amount) or meta_order != str(order.id):
            log.warning("Платёж %s: сумма/заказ не совпали (%s ≠ %s) — возврат",
                        payment.provider_ref, state.amount, payment.amount)
            payment.failure_reason = "amount_mismatch"
            await refund_payment(session, order, payment, reason="amount_mismatch")
            return "mismatch_refunded"
        if order.status == OrderStatus.created and not is_past_deadline(order):
            await mark_order_paid(session, order)
            return "paid"
        if order.status == OrderStatus.created:
            # заплатил после отсечки: заказ отменяется, деньги возвращаются
            await cancel_order(session, order, reason="deadline")
            return "late_refunded"
        reason = "duplicate_payment" if order.status != OrderStatus.cancelled else "order_cancelled"
        await refund_payment(session, order, payment, reason=reason)
        return "refunded"

    if state.status == "canceled" and payment.status == PaymentStatus.pending:
        payment.status = PaymentStatus.failed
        payment.failure_reason = state.failure_reason[:120]
        return "failed"
    return "pending"


async def refresh_pending_payments(session: AsyncSession, order: Order) -> None:
    """Перезапрашивает у провайдера незавершённые платежи заказа.

    Нужен, когда вебхук задерживается (или недоступен на стенде разработчика).
    Это так же безопасно, как вебхук: статус берётся из API провайдера.
    """
    pending = [
        p for p in order.payments
        if p.status == PaymentStatus.pending and p.provider_ref and p.provider != "demo"
    ]
    if not pending:
        return
    provider = get_provider()
    for payment in pending:
        try:
            state = await provider.get_status(payment.provider_ref)
        except PaymentError as exc:
            log.warning("Статус платежа %s не получен: %s", payment.provider_ref, exc)
            continue
        await apply_payment_state(session, payment, state)
    await session.commit()


async def payment_status_payload(session: AsyncSession, order: Order) -> dict:
    await refresh_pending_payments(session, order)
    await session.refresh(order, ["payments"])
    if order.status == OrderStatus.created:
        await expire_order_if_stale(session, order)
    last = max(order.payments, key=lambda p: p.id, default=None)
    if order.status == OrderStatus.cancelled:
        state = "expired" if order.cancel_reason in ("expired", "deadline") else "cancelled"
    elif order.status != OrderStatus.created:
        state = "paid"
    elif last is None:
        state = "not_started"
    elif last.status == PaymentStatus.failed:
        state = "failed"
    else:
        state = "pending"
    return {
        "state": state,
        "order_status": order.status,
        "message": cancelled_message(order) if order.status == OrderStatus.cancelled else "",
        "confirmation_url": last.confirmation_url if last and state == "pending" else "",
        "refund_status": last.refund_status if last else "",
    }


# --------------------------------------------------------------------------- #
#  Популярность и повтор заказа
# --------------------------------------------------------------------------- #
async def popular_dish_ids(session: AsyncSession, days: int = 7, limit: int = 6) -> list[int]:
    """id блюд, отсортированные по проданным порциям за последние `days` дней.

    Считаем только оплаченные и выданные заказы — отменённые и неоплаченные
    в статистику продаж не попадают.
    """
    since = campus_today() - timedelta(days=days)
    counted = (
        OrderStatus.paid,
        OrderStatus.accepted,
        OrderStatus.cooking,
        OrderStatus.ready,
        OrderStatus.in_locker,
        OrderStatus.issued,
    )
    rows = (
        await session.execute(
            select(OrderItem.dish_id, func.sum(OrderItem.qty).label("sold"))
            .join(Order, Order.id == OrderItem.order_id)
            .where(
                OrderItem.dish_id.is_not(None),
                Order.pickup_date >= since,
                Order.status.in_(counted),
            )
            .group_by(OrderItem.dish_id)
            .order_by(func.sum(OrderItem.qty).desc())
            .limit(limit)
        )
    ).all()
    return [int(r[0]) for r in rows if r[0] is not None]


async def repeat_order(session: AsyncSession, user: User, order: Order) -> dict:
    """Кладёт состав прошлого заказа в корзину.

    Недоступные позиции пропускаем, доступные добавляем в том количестве,
    которое реально осталось на кухне, и честно рассказываем, что не поместилось.
    """
    await session.refresh(order, ["items"])

    added: list[str] = []
    skipped: list[dict] = []
    for item in sorted(order.items, key=lambda i: i.id):
        if item.dish_id is None:
            skipped.append({"name": item.name, "reason": "снято с меню"})
            continue
        dish = await session.get(Dish, item.dish_id)
        if dish is None or not dish.is_active:
            skipped.append({"name": item.name, "reason": "снято с меню"})
            continue
        if dish.stock_qty <= 0:
            skipped.append({"name": dish.name, "reason": "сегодня закончилось"})
            continue
        qty = min(item.qty, dish.stock_qty)
        await set_cart_item(session, user, dish.id, qty)
        added.append(dish.name)
        if qty < item.qty:
            skipped.append(
                {"name": dish.name, "reason": f"добавили {qty} из {item.qty} — больше нет"}
            )

    return {
        "added": added,
        "skipped": skipped,
        "cart": await cart_payload(session, user),
    }


# --------------------------------------------------------------------------- #
#  Смена кухни: заказы по переменам
# --------------------------------------------------------------------------- #
def collect_summary(orders: list[Order]) -> list[dict]:
    """«Что собрать»: блюдо → сколько порций на перемену, больше — выше."""
    totals: dict[str, int] = {}
    for order in orders:
        for item in order.items:
            totals[item.name] = totals.get(item.name, 0) + item.qty
    return [
        {"name": name, "qty": qty}
        for name, qty in sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


async def shift_payload(session: AsyncSession, on_date: date) -> dict:
    """Перемены дня: отсечка, счётчики по статусам, сводка сборки и заказы."""
    await expire_unpaid_orders(session)
    await refresh_locker_points(session)
    lockers = await lockers_status(session)
    lockers_by_point = {item["point"]: item for item in lockers}
    now = campus_now()
    slots = (
        await session.scalars(select(PickupSlot).order_by(PickupSlot.sort_order, PickupSlot.starts_at))
    ).all()
    orders = (
        await session.scalars(
            select(Order)
            .where(
                Order.pickup_date == on_date,
                Order.status.in_((*ACTIVE_STATUSES, OrderStatus.issued)),
            )
            .order_by(Order.paid_at, Order.created_at)
        )
    ).unique().all()

    by_slot: dict[int | None, list[Order]] = {}
    for order in orders:
        by_slot.setdefault(order.slot_id, []).append(order)

    def section(slot: PickupSlot | None, items: list[Order]) -> dict:
        counts = {s.value: 0 for s in (*ACTIVE_STATUSES, OrderStatus.issued)}
        for order in items:
            counts[order.status.value] += 1
        to_collect = [o for o in items if o.status in TO_COLLECT_STATUSES]
        active = [o for o in items if o.status in ACTIVE_STATUSES]
        data = {
            "id": slot.id if slot else None,
            "label": slot.label if slot else "Окно удалено",
            "time_range": slot.time_range if slot else "",
            "starts_at": slot.starts_at.strftime("%H:%M") if slot else "",
            "point": slot.point if slot else (items[0].pickup_point if items else ""),
            "is_active": slot.is_active if slot else False,
            "counts": counts,
            "total": len(active),
            "to_collect_count": len(to_collect),
            "to_collect": collect_summary(to_collect),
            "all_items": collect_summary(active),
            "orders": [order_payload(o, with_customer=True) for o in active],
        }
        point = data["point"]
        locker = lockers_by_point.get(point)
        data["is_locker"] = locker is not None
        data["locker"] = (
            {k: locker[k] for k in ("id", "name", "is_online", "cells_free", "cells_total")}
            if locker
            else None
        )
        if slot is not None:
            deadline = slot_deadline(slot, on_date)
            ends = datetime.combine(on_date, slot.ends_at)
            data.update(
                deadline_time=hhmm(deadline),
                intake_closed=now >= deadline,
                is_over=now >= ends,
            )
        else:
            data.update(deadline_time="", intake_closed=True, is_over=False)
        return data

    sections = [
        section(slot, by_slot.get(slot.id, []))
        for slot in slots
        if slot.is_active or by_slot.get(slot.id)
    ]
    if by_slot.get(None):
        sections.append(section(None, by_slot[None]))

    # текущая или ближайшая перемена: первая незакончившаяся, где есть что делать
    current = None
    if on_date == now.date():
        current = next(
            (s["id"] for s in sections if not s["is_over"] and s["total"]),
            next((s["id"] for s in sections if not s["is_over"]), None),
        )
        if current is None:
            # перемены закончились, а невыданные заказы остались — их и показываем
            current = next((s["id"] for s in sections if s["total"]), None)
    else:
        current = next((s["id"] for s in sections if s["total"]), None)

    return {
        "date": on_date,
        "now": now,
        "current_slot_id": current,
        "slots": sections,
        "issued_count": sum(s["counts"]["issued"] for s in sections),
        "lockers": [{k: v for k, v in item.items() if k != "cells"} for item in lockers],
        "active_count": sum(s["total"] for s in sections),
    }


async def mark_slot_collected(session: AsyncSession, slot_id: int, on_date: date) -> int:
    """Массовое «Собран» по перемене: все ещё не собранные заказы → ready."""
    stmt = select(Order).where(
        Order.slot_id == slot_id,
        Order.pickup_date == on_date,
        Order.status.in_(TO_COLLECT_STATUSES),
    )
    if not settings.is_sqlite:
        # OF orders: у заказа жадно подгружаются пользователь и окно через LEFT JOIN,
        # а PostgreSQL не блокирует «nullable»-сторону внешнего соединения
        stmt = stmt.with_for_update(of=Order)
    orders = (await session.scalars(stmt)).unique().all()
    stamp = utcnow()
    for order in orders:
        order.status = OrderStatus.ready
        order.ready_at = stamp
    await session.commit()
    return len(orders)
