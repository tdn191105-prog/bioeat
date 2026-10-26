"""Платежи: настройки для экрана оплаты и вебхуки провайдеров."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import Payment
from ..payments import PaymentError, get_provider
from ..payments.yookassa import YooKassaProvider
from ..services import apply_payment_state

log = logging.getLogger("rospit")

router = APIRouter(prefix="/api/payments", tags=["payments"])


@router.get("/config")
async def config():
    provider = get_provider()
    return {
        "provider": provider.name,
        "demo": provider.name == "demo",
        "configured": provider.configured,
        "methods": ["sbp", "card"],
    }


@router.post("/webhook/yookassa")
async def yookassa_webhook(request: Request, session: AsyncSession = Depends(get_session)):
    """Уведомление ЮKassa. Телу не доверяем: перезапрашиваем статус платежа через API.

    Обработка идемпотентна — повторное уведомление ничего не меняет. Ответ 200
    подтверждает приём; при ошибке ЮKassa повторит уведомление (до 24 часов).
    """
    provider = get_provider()
    if not isinstance(provider, YooKassaProvider):
        return JSONResponse(status_code=404, content={"detail": "ЮKassa не подключена"})
    provider_ref = await provider.parse_webhook(request)
    if not provider_ref:
        return JSONResponse(status_code=400, content={"detail": "Уведомление не принято"})

    payment = await session.scalar(
        select(Payment).where(Payment.provider_ref == provider_ref, Payment.provider == provider.name)
    )
    if payment is None:
        # не наш платёж или уведомление пришло раньше ответа на создание — ЮKassa повторит
        log.warning("Вебхук ЮKassa: неизвестный платёж %s", provider_ref)
        return {"ok": True, "result": "unknown_payment"}
    try:
        state = await provider.get_status(provider_ref)
    except PaymentError as exc:
        log.warning("Вебхук ЮKassa: статус %s не получен: %s", provider_ref, exc)
        return JSONResponse(status_code=502, content={"detail": "Повторите позже"})
    result = await apply_payment_state(session, payment, state)
    await session.commit()
    return {"ok": True, "result": result}
