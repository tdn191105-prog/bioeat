"""Pydantic-схемы запросов и ответов."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from .models import OrderStatus, PaymentMethod, UserRole


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ------------------------------- Auth -------------------------------------- #
class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=4, max_length=128)


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=4, max_length=128)
    full_name: str = Field(min_length=2, max_length=160)
    group_name: str | None = Field(default=None, max_length=80)


class UserOut(ORMModel):
    id: int
    email: str
    full_name: str
    role: UserRole
    group_name: str | None = None
    bonus_balance: Decimal


class AuthOut(BaseModel):
    token: str
    user: UserOut


# ------------------------------- Меню --------------------------------------- #
class DishOut(ORMModel):
    id: int
    category_id: int
    name: str
    description: str
    price: Decimal
    weight_g: int
    kcal: int
    protein: Decimal
    fat: Decimal
    carbs: Decimal
    icon: str
    tags: list[str]
    image_url: str = ""
    image_thumb_url: str = ""
    image_placeholder: str = ""
    image_author: str = ""
    image_license: str = ""
    image_source_url: str = ""
    ingredients: list[str] = []
    allergens: list[str] = []
    stock_qty: int
    is_active: bool
    sort_order: int


class DishIn(BaseModel):
    category_id: int
    name: str = Field(min_length=1, max_length=160)
    description: str = ""
    price: Decimal = Field(ge=0, le=100000)
    weight_g: int = Field(default=0, ge=0, le=5000)
    kcal: int = Field(default=0, ge=0, le=10000)
    protein: Decimal = Field(default=Decimal(0), ge=0)
    fat: Decimal = Field(default=Decimal(0), ge=0)
    carbs: Decimal = Field(default=Decimal(0), ge=0)
    icon: str = "🍲"
    tags: list[str] = Field(default_factory=list)
    ingredients: list[str] = Field(default_factory=list)
    allergens: list[str] = Field(default_factory=list)
    stock_qty: int = Field(default=50, ge=0, le=100000)
    is_active: bool = True
    sort_order: int = 0


class DishPatch(BaseModel):
    category_id: int | None = None
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = None
    price: Decimal | None = Field(default=None, ge=0, le=100000)
    weight_g: int | None = Field(default=None, ge=0, le=5000)
    kcal: int | None = Field(default=None, ge=0, le=10000)
    protein: Decimal | None = None
    fat: Decimal | None = None
    carbs: Decimal | None = None
    icon: str | None = None
    tags: list[str] | None = None
    ingredients: list[str] | None = None
    allergens: list[str] | None = None
    stock_qty: int | None = Field(default=None, ge=0, le=100000)
    is_active: bool | None = None
    sort_order: int | None = None


class AllergenOut(BaseModel):
    code: str
    name: str
    short: str
    icon: str
    color: str
    note: str


class CategoryOut(ORMModel):
    id: int
    name: str
    slug: str
    icon: str
    color: str
    sort_order: int
    is_active: bool


class CategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    slug: str | None = Field(default=None, max_length=80)
    icon: str = "🍽"
    color: str = "#4a7dff"
    sort_order: int = 0
    is_active: bool = True


class CategoryPatch(BaseModel):
    name: str | None = None
    icon: str | None = None
    color: str | None = None
    sort_order: int | None = None
    is_active: bool | None = None


# ------------------------------- Слоты -------------------------------------- #
class SlotOut(BaseModel):
    id: int
    label: str
    time_range: str
    starts_at: str
    ends_at: str
    point: str
    capacity: int
    taken: int
    left: int
    is_available: bool
    is_active: bool
    is_open: bool = True
    order_cutoff_minutes: int = 60
    order_deadline: datetime | None = None   # время кампуса
    deadline_time: str = ""                  # «11:00»
    closes_in_minutes: int = 0


class SlotIn(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    starts_at: str  # "10:00"
    ends_at: str    # "10:25"
    capacity: int = Field(default=60, ge=1, le=100000)
    # None — значение по умолчанию из DEFAULT_ORDER_CUTOFF_MINUTES
    order_cutoff_minutes: int | None = Field(default=None, ge=0, le=24 * 60)
    point: str = "Окно «Экспресс-выдача»"
    is_active: bool = True
    sort_order: int = 0


class SlotPatch(BaseModel):
    label: str | None = None
    starts_at: str | None = None
    ends_at: str | None = None
    capacity: int | None = Field(default=None, ge=1, le=100000)
    order_cutoff_minutes: int | None = Field(default=None, ge=0, le=24 * 60)
    point: str | None = None
    is_active: bool | None = None
    sort_order: int | None = None


# ------------------------------- Корзина ------------------------------------ #
class CartItemIn(BaseModel):
    dish_id: int
    qty: int = Field(default=1, ge=0, le=50)


class CartItemOut(BaseModel):
    dish_id: int
    name: str
    icon: str
    image_thumb_url: str = ""
    image_placeholder: str = ""
    category_id: int | None = None
    price: Decimal
    qty: int
    line_total: Decimal
    stock_qty: int
    is_active: bool


class CartOut(BaseModel):
    items: list[CartItemOut]
    count: int
    subtotal: Decimal
    bonus_available: Decimal
    max_bonus_applicable: Decimal


# ------------------------------- Заказы ------------------------------------- #
class OrderCreateIn(BaseModel):
    slot_id: int
    comment: str = Field(default="", max_length=300)
    use_bonus: bool = False
    pickup_date: date | None = None


class OrderItemOut(ORMModel):
    id: int
    dish_id: int | None
    name: str
    icon: str
    price: Decimal
    qty: int
    image_thumb_url: str = ""
    image_placeholder: str = ""
    category_id: int | None = None


class OrderOut(BaseModel):
    id: int
    number: str
    status: OrderStatus
    status_label: str
    slot_label: str
    pickup_point: str
    pickup_date: date
    subtotal: Decimal
    bonus_used: Decimal
    total: Decimal
    bonus_earned: Decimal
    comment: str
    pickup_code: str
    created_at: datetime
    paid_at: datetime | None = None
    ready_at: datetime | None = None
    issued_at: datetime | None = None
    items: list[OrderItemOut]
    customer_name: str | None = None
    customer_group: str | None = None
    cancel_reason: str = ""
    order_deadline: datetime | None = None   # отсечка перемены, время кампуса
    deadline_time: str | None = None
    can_cancel: bool = False                 # может ли студент отменить сам
    pay_until: datetime | None = None        # UTC: до какого момента ждём оплату
    pickup_kind: str = "window"              # window | locker
    locker_id: int | None = None
    locker_name: str = ""
    cell_number: int | None = None
    placed_at: datetime | None = None
    picked_up_at: datetime | None = None


class PayIn(BaseModel):
    method: PaymentMethod = PaymentMethod.sbp
    # в демо-режиме можно смоделировать отказ банка
    simulate_failure: bool = False


class PayOut(BaseModel):
    ok: bool
    message: str
    order: OrderOut | None = None
    provider_ref: str | None = None


# ------------------------------- Оператор ----------------------------------- #
class StatusPatch(BaseModel):
    status: OrderStatus


class IssueIn(BaseModel):
    code: str


class PlaceIn(BaseModel):
    # None — сервер выберет свободную ячейку сам
    cell_number: int | None = Field(default=None, ge=1, le=999)


class PickupTokenOut(BaseModel):
    code: str             # тело QR: ROSPIT:L:<token>
    pin: str              # запасной вариант без камеры
    expires_at: datetime  # UTC
    ttl_seconds: int
    refresh_after_seconds: int
    qr_svg: str
    cell_number: int | None = None
    locker_name: str = ""


class DeviceScanIn(BaseModel):
    code: str = Field(max_length=200)
    ts: int
    nonce: str = Field(min_length=8, max_length=64)
    sig: str = Field(min_length=64, max_length=64)


class DeviceEventIn(BaseModel):
    # door_opened | door_closed | cell_empty | door_jammed
    type: str = Field(max_length=30)
    cell: int | None = Field(default=None, ge=1, le=999)
    empty: bool | None = None
    ts: int
    nonce: str = Field(min_length=8, max_length=64)
    sig: str = Field(min_length=64, max_length=64)


class DeviceHeartbeatIn(BaseModel):
    firmware: str = Field(default="", max_length=40)
    ts: int
    nonce: str = Field(min_length=8, max_length=64)
    sig: str = Field(min_length=64, max_length=64)


# ------------------------------- Статистика --------------------------------- #
class StatsOut(BaseModel):
    orders_today: int
    revenue_today: Decimal
    active_orders: int
    issued_today: int
    avg_check: Decimal
    top_dishes: list[dict]
    by_slot: list[dict]
    users_total: int
    dishes_active: int
