"""Платёжные провайдеры. Выбор — переменной PAYMENT_PROVIDER (или DEMO_PAYMENTS)."""
from __future__ import annotations

from ..config import settings
from .base import (
    CreatedPayment,
    PaymentError,
    PaymentProvider,
    PaymentRequest,
    PaymentState,
    RefundResult,
)
from .demo import DemoProvider
from .stubs import BankAcquiringProvider, CloudPaymentsProvider
from .yookassa import YooKassaProvider

_provider: PaymentProvider | None = None


def build_provider(name: str | None = None) -> PaymentProvider:
    name = name or settings.active_payment_provider
    if name == "demo":
        return DemoProvider()
    if name == "yookassa":
        return YooKassaProvider(
            settings.yookassa_shop_id,
            settings.yookassa_secret_key,
            settings.yookassa_api_url,
            check_ip=settings.yookassa_check_ip,
        )
    if name == "cloudpayments":
        return CloudPaymentsProvider()
    if name == "bank":
        return BankAcquiringProvider()
    raise ValueError(f"Неизвестный PAYMENT_PROVIDER: {name}")


def get_provider() -> PaymentProvider:
    global _provider
    if _provider is None:
        _provider = build_provider()
    return _provider


def set_provider(provider: PaymentProvider | None) -> None:
    """Подмена провайдера — для тестов и переключения без перезапуска."""
    global _provider
    _provider = provider


__all__ = [
    "BankAcquiringProvider",
    "CloudPaymentsProvider",
    "CreatedPayment",
    "DemoProvider",
    "PaymentError",
    "PaymentProvider",
    "PaymentRequest",
    "PaymentState",
    "RefundResult",
    "YooKassaProvider",
    "build_provider",
    "get_provider",
    "set_provider",
]
