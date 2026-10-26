"""Зависимости FastAPI: текущий пользователь, проверка ролей."""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_session
from .models import User, UserRole
from .security import decode_access_token

COOKIE_NAME = "rospit_token"
# cookie времён BioEat: читаем, чтобы никого не разлогинить; при входе стираем
LEGACY_COOKIE_NAME = "bioeat_token"


def _extract_token(request: Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.cookies.get(COOKIE_NAME) or request.cookies.get(LEGACY_COOKIE_NAME)


async def current_user_optional(
    request: Request, session: AsyncSession = Depends(get_session)
) -> User | None:
    token = _extract_token(request)
    if not token:
        return None
    payload = decode_access_token(token)
    if not payload:
        return None
    try:
        user_id = int(payload.get("sub", 0))
    except (TypeError, ValueError):
        return None
    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        return None
    return user


async def current_user(user: User | None = Depends(current_user_optional)) -> User:
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Требуется вход в приложение"
        )
    return user


def require_roles(*roles: UserRole):
    async def _guard(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Недостаточно прав")
        return user

    return _guard


staff_required = require_roles(UserRole.operator, UserRole.admin)
admin_required = require_roles(UserRole.admin)
