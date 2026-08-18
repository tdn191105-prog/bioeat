"""Серверная корзина — синхронизируется между устройствами пользователя."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import current_user
from ..models import User
from ..schemas import CartItemIn, CartOut
from ..services import add_to_cart, cart_payload, clear_cart, set_cart_item

router = APIRouter(prefix="/api/cart", tags=["cart"])


@router.get("", response_model=CartOut)
async def get_cart(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return await cart_payload(session, user)


@router.post("/items", response_model=CartOut)
async def add_item(
    data: CartItemIn,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    """Прибавляет qty порций к тому, что уже лежит в корзине."""
    return await add_to_cart(session, user, data.dish_id, data.qty or 1)


@router.put("/items", response_model=CartOut)
async def set_item(
    data: CartItemIn,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    """Задаёт точное количество. qty = 0 удаляет позицию."""
    return await set_cart_item(session, user, data.dish_id, data.qty)


@router.delete("/items/{dish_id}", response_model=CartOut)
async def delete_item(
    dish_id: int,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    return await set_cart_item(session, user, dish_id, 0)


@router.delete("", response_model=CartOut)
async def empty_cart(
    user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
):
    await clear_cart(session, user)
    return await cart_payload(session, user)
