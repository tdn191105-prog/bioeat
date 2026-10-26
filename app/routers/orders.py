"""Заказы студента: оформление, оплата, история, QR-код."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import get_session
from ..deps import current_user
from ..lockers import issue_pickup_token, pickup_snapshot
from ..models import ACTIVE_STATUSES, Order, OrderStatus, User, UserRole
from ..qr import qr_svg
from ..schemas import OrderCreateIn, OrderOut, PayIn, PaymentStatusOut, PayOut, PickupTokenOut
from ..services import (
    cancel_order,
    create_order,
    expire_order_if_stale,
    expire_unpaid_orders,
    hhmm,
    is_past_deadline,
    order_deadline,
    order_payload,
    pay_order,
    payment_status_payload,
    repeat_order,
)

router = APIRouter(prefix="/api/orders", tags=["orders"])


async def _load_order(session: AsyncSession, order_id: int, user: User) -> Order:
    order = await session.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Заказ не найден")
    if order.user_id != user.id and user.role == UserRole.student:
        raise HTTPException(status_code=403, detail="Это не ваш заказ")
    return order


@router.post("", response_model=OrderOut, status_code=201)
async def make_order(
    data: OrderCreateIn,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    order = await create_order(
        session, user, data.slot_id, data.comment, data.use_bonus, data.pickup_date
    )
    return order_payload(order)


@router.get("", response_model=list[OrderOut])
async def my_orders(
    active_only: bool = False,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    await expire_unpaid_orders(session)
    stmt = select(Order).where(Order.user_id == user.id)
    if active_only:
        stmt = stmt.where(Order.status.in_((OrderStatus.created, *ACTIVE_STATUSES)))
    stmt = stmt.order_by(desc(Order.created_at)).limit(100)
    orders = (await session.scalars(stmt)).all()
    return [order_payload(o) for o in orders]


@router.get("/{order_id}", response_model=OrderOut)
async def get_order(
    order_id: int,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    order = await _load_order(session, order_id, user)
    await expire_order_if_stale(session, order)
    return order_payload(order, with_customer=user.role != UserRole.student)


def _return_url(request: Request, order_id: int) -> str:
    base = settings.public_base_url.rstrip("/") or str(request.base_url).rstrip("/")
    return f"{base}/#/order/{order_id}?payment=return"


@router.post("/{order_id}/pay", response_model=PayOut)
async def pay(
    order_id: int,
    data: PayIn,
    request: Request,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    order = await _load_order(session, order_id, user)
    result = await pay_order(
        session, order, data.method, data.simulate_failure, return_url=_return_url(request, order.id)
    )
    return {**result, "order": order_payload(order) if result["ok"] else None}


@router.get("/{order_id}/payment-status", response_model=PaymentStatusOut)
async def payment_status(
    order_id: int,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    """Клиент опрашивает после возврата из банка. Статус перезапрашивается у провайдера."""
    order = await _load_order(session, order_id, user)
    return await payment_status_payload(session, order)


@router.post("/{order_id}/cancel", response_model=OrderOut)
async def cancel(
    order_id: int,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    order = await _load_order(session, order_id, user)
    if user.role == UserRole.student and order.status != OrderStatus.created:
        if order.status not in (OrderStatus.paid, OrderStatus.accepted):
            raise HTTPException(
                status_code=409,
                detail="Заказ уже готовится. Отмена возможна только через оператора столовой.",
            )
        if is_past_deadline(order):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Приём заказов на перемену закрылся в {hhmm(order_deadline(order))} — "
                    "кухня уже собирает заказ. Отменить его можно только через оператора столовой."
                ),
            )
    order = await cancel_order(session, order)
    return order_payload(order)


@router.post("/{order_id}/repeat")
async def repeat(
    order_id: int,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    """Повторить заказ: кладёт его состав в корзину.

    Возвращает, что удалось добавить и что пришлось пропустить, — клиент
    показывает это пользователю, чтобы пропажа позиции не осталась незамеченной.
    """
    order = await _load_order(session, order_id, user)
    if order.user_id != user.id:
        raise HTTPException(status_code=403, detail="Это не ваш заказ")
    return await repeat_order(session, user, order)


@router.get("/{order_id}/qr.svg")
async def order_qr(
    order_id: int,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    """QR-код выдачи в окне в виде SVG (подписанный, одноразовый по факту выдачи)."""
    order = await _load_order(session, order_id, user)
    return Response(
        content=qr_svg(order.pickup_code),
        media_type="image/svg+xml",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/{order_id}/pickup-token", response_model=PickupTokenOut)
async def pickup_token(
    order_id: int,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    """Одноразовый QR и PIN для постамата. Каждый новый запрос гасит прежние коды."""
    order = await _load_order(session, order_id, user)
    if order.user_id != user.id:
        raise HTTPException(status_code=403, detail="Код получает только владелец заказа")
    data = await issue_pickup_token(session, order)
    snapshot = pickup_snapshot(order)
    return {
        **data,
        "qr_svg": qr_svg(data["code"]),
        "cell_number": order.cell_number,
        "locker_name": snapshot["locker_name"],
    }
