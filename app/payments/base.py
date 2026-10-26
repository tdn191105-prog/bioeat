"""Интерфейс платёжного провайдера.

Сервисный слой (services.pay_order, cancel_order, вебхук) работает только с этим
интерфейсом — замена ЮKassa на банк столовой не трогает бизнес-логику.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal

from fastapi import Request


class PaymentError(Exception):
    """Провайдер недоступен или отклонил запрос (сеть, ключи, валидация)."""


@dataclass
class PaymentRequest:
    payment_id: int                  # наш id платежа — он же ключ идемпотентности
    order_id: int
    order_number: str
    amount: Decimal
    method: str                      # sbp | card
    return_url: str
    description: str
    receipt: dict | None = None      # чек 54-ФЗ, если чеки формирует провайдер
    simulate_failure: bool = False   # только DemoProvider


@dataclass
class CreatedPayment:
    provider_ref: str
    status: str                      # pending | succeeded | canceled
    confirmation_url: str = ""       # карта/3-D Secure/страница выбора банка СБП
    qr_payload: str = ""             # ссылка СБП (https://qr.nspk.ru/…), если отдана напрямую
    failure_reason: str = ""


@dataclass
class PaymentState:
    provider_ref: str
    status: str                      # pending | waiting_for_capture | succeeded | canceled
    amount: Decimal
    currency: str = "RUB"
    metadata: dict = field(default_factory=dict)
    failure_reason: str = ""


@dataclass
class RefundResult:
    refund_ref: str
    status: str                      # pending | succeeded | canceled


class PaymentProvider(ABC):
    name: str = "base"
    #  готов ли провайдер к работе (ключи заданы) — иначе оплата отвечает понятной ошибкой
    configured: bool = True

    @abstractmethod
    async def create_payment(self, request: PaymentRequest) -> CreatedPayment: ...

    @abstractmethod
    async def get_status(self, provider_ref: str) -> PaymentState: ...

    @abstractmethod
    async def refund(self, provider_ref: str, amount: Decimal, receipt: dict | None = None,
                     idempotence_key: str = "") -> RefundResult: ...

    @abstractmethod
    async def parse_webhook(self, request: Request) -> str | None:
        """Возвращает id платежа у провайдера из уведомления или None.

        Телу уведомления не доверяем: статус и сумму сервис потом перезапрашивает
        через get_status().
        """
