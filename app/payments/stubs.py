"""Заглушки CloudPayments и интернет-эквайринга банка с тем же интерфейсом.

Полная интеграция не сделана: нужен выбор провайдера и договор. Структура та же,
что у YooKassaProvider, — переписать четыре метода по документации провайдера.
"""
from __future__ import annotations

from decimal import Decimal

from fastapi import Request

from .base import CreatedPayment, PaymentError, PaymentProvider, PaymentRequest, PaymentState, RefundResult


class _NotImplementedProvider(PaymentProvider):
    configured = False
    docs = ""

    def _todo(self):
        raise PaymentError(f"Провайдер «{self.name}» ещё не подключён. TODO: {self.docs}")

    async def create_payment(self, request: PaymentRequest) -> CreatedPayment:
        self._todo()

    async def get_status(self, provider_ref: str) -> PaymentState:
        self._todo()

    async def refund(self, provider_ref: str, amount: Decimal, receipt: dict | None = None,
                     idempotence_key: str = "") -> RefundResult:
        self._todo()

    async def parse_webhook(self, request: Request) -> str | None:
        return None


class CloudPaymentsProvider(_NotImplementedProvider):
    # TODO: платёжная форма/виджет или API /payments/cards/charge, СБП — /payments/qr/sbp/link;
    # уведомления Pay/Fail/Refund подписаны HMAC-SHA256 заголовком Content-HMAC (API Secret).
    name = "cloudpayments"
    docs = "https://developers.cloudpayments.ru/"


class BankAcquiringProvider(_NotImplementedProvider):
    # TODO: интернет-эквайринг банка столовой (Т-Банк: /v2/Init, /v2/GetState, /v2/Cancel,
    # уведомления с полем Token; Сбер и Альфа — свои API). Выбирать, если у столовой уже есть договор.
    name = "bank"
    docs = "документация банка, с которым у столовой договор эквайринга"
