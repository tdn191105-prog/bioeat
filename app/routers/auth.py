"""Аутентификация: вход, регистрация, профиль."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import get_session
from ..deps import COOKIE_NAME, LEGACY_COOKIE_NAME, current_user
from ..models import User, UserRole
from ..schemas import AuthOut, LoginIn, RegisterIn, UserOut
from ..security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=settings.access_token_ttl_minutes * 60,
        path="/",
    )
    response.delete_cookie(LEGACY_COOKIE_NAME, path="/")


@router.post("/login", response_model=AuthOut)
async def login(data: LoginIn, response: Response, session: AsyncSession = Depends(get_session)):
    user = await session.scalar(select(User).where(User.email == data.email.lower()))
    if user is None or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Неверная почта или пароль")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Учётная запись заблокирована")
    token = create_access_token(user.id, user.role.value)
    _set_cookie(response, token)
    return {"token": token, "user": user}


@router.post("/register", response_model=AuthOut, status_code=201)
async def register(
    data: RegisterIn, response: Response, session: AsyncSession = Depends(get_session)
):
    email = data.email.lower()
    exists = await session.scalar(select(User).where(User.email == email))
    if exists:
        raise HTTPException(status_code=409, detail="Пользователь с такой почтой уже есть")
    user = User(
        email=email,
        password_hash=hash_password(data.password),
        full_name=data.full_name.strip(),
        group_name=(data.group_name or "").strip() or None,
        role=UserRole.student,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    token = create_access_token(user.id, user.role.value)
    _set_cookie(response, token)
    return {"token": token, "user": user}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/")
    response.delete_cookie(LEGACY_COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me", response_model=UserOut)
async def me(request: Request, response: Response, user: User = Depends(current_user)):
    # переносим сессию со старой cookie BioEat на новую — один раз и незаметно
    legacy = request.cookies.get(LEGACY_COOKIE_NAME)
    if legacy and not request.cookies.get(COOKIE_NAME):
        _set_cookie(response, legacy)
    return user
