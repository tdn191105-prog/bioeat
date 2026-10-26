"""Экран оператора столовой: очередь заказов и выдача по QR."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import staff_required
from ..models import ACTIVE_STATUSES, Order, OrderStatus, utcnow
from ..schemas import IssueIn, OrderOut, StatusPatch
from ..security import verify_pickup_code
from ..services import (
    ALLOWED_TRANSITIONS,
    campus_today,
    cancel_order,
    mark_slot_collected,
    order_number_candidates,
    order_payload,
    shift_payload,
)

router = APIRouter(prefix="/api/operator", tags=["operator"], dependencies=[Depends(staff_required)])


async def find_by_number(session: AsyncSession, raw: str) -> Order | None:
    for candidate in order_number_candidates(raw):
        order = await session.scalar(select(Order).where(Order.number == candidate))
        if order is not None:
            return order
    return None


@router.get("/queue", response_model=list[OrderOut])
async def queue(
    on_date: date | None = Query(default=None, alias="date"),
    status: OrderStatus | None = None,
    session: AsyncSession = Depends(get_session),
):
    """Очередь заказов на дату. По умолчанию — активные заказы на сегодня."""
    on_date = on_date or campus_today()
    stmt = select(Order).where(Order.pickup_date == on_date)
    stmt = stmt.where(Order.status == status) if status else stmt.where(
        Order.status.in_(ACTIVE_STATUSES)
    )
    stmt = stmt.order_by(Order.created_at)
    orders = (await session.scalars(stmt)).all()
    return [order_payload(o, with_customer=True) for o in orders]


@router.get("/shift")
async def shift(
    on_date: date | None = Query(default=None, alias="date"),
    session: AsyncSession = Depends(get_session),
):
    """Экран кухни: перемены дня со сводкой «что собрать» и заказами."""
    return await shift_payload(session, on_date or campus_today())


@router.post("/shift/{slot_id}/collected")
async def shift_collected(
    slot_id: int,
    on_date: date | None = Query(default=None, alias="date"),
    session: AsyncSession = Depends(get_session),
):
    """«Отметить всё как собранное» по перемене — одним действием."""
    count = await mark_slot_collected(session, slot_id, on_date or campus_today())
    return {"ok": True, "updated": count}


@router.get("/board")
async def board(
    on_date: date | None = Query(default=None, alias="date"),
    session: AsyncSession = Depends(get_session),
):
    """Сводка по колонкам канбана для экрана кухни."""
    on_date = on_date or campus_today()
    orders = (
        await session.scalars(
            select(Order)
            .where(Order.pickup_date == on_date, Order.status.in_(ACTIVE_STATUSES))
            .order_by(Order.created_at)
        )
    ).all()

    columns = {s.value: [] for s in ACTIVE_STATUSES}
    for order in orders:
        columns[order.status.value].append(order_payload(order, with_customer=True))

    issued_today = await session.scalars(
        select(Order).where(Order.pickup_date == on_date, Order.status == OrderStatus.issued)
    )
    return {
        "date": on_date,
        "columns": columns,
        "counts": {k: len(v) for k, v in columns.items()},
        "issued_count": len(list(issued_today)),
    }


@router.patch("/orders/{order_id}/status", response_model=OrderOut)
async def change_status(
    order_id: int,
    data: StatusPatch,
    session: AsyncSession = Depends(get_session),
):
    order = await session.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Заказ не найден")

    if data.status == OrderStatus.cancelled:
        order = await cancel_order(session, order)
        return order_payload(order, with_customer=True)

    if data.status == OrderStatus.in_locker:
        raise HTTPException(
            status_code=409,
            detail="В ячейку заказ кладётся через «Положен в ячейку» — там назначается номер ячейки",
        )
    if data.status not in ALLOWED_TRANSITIONS.get(order.status, set()):
        raise HTTPException(
            status_code=409,
            detail=f"Нельзя перевести заказ из «{order.status.value}» в «{data.status.value}»",
        )

    order.status = data.status
    if data.status == OrderStatus.ready:
        order.ready_at = utcnow()
    elif data.status == OrderStatus.issued:
        order.issued_at = utcnow()
    await session.commit()
    await session.refresh(order, ["items", "user"])
    return order_payload(order, with_customer=True)


@router.post("/issue", response_model=OrderOut)
async def issue_by_code(data: IssueIn, session: AsyncSession = Depends(get_session)):
    """Выдача по QR-коду или по номеру заказа (если камера недоступна)."""
    raw = (data.code or "").strip()
    number = verify_pickup_code(raw)

    if number is None:
        # ручной ввод номера: RP-1234, старый BE-1234 или просто 1234
        order = await find_by_number(session, raw)
        if order is None:
            raise HTTPException(status_code=404, detail="Код не распознан")
    else:
        order = await session.scalar(select(Order).where(Order.number == number))
        if order is None:
            raise HTTPException(status_code=404, detail="Заказ не найден")
        if order.pickup_code != raw:
            raise HTTPException(status_code=409, detail="Код устарел — попросите обновить экран")

    if order.status == OrderStatus.issued:
        raise HTTPException(status_code=409, detail=f"Заказ {order.number} уже выдан")
    if order.status == OrderStatus.cancelled:
        raise HTTPException(status_code=409, detail=f"Заказ {order.number} отменён")
    if order.status == OrderStatus.created:
        raise HTTPException(status_code=409, detail=f"Заказ {order.number} не оплачен")
    if order.status != OrderStatus.ready:
        raise HTTPException(
            status_code=409, detail=f"Заказ {order.number} ещё не готов к выдаче"
        )

    order.status = OrderStatus.issued
    order.issued_at = utcnow()
    await session.commit()
    await session.refresh(order, ["items", "user"])
    return order_payload(order, with_customer=True)


@router.get("/lookup/{number}", response_model=OrderOut)
async def lookup(number: str, session: AsyncSession = Depends(get_session)):
    signed = verify_pickup_code(number)
    order = await find_by_number(session, signed or number)
    if order is None:
        raise HTTPException(status_code=404, detail="Заказ не найден")
    return order_payload(order, with_customer=True)
