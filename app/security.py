"""Пароли, JWT-токены, коды выдачи.

Хеширование пароля сделано на стандартной библиотеке (PBKDF2-HMAC-SHA256),
чтобы у проекта не было лишних зависимостей и он собирался на любой версии Python.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from datetime import timedelta

from .config import settings

PBKDF2_ROUNDS = 260_000
ALGORITHM = "HS256"


# --------------------------------------------------------------------------- #
#  Пароли
# --------------------------------------------------------------------------- #
def hash_password(raw: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", raw.encode(), salt, PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${salt.hex()}${digest.hex()}"


def verify_password(raw: str, hashed: str) -> bool:
    try:
        scheme, rounds, salt_hex, digest_hex = (hashed or "").split("$")
        if scheme != "pbkdf2_sha256":
            return False
        expected = hashlib.pbkdf2_hmac(
            "sha256", raw.encode(), bytes.fromhex(salt_hex), int(rounds)
        )
        return hmac.compare_digest(expected.hex(), digest_hex)
    except (ValueError, AttributeError):
        return False


# --------------------------------------------------------------------------- #
#  JWT (HS256) — компактная собственная реализация без внешних библиотек
# --------------------------------------------------------------------------- #
def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64url_decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def _sign(message: str) -> str:
    signature = hmac.new(settings.secret_key.encode(), message.encode(), hashlib.sha256).digest()
    return _b64url(signature)


def create_access_token(user_id: int, role: str) -> str:
    expire = int(time.time() + timedelta(minutes=settings.access_token_ttl_minutes).total_seconds())
    header = _b64url(json.dumps({"alg": ALGORITHM, "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64url(
        json.dumps({"sub": str(user_id), "role": role, "exp": expire}, separators=(",", ":")).encode()
    )
    message = f"{header}.{payload}"
    return f"{message}.{_sign(message)}"


def decode_access_token(token: str) -> dict | None:
    try:
        header, payload, signature = (token or "").split(".")
    except ValueError:
        return None

    if not hmac.compare_digest(_sign(f"{header}.{payload}"), signature):
        return None

    try:
        data = json.loads(_b64url_decode(payload))
    except (ValueError, json.JSONDecodeError):
        return None

    if not isinstance(data, dict) or int(data.get("exp", 0)) < time.time():
        return None
    return data


# --------------------------------------------------------------------------- #
#  Коды выдачи заказа (тело QR)
# --------------------------------------------------------------------------- #
# Префикс тела QR. Старые коды BIOEAT: продолжают приниматься, чтобы заказы,
# оформленные до переименования, можно было выдать.
PICKUP_PREFIX = "ROSPIT"
LEGACY_PICKUP_PREFIXES = ("BIOEAT",)


def _pickup_signature(raw: str) -> str:
    return hmac.new(settings.secret_key.encode(), raw.encode(), hashlib.sha256).hexdigest()[:12]


def make_pickup_code(order_number: str) -> str:
    """Подписанный код выдачи. Формат: ROSPIT:<номер>:<nonce>:<подпись>."""
    nonce = secrets.token_hex(6)
    raw = f"{order_number}:{nonce}"
    return f"{PICKUP_PREFIX}:{raw}:{_pickup_signature(raw)}"


def verify_pickup_code(code: str) -> str | None:
    """Проверяет подпись кода и возвращает номер заказа."""
    parts = (code or "").strip().split(":")
    if len(parts) != 4 or parts[0] not in (PICKUP_PREFIX, *LEGACY_PICKUP_PREFIXES):
        return None
    _, number, nonce, sig = parts
    expected = _pickup_signature(f"{number}:{nonce}")
    return number if hmac.compare_digest(expected, sig) else None
