"""ЮKassa через HTTP API v3 (httpx), без SDK — так проще тестировать и меньше зависимостей.

Документация: https://yookassa.ru/developers/api
"""
from __future__ import annotations

import ipaddress
import logging
from decimal import Decimal

import httpx
from fastapi import Request

from .base import (
    CreatedPayment,
    PaymentError,
    PaymentProvider,
    PaymentRequest,
    PaymentState,
    RefundResult,
)

log = logging.getLogger("rospit")

# Адреса, с которых ЮKassa отправляет уведомления (yookassa.ru/developers/using-api/webhooks).
# Список меняется редко, но перед боевым запуском его стоит сверить.
YOOKASSA_NETWORKS = [
    ipaddress.ip_network(n)
    for n in (
        "185.71.76.0/27",
        "185.71.77.0/27",
        "77.75.153.0/25",
        "77.75.156.11/32",
        "77.75.156.35/32",
        "77.75.154.128/25",
        "2a02:5180::/32",
    )
]


def is_yookassa_ip(host: str | None) -> bool:
    try:
        addr = ipaddress.ip_address(host or "")
    except ValueError:
        return False
    return any(addr in net for net in YOOKASSA_NETWORKS)


def _money(value: Decimal) -> str:
    return f"{Decimal(value).quantize(Decimal('0.01'))}"


class YooKassaProvider(PaymentProvider):
    name = "yookassa"

    def __init__(self, shop_id: str, secret_key: str, api_url: str = "https://api.yookassa.ru/v3",
                 *, check_ip: bool = True, transport: httpx.AsyncBaseTransport | None = None):
        self.shop_id = shop_id
        self.secret_key = secret_key
        self.api_url = api_url.rstrip("/")
        self.check_ip = check_ip
        self.transport = transport        # тесты подставляют httpx.MockTransport
        self.configured = bool(shop_id and secret_key)

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.api_url,
            auth=(self.shop_id, self.secret_key),
            timeout=httpx.Timeout(15.0, connect=5.0),
            transport=self.transport,
        )

    async def _call(self, method: str, path: str, *, json: dict | None = None,
                    idempotence_key: str = "") -> dict:
        if not self.configured:
            raise PaymentError("ЮKassa не настроена: задайте YOOKASSA_SHOP_ID и YOOKASSA_SECRET_KEY")
        headers = {"Idempotence-Key": idempotence_key} if idempotence_key else {}
        try:
            async with self._client() as client:
                response = await client.request(method, path, json=json, headers=headers)
        except httpx.HTTPError as exc:
            raise PaymentError(f"ЮKassa недоступна: {exc}") from exc
        if response.status_code >= 400:
            try:
                detail = response.json().get("description", response.text)
            except ValueError:
                detail = response.text
            log.warning("ЮKassa %s %s → %s: %s", method, path, response.status_code, detail)
            raise PaymentError(f"ЮKassa отклонила запрос: {detail}")
        return response.json()

    async def create_payment(self, request: PaymentRequest) -> CreatedPayment:
        body: dict = {
            "amount": {"value": _money(request.amount), "currency": "RUB"},
            # одностадийная оплата: СБП двухстадийную не поддерживает
            "capture": True,
            "payment_method_data": {"type": "sbp" if request.method == "sbp" else "bank_card"},
            "confirmation": {"type": "redirect", "return_url": request.return_url},
            "description": request.description[:128],
            "metadata": {"order_id": str(request.order_id), "payment_id": str(request.payment_id)},
        }
        if request.receipt:
            body["receipt"] = request.receipt
        data = await self._call(
            "POST", "/payments", json=body, idempotence_key=f"rospit-pay-{request.payment_id}"
        )
        confirmation = data.get("confirmation") or {}
        return CreatedPayment(
            provider_ref=data["id"],
            status=data.get("status", "pending"),
            confirmation_url=confirmation.get("confirmation_url", ""),
            failure_reason=(data.get("cancellation_details") or {}).get("reason", ""),
        )

    async def get_status(self, provider_ref: str) -> PaymentState:
        data = await self._call("GET", f"/payments/{provider_ref}")
        amount = data.get("amount") or {}
        return PaymentState(
            provider_ref=data["id"],
            status=data.get("status", "pending"),
            amount=Decimal(str(amount.get("value", "0"))),
            currency=amount.get("currency", "RUB"),
            metadata=data.get("metadata") or {},
            failure_reason=(data.get("cancellation_details") or {}).get("reason", ""),
        )

    async def refund(self, provider_ref: str, amount: Decimal, receipt: dict | None = None,
                     idempotence_key: str = "") -> RefundResult:
        body: dict = {"payment_id": provider_ref, "amount": {"value": _money(amount), "currency": "RUB"}}
        if receipt:
            body["receipt"] = receipt
        data = await self._call(
            "POST", "/refunds", json=body, idempotence_key=idempotence_key or f"rospit-refund-{provider_ref}"
        )
        return RefundResult(refund_ref=data["id"], status=data.get("status", "pending"))

    async def parse_webhook(self, request: Request) -> str | None:
        if self.check_ip and not is_yookassa_ip(request.client.host if request.client else None):
            log.warning("Вебхук ЮKassa с чужого адреса %s отклонён", request.client)
            return None
        try:
            payload = await request.json()
        except ValueError:
            return None
        obj = payload.get("object") or {}
        event = payload.get("event", "")
        if event.startswith("refund."):
            return obj.get("payment_id")
        return obj.get("id")
