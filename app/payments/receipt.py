"""Чек 54-ФЗ для провайдера: позиции заказа, НДС и бонусная скидка до копейки."""
from __future__ import annotations

from decimal import Decimal

from ..config import settings


def _kop(value) -> int:
    return int((Decimal(str(value)) * 100).quantize(Decimal("1")))


def _rub(kop: int) -> str:
    return f"{kop // 100}.{kop % 100:02d}"


def build_receipt(order, email: str, *, total: Decimal | None = None) -> dict:
    """Позиции заказа для чека. Бонусы — скидка, распределённая по позициям.

    Сумма чека обязана совпасть с суммой платежа до копейки. Скидку делим
    пропорционально стоимости строк, остаток копеек — последней строке;
    если цена за штуку не делится нацело, строку разбиваем на две.
    """
    items = sorted(order.items, key=lambda i: i.id)
    lines = [(i.name, i.qty, _kop(i.price)) for i in items]
    subtotal = sum(q * p for _, q, p in lines)
    target = _kop(order.total if total is None else total)
    discount = max(0, subtotal - target)

    # пропорционально стоимости строк с округлением вниз…
    shares = [discount * q * p // subtotal if subtotal else 0 for _, q, p in lines]
    # …а оставшиеся копейки раздаём строкам, где ещё есть запас (с конца)
    left = discount - sum(shares)
    for index in reversed(range(len(lines))):
        if left <= 0:
            break
        _, qty, price = lines[index]
        room = qty * price - shares[index]
        take = min(room, left)
        shares[index] += take
        left -= take

    out: list[dict] = []

    def add(name: str, qty: int, unit_kop: int) -> None:
        item = {
            "description": name[:128],
            "quantity": f"{qty}.00",
            "amount": {"value": _rub(unit_kop), "currency": "RUB"},
            "vat_code": settings.receipt_vat_code,
            "payment_mode": "full_payment",
            "payment_subject": settings.receipt_payment_subject,
        }
        out.append(item)

    for (name, qty, price), share in zip(lines, shares, strict=True):
        line_total = qty * price - share
        unit, rest = divmod(line_total, qty)
        if rest == 0:
            add(name, qty, unit)
        else:
            # rest штук по unit+1 копейке и qty-rest штук по unit
            add(name, rest, unit + 1)
            add(name, qty - rest, unit)

    receipt: dict = {"customer": {"email": email}, "items": out}
    if settings.receipt_tax_system_code:
        receipt["tax_system_code"] = settings.receipt_tax_system_code
    return receipt


def receipt_total(receipt: dict) -> Decimal:
    kop = sum(_kop(i["amount"]["value"]) * int(Decimal(i["quantity"])) for i in receipt["items"])
    return Decimal(kop) / 100
