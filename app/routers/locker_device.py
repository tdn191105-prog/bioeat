"""API для контроллера постамата (ESP32). Без JWT пользователя.

Каждый запрос подписан HMAC-SHA256 общим секретом устройства по строке
«device_id|ts|nonce|payload»; сервер отбрасывает запросы старше 30 секунд
и повтор nonce. Формат и сценарии — в docs/locker_integration.md.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import SessionLocal, get_session
from ..lockers import (
    authenticate_device,
    consume_code,
    handle_event,
    prune_nonces,
    take_commands,
)
from ..models import Locker
from ..schemas import DeviceEventIn, DeviceHeartbeatIn, DeviceScanIn

router = APIRouter(prefix="/api/device/lockers", tags=["locker-device"])

MAX_WAIT_SECONDS = 25


@router.post("/{device_id}/scan")
async def scan(device_id: str, data: DeviceScanIn, session: AsyncSession = Depends(get_session)):
    """Студент поднёс QR или ввёл PIN: открыть ячейку или отказать.

    Подпись — по строке «device_id|ts|nonce|code».
    """
    locker = await authenticate_device(session, device_id, data.ts, data.nonce, data.code, data.sig)
    return await consume_code(session, locker, data.code)


@router.post("/{device_id}/events")
async def events(device_id: str, data: DeviceEventIn, session: AsyncSession = Depends(get_session)):
    """Дверь открыта / закрыта, датчик «ячейка пуста», дверь заклинило.

    Подпись — по строке «device_id|ts|nonce|<type>:<cell>».
    """
    payload = f"{data.type}:{data.cell if data.cell is not None else ''}"
    locker = await authenticate_device(session, device_id, data.ts, data.nonce, payload, data.sig)
    return await handle_event(session, locker, data.type, data.cell, data.empty)


@router.post("/{device_id}/heartbeat")
async def heartbeat(device_id: str, data: DeviceHeartbeatIn, session: AsyncSession = Depends(get_session)):
    """Устройство на связи. Подпись — по строке «device_id|ts|nonce|heartbeat»."""
    locker = await authenticate_device(session, device_id, data.ts, data.nonce, "heartbeat", data.sig)
    if data.firmware:
        locker.firmware = data.firmware
    await prune_nonces(session)
    await session.commit()
    return {"ok": True}


@router.get("/{device_id}/commands")
async def commands(
    device_id: str,
    ts: int,
    nonce: str = Query(min_length=8, max_length=64),
    sig: str = Query(min_length=64, max_length=64),
    wait: int = Query(default=MAX_WAIT_SECONDS, ge=0, le=MAX_WAIT_SECONDS),
    session: AsyncSession = Depends(get_session),
):
    """Long-polling: ждём до `wait` секунд, пока для постамата не появится команда.

    Подпись — по строке «device_id|ts|nonce|commands». Запрос служит и heartbeat.
    """
    locker = await authenticate_device(session, device_id, ts, nonce, "commands", sig)
    found = await take_commands(session, locker)
    await session.commit()
    locker_id = locker.id
    loops = wait * 2
    while not found and loops > 0:
        await asyncio.sleep(0.5)
        loops -= 1
        # своя короткая сессия на каждую проверку — не держим соединение 25 секунд
        async with SessionLocal() as poll:
            fresh = await poll.get(Locker, locker_id)
            found = await take_commands(poll, fresh)
            await poll.commit()
    return {"commands": found}
