"""Постамат: ячейки, одноразовые коды выдачи, подпись запросов устройства.

Схема обмена с ESP32 и решения по безопасности описаны в docs/locker_integration.md.
Модуль не импортирует services.py — наоборот, services вызывает отсюда
освобождение ячейки при выдаче и отмене.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .models import (
    CellSize,
    CellState,
    DeviceNonce,
    Locker,
    LockerCell,
    LockerCommand,
    LockerEvent,
    Order,
    OrderStatus,
    PickupToken,
    utcnow,
)

QR_PREFIX = "ROSPIT:L:"
PIN_LENGTH = 6

# точки выдачи, обслуживаемые постаматом; обновляется при старте и на экране кухни
LOCKER_POINTS: dict[str, str] = {}   # point → название постамата


# --------------------------------------------------------------------------- #
#  Секрет устройства и подпись запросов
# --------------------------------------------------------------------------- #
def device_secret(device_id: str, key_version: int = 1) -> str:
    """Общий секрет постамата для HMAC.

    Выводится из SECRET_KEY, поэтому его не нужно хранить в базе открытым текстом:
    HMAC проверяется только знающим секрет, а хэш для этого не годится.
    Смена ключа — увеличить Locker.key_version и прошить новый секрет.
    """
    raw = f"locker-device:{device_id}:{key_version}"
    return hmac.new(settings.secret_key.encode(), raw.encode(), hashlib.sha256).hexdigest()


def secret_hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def sign(secret: str, device_id: str, ts: int, nonce: str, payload: str) -> str:
    """HMAC-SHA256 строки «device_id|ts|nonce|payload» — так же считает прошивка."""
    message = f"{device_id}|{ts}|{nonce}|{payload}"
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


async def authenticate_device(
    session: AsyncSession, device_id: str, ts: int, nonce: str, payload: str, signature: str
) -> Locker:
    """Проверяет подпись, свежесть и уникальность запроса постамата.

    Отбрасывает запросы старше DEVICE_CLOCK_SKEW_SECONDS и повтор nonce —
    перехваченный запрос нельзя «проиграть» второй раз.
    """
    locker = await session.scalar(select(Locker).where(Locker.device_id == device_id))
    if locker is None or not locker.is_active:
        raise HTTPException(status_code=404, detail="unknown_device")

    secret = device_secret(locker.device_id, locker.key_version)
    if locker.device_secret_hash and locker.device_secret_hash != secret_hash(secret):
        raise HTTPException(status_code=401, detail="key_mismatch")
    expected = sign(secret, device_id, ts, nonce, payload)
    if not hmac.compare_digest(expected, (signature or "").lower()):
        raise HTTPException(status_code=401, detail="bad_signature")

    if abs(time.time() - ts) > settings.device_clock_skew_seconds:
        raise HTTPException(status_code=401, detail="stale_request")
    if not nonce or len(nonce) > 64:
        raise HTTPException(status_code=400, detail="bad_nonce")

    session.add(DeviceNonce(locker_id=locker.id, nonce=nonce))
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="replayed_nonce") from None

    # любой подписанный запрос — это и heartbeat
    locker.last_seen_at = utcnow()
    locker.is_online = True
    return locker


async def prune_nonces(session: AsyncSession) -> None:
    """Старые nonce больше не нужны: запросы старше окна и так отбрасываются."""
    border = utcnow() - timedelta(minutes=10)
    await session.execute(delete(DeviceNonce).where(DeviceNonce.created_at < border))


# --------------------------------------------------------------------------- #
#  Постаматы и точки выдачи
# --------------------------------------------------------------------------- #
def locker_online(locker: Locker) -> bool:
    if not locker.last_seen_at:
        return False
    return utcnow() - locker.last_seen_at <= timedelta(seconds=settings.locker_online_seconds)


async def refresh_locker_points(session: AsyncSession) -> dict[str, str]:
    rows = (await session.execute(select(Locker.point, Locker.name).where(Locker.is_active.is_(True)))).all()
    LOCKER_POINTS.clear()
    LOCKER_POINTS.update({point: name for point, name in rows})
    return LOCKER_POINTS


def is_locker_point(point: str) -> bool:
    return point in LOCKER_POINTS


async def locker_for_point(session: AsyncSession, point: str) -> Locker | None:
    return await session.scalar(
        select(Locker).where(Locker.point == point, Locker.is_active.is_(True))
    )


async def lockers_status(session: AsyncSession) -> list[dict]:
    lockers = (await session.scalars(select(Locker).where(Locker.is_active.is_(True)))).all()
    out = []
    for locker in lockers:
        free = sum(1 for c in locker.cells if c.state == CellState.free)
        out.append(
            {
                "id": locker.id,
                "name": locker.name,
                "point": locker.point,
                "device_id": locker.device_id,
                "is_online": locker_online(locker),
                "last_seen_at": locker.last_seen_at,
                "cells_total": len(locker.cells),
                "cells_free": free,
                "cells": [
                    {"number": c.number, "size": c.size.value, "state": c.state.value, "order_id": c.order_id}
                    for c in locker.cells
                ],
            }
        )
    return out


async def seed_lockers(session: AsyncSession) -> int:
    """Один постамат «Корпус Б, 1 этаж» на 24 ячейки: 8 S, 10 M, 6 L."""
    exists = await session.scalar(select(func.count()).select_from(Locker))
    if exists:
        return 0
    device_id = "locker-b1"
    locker = Locker(
        name="Корпус Б, 1 этаж",
        point="Постамат, 1 этаж корпуса Б",
        device_id=device_id,
        device_secret_hash=secret_hash(device_secret(device_id, 1)),
    )
    for number in range(1, 25):
        size = CellSize.S if number <= 8 else CellSize.M if number <= 18 else CellSize.L
        locker.cells.append(LockerCell(number=number, size=size))
    session.add(locker)
    await session.commit()
    return 1


# --------------------------------------------------------------------------- #
#  Ячейки: положить, освободить, команды
# --------------------------------------------------------------------------- #
async def enqueue_command(
    session: AsyncSession, locker: Locker, cell_number: int, reason: str, order_id: int | None = None
) -> None:
    session.add(
        LockerCommand(locker_id=locker.id, cell_number=cell_number, reason=reason, order_id=order_id)
    )


async def place_in_cell(session: AsyncSession, order: Order, cell_number: int | None = None) -> Order:
    """«Положен в ячейку»: в транзакции занимает свободную ячейку под заказ.

    Ячейка захватывается условным UPDATE … WHERE state='free' — два оператора,
    нажавшие одновременно, не получат одну и ту же ячейку (на PostgreSQL строки
    дополнительно блокируются FOR UPDATE).
    """
    if order.status not in (OrderStatus.ready, OrderStatus.paid, OrderStatus.accepted, OrderStatus.cooking):
        raise HTTPException(status_code=409, detail=f"Заказ {order.number} нельзя положить в ячейку")
    locker = await locker_for_point(session, order.pickup_point)
    if locker is None:
        raise HTTPException(status_code=409, detail="У этой точки выдачи нет постамата")

    stmt = select(LockerCell).where(LockerCell.locker_id == locker.id, LockerCell.state == CellState.free)
    if cell_number is not None:
        stmt = stmt.where(LockerCell.number == cell_number)
    stmt = stmt.order_by(LockerCell.number)
    if not settings.is_sqlite:
        if cell_number is None:
            # блокируем ровно одну свободную ячейку и пропускаем занятые другими —
            # без LIMIT первый оператор заблокировал бы все, второй не нашёл бы ни одной
            stmt = stmt.limit(1).with_for_update(skip_locked=True)
        else:
            stmt = stmt.with_for_update()
    candidates = (await session.scalars(stmt)).all()
    if not candidates:
        detail = (
            f"Ячейка №{cell_number} занята или неисправна"
            if cell_number is not None
            else "В постамате нет свободных ячеек — выдайте заказ в окне"
        )
        raise HTTPException(status_code=409, detail=detail)

    taken = None
    for cell in candidates:
        result = await session.execute(
            update(LockerCell)
            .where(LockerCell.id == cell.id, LockerCell.state == CellState.free)
            .values(state=CellState.occupied, order_id=order.id, updated_at=utcnow())
            .execution_options(synchronize_session=False)
        )
        if result.rowcount == 1:
            taken = cell
            break
    if taken is None:
        raise HTTPException(status_code=409, detail="Ячейку только что заняли — попробуйте ещё раз")

    now = utcnow()
    order.status = OrderStatus.in_locker
    order.locker_id = locker.id
    order.cell_number = taken.number
    order.placed_at = now
    order.ready_at = order.ready_at or now
    # дверца открывается, чтобы повар положил заказ
    await enqueue_command(session, locker, taken.number, "load", order.id)
    session.add(LockerEvent(locker_id=locker.id, kind="placed", cell_number=taken.number, order_id=order.id))
    await session.commit()
    await session.refresh(order)
    return order


async def release_cell(session: AsyncSession, order: Order, *, open_reason: str = "") -> None:
    """Освобождает ячейку заказа (без commit). open_reason — открыть дверцу, чтобы забрать."""
    if not order.locker_id or not order.cell_number:
        return
    cell = await session.scalar(
        select(LockerCell).where(
            LockerCell.locker_id == order.locker_id, LockerCell.number == order.cell_number
        )
    )
    if cell is not None and cell.order_id == order.id:
        cell.state = CellState.free
        cell.order_id = None
        if open_reason:
            locker = await session.get(Locker, order.locker_id)
            if locker is not None:
                await enqueue_command(session, locker, cell.number, open_reason, order.id)
    # повторная выдача по тем же кодам невозможна
    await session.execute(
        update(PickupToken)
        .where(PickupToken.order_id == order.id, PickupToken.used_at.is_(None))
        .values(expires_at=utcnow())
    )


async def take_commands(session: AsyncSession, locker: Locker) -> list[dict]:
    pending = (
        await session.scalars(
            select(LockerCommand)
            .where(LockerCommand.locker_id == locker.id, LockerCommand.delivered_at.is_(None))
            .order_by(LockerCommand.id)
        )
    ).all()
    now = utcnow()
    for cmd in pending:
        cmd.delivered_at = now
    return [
        {"id": c.id, "action": c.action, "cell": c.cell_number, "reason": c.reason} for c in pending
    ]


# --------------------------------------------------------------------------- #
#  Одноразовые коды выдачи
# --------------------------------------------------------------------------- #
def qr_hash(token: str) -> str:
    return hashlib.sha256(f"qr:{token}".encode()).hexdigest()


def pin_hash(locker_id: int, pin: str) -> str:
    # PIN короткий, поэтому хэш привязан к постамату и SECRET_KEY — перебор по базе бесполезен
    raw = f"pin:{locker_id}:{pin}"
    return hmac.new(settings.secret_key.encode(), raw.encode(), hashlib.sha256).hexdigest()


async def issue_pickup_token(session: AsyncSession, order: Order) -> dict:
    """Новый QR и PIN для заказа в ячейке; прежние гаснут сразу.

    Экран заказа запрашивает новый код каждые ~60 секунд, срок жизни — 120:
    скриншот, пересланный другу, через пару минут не сработает.
    """
    if order.status != OrderStatus.in_locker or not order.locker_id:
        raise HTTPException(status_code=409, detail="Код появится, когда заказ положат в ячейку")

    now = utcnow()
    await session.execute(
        update(PickupToken)
        .where(
            PickupToken.order_id == order.id,
            PickupToken.used_at.is_(None),
            PickupToken.expires_at > now,
        )
        .values(expires_at=now)
    )
    expires = now + timedelta(seconds=settings.pickup_token_ttl_seconds)

    token = secrets.token_urlsafe(16)  # 128 бит случайности
    session.add(PickupToken(order_id=order.id, kind="qr", token_hash=qr_hash(token), expires_at=expires))

    # PIN должен быть уникален среди действующих PIN этого постамата
    for _ in range(20):
        pin = f"{secrets.randbelow(10 ** PIN_LENGTH):0{PIN_LENGTH}d}"
        h = pin_hash(order.locker_id, pin)
        clash = await session.scalar(
            select(PickupToken.id).where(
                PickupToken.token_hash == h, PickupToken.used_at.is_(None), PickupToken.expires_at > now
            )
        )
        if not clash:
            break
    session.add(PickupToken(order_id=order.id, kind="pin", token_hash=h, expires_at=expires))
    await session.commit()
    return {
        "code": f"{QR_PREFIX}{token}",
        "pin": pin,
        "expires_at": expires,
        "ttl_seconds": settings.pickup_token_ttl_seconds,
        "refresh_after_seconds": max(10, settings.pickup_token_ttl_seconds // 2),
    }


async def _recent_pin_failures(session: AsyncSession, locker: Locker) -> int:
    since = utcnow() - timedelta(minutes=5)
    return int(
        await session.scalar(
            select(func.count())
            .select_from(LockerEvent)
            .where(
                LockerEvent.locker_id == locker.id,
                LockerEvent.kind == "pin_fail",
                LockerEvent.created_at >= since,
            )
        )
        or 0
    )


async def consume_code(session: AsyncSession, locker: Locker, code: str) -> dict:
    """Скан у постамата: проверяет и гасит код, возвращает решение для устройства.

    Гашение атомарное — UPDATE … SET used_at WHERE used_at IS NULL AND expires_at > now:
    из двух одновременных сканов одного кода пройдёт ровно один.
    """
    code = (code or "").strip()
    now = utcnow()
    is_pin = code.isdigit() and len(code) == PIN_LENGTH

    if code.startswith(QR_PREFIX):
        h = qr_hash(code[len(QR_PREFIX):])
    elif is_pin:
        if await _recent_pin_failures(session, locker) >= settings.pin_attempts_per_5min:
            session.add(LockerEvent(locker_id=locker.id, kind="pin_blocked", detail="лимит попыток"))
            await session.commit()
            return {"action": "deny", "reason": "too_many_attempts",
                    "message": "Слишком много попыток. Подождите 5 минут или обратитесь в окно выдачи"}
        h = pin_hash(locker.id, code)
    elif code.startswith(("ROSPIT:", "BIOEAT:")):
        return {"action": "deny", "reason": "window_code",
                "message": "Это код для окна выдачи. Откройте заказ в приложении"}
    else:
        return {"action": "deny", "reason": "unknown_code", "message": "Код не распознан"}

    result = await session.execute(
        update(PickupToken)
        .where(
            PickupToken.token_hash == h,
            PickupToken.used_at.is_(None),
            PickupToken.expires_at > now,
        )
        .values(used_at=now)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        known = await session.scalar(
            select(PickupToken).where(PickupToken.token_hash == h).order_by(PickupToken.id.desc()).limit(1)
        )
        if is_pin:
            session.add(LockerEvent(locker_id=locker.id, kind="pin_fail"))
        else:
            session.add(LockerEvent(locker_id=locker.id, kind="scan_deny",
                                    order_id=known.order_id if known else None))
        await session.commit()
        if known is None:
            return {"action": "deny", "reason": "unknown_code", "message": "Код не найден"}
        if known.used_at is not None:
            return {"action": "deny", "reason": "used", "message": "Код уже использован"}
        return {"action": "deny", "reason": "expired",
                "message": "Код устарел — обновите QR в приложении"}

    token = await session.scalar(
        select(PickupToken)
        .where(PickupToken.token_hash == h, PickupToken.used_at.is_not(None))
        .order_by(PickupToken.used_at.desc(), PickupToken.id.desc())
        .limit(1)
    )
    order = await session.get(Order, token.order_id) if token else None
    if order is None or order.status != OrderStatus.in_locker:
        await session.commit()
        return {"action": "deny", "reason": "not_in_locker", "message": "Заказ не лежит в ячейке"}
    if order.locker_id != locker.id:
        await session.commit()
        return {"action": "deny", "reason": "other_locker", "message": "Заказ в другом постамате"}

    # остальные коды заказа гаснут: открыть ячейку можно ровно один раз
    await session.execute(
        update(PickupToken)
        .where(PickupToken.order_id == order.id, PickupToken.used_at.is_(None))
        .values(expires_at=now)
    )
    order.picked_up_at = now
    session.add(LockerEvent(locker_id=locker.id, kind="scan_open", cell_number=order.cell_number,
                            order_id=order.id))
    await session.commit()
    return {"action": "open", "cell": order.cell_number, "order": order.number}


async def handle_event(
    session: AsyncSession, locker: Locker, kind: str, cell_number: int | None, empty: bool | None
) -> dict:
    """События устройства. Дверь закрыли после выдачи или датчик «пусто» → заказ выдан."""
    session.add(LockerEvent(locker_id=locker.id, kind=kind, cell_number=cell_number,
                            detail="" if empty is None else f"empty={empty}"))
    issued = None
    if cell_number is not None and (kind == "cell_empty" or (kind == "door_closed" and empty is not False)):
        cell = await session.scalar(
            select(LockerCell).where(LockerCell.locker_id == locker.id, LockerCell.number == cell_number)
        )
        order = await session.get(Order, cell.order_id) if cell and cell.order_id else None
        # закрытие после загрузки поваром заказ не выдаёт — только после скана студента
        if order is not None and order.status == OrderStatus.in_locker and order.picked_up_at:
            order.status = OrderStatus.issued
            order.issued_at = utcnow()
            cell.state = CellState.free
            cell.order_id = None
            issued = order.number
        elif cell is not None and cell.order_id is None and cell.state == CellState.occupied:
            cell.state = CellState.free
    elif kind == "door_jammed" and cell_number is not None:
        cell = await session.scalar(
            select(LockerCell).where(LockerCell.locker_id == locker.id, LockerCell.number == cell_number)
        )
        if cell is not None and cell.order_id is None:
            cell.state = CellState.out_of_service
    await session.commit()
    return {"ok": True, "issued": issued}


def pickup_snapshot(order: Order) -> dict:
    """Поля постамата для ответа API о заказе."""
    locker = order.__dict__.get("locker")
    return {
        "pickup_kind": "locker" if is_locker_point(order.pickup_point) else "window",
        "locker_id": order.locker_id,
        "locker_name": locker.name if locker is not None else LOCKER_POINTS.get(order.pickup_point, ""),
        "cell_number": order.cell_number,
        "placed_at": order.placed_at,
        "picked_up_at": order.picked_up_at,
    }


def utc_iso(moment: datetime | None) -> str | None:
    return moment.isoformat() if moment else None
