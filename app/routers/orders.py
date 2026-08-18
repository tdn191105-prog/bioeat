"""Заказы студента: оформление, оплата, история, QR-код."""
from __future__ import annotations

import io

import qrcode
import qrcode.image.svg
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import current_user
from ..models import ACTIVE_STATUSES, Order, OrderStatus, User, UserRole
from ..schemas import OrderCreateIn, OrderOut, PayIn, PayOut
from ..services import cancel_order, create_order, order_payload, pay_order

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
    return order_payload(order, with_customer=user.role != UserRole.student)


@router.post("/{order_id}/pay", response_model=PayOut)
async def pay(
    order_id: int,
    data: PayIn,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    order = await _load_order(session, order_id, user)
    ok, message, ref = await pay_order(session, order, data.method, data.simulate_failure)
    return {
        "ok": ok,
        "message": message,
        "order": order_payload(order) if ok else None,
        "provider_ref": ref,
    }


@router.post("/{order_id}/cancel", response_model=OrderOut)
async def cancel(
    order_id: int,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    order = await _load_order(session, order_id, user)
    if user.role == UserRole.student and order.status in (
        OrderStatus.cooking,
        OrderStatus.ready,
    ):
        raise HTTPException(
            status_code=409,
            detail="Заказ уже готовится. Отмена возможна только через оператора столовой.",
        )
    order = await cancel_order(session, order)
    return order_payload(order)


@router.get("/{order_id}/qr.svg")
async def order_qr(
    order_id: int,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    """QR-код выдачи в виде SVG — масштабируется без потерь на любом экране."""
    order = await _load_order(session, order_id, user)
    factory = qrcode.image.svg.SvgPathImage
    qr = qrcode.QRCode(box_size=10, border=1, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(order.pickup_code)
    qr.make(fit=True)
    img = qr.make_image(image_factory=factory)
    buf = io.BytesIO()
    img.save(buf)
    svg = buf.getvalue().decode("utf-8")
    # белый фон + чёрный код читается сканерами лучше всего
    svg = svg.replace("<svg ", '<svg style="background:#fff" ', 1)
    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={"Cache-Control": "no-store"},
    )
