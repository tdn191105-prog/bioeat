"""Демо-провайдер: прежнее поведение MVP, реальные системы не вызываются."""
from __future__ import annotations

import random
from decimal import Decimal

from fastapi import Request

from .base import CreatedPayment, PaymentProvider, PaymentRequest, PaymentState, RefundResult


class DemoProvider(PaymentProvider):
    name = "demo"

    def __init__(self) -> None:
        self._payments: dict[str, PaymentState] = {}

    async def create_payment(self, request: PaymentRequest) -> CreatedPayment:
        ref = f"DEMO-{random.randint(100000, 999999)}"
        if request.simulate_failure:
            self._payments[ref] = PaymentState(ref, "canceled", request.amount, failure_reason="card_declined")
            return CreatedPayment(ref, "canceled", failure_reason="card_declined")
        self._payments[ref] = PaymentState(
            ref, "succeeded", request.amount, metadata={"order_id": str(request.order_id)}
        )
        return CreatedPayment(ref, "succeeded")

    async def get_status(self, provider_ref: str) -> PaymentState:
        return self._payments.get(provider_ref) or PaymentState(provider_ref, "succeeded", Decimal("0"))

    async def refund(self, provider_ref: str, amount: Decimal, receipt: dict | None = None,
                     idempotence_key: str = "") -> RefundResult:
        return RefundResult(f"DEMO-R-{random.randint(100000, 999999)}", "succeeded")

    async def parse_webhook(self, request: Request) -> str | None:
        return None
