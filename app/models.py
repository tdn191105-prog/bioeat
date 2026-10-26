"""Модели базы данных РосПит (SQLAlchemy 2.0)."""
from __future__ import annotations

import enum
from datetime import UTC, date, datetime, time

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


# --------------------------------------------------------------------------- #
#  Перечисления
# --------------------------------------------------------------------------- #
class UserRole(str, enum.Enum):
    student = "student"       # обучающийся / сотрудник — покупатель
    operator = "operator"     # оператор столовой (кухня + выдача)
    admin = "admin"           # администратор: меню, слоты, отчёты


class OrderStatus(str, enum.Enum):
    created = "created"       # оформлен, ждёт оплаты
    paid = "paid"             # оплачен, ждёт подтверждения кухней
    accepted = "accepted"     # кухня приняла
    cooking = "cooking"       # комплектуется
    ready = "ready"           # готов к выдаче (push «Заказ готов»)
    issued = "issued"         # выдан студенту
    cancelled = "cancelled"   # отменён (остатки возвращены)


class PaymentMethod(str, enum.Enum):
    sbp = "sbp"
    card = "card"
    bonus = "bonus"


class PaymentStatus(str, enum.Enum):
    pending = "pending"
    succeeded = "succeeded"
    failed = "failed"
    refunded = "refunded"


ACTIVE_STATUSES = (
    OrderStatus.paid,
    OrderStatus.accepted,
    OrderStatus.cooking,
    OrderStatus.ready,
)


# --------------------------------------------------------------------------- #
#  Пользователи
# --------------------------------------------------------------------------- #
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(160))
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, native_enum=False, length=20), default=UserRole.student, index=True
    )
    group_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    bonus_balance: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    orders: Mapped[list[Order]] = relationship(back_populates="user")
    cart: Mapped[Cart | None] = relationship(back_populates="user", uselist=False)


# --------------------------------------------------------------------------- #
#  Меню
# --------------------------------------------------------------------------- #
class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    icon: Mapped[str] = mapped_column(String(16), default="🍽")
    color: Mapped[str] = mapped_column(String(16), default="#4a7dff")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    dishes: Mapped[list[Dish]] = relationship(
        back_populates="category", cascade="all, delete-orphan"
    )


class Dish(Base):
    __tablename__ = "dishes"

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    price: Mapped[float] = mapped_column(Numeric(10, 2))
    weight_g: Mapped[int] = mapped_column(Integer, default=0)
    kcal: Mapped[int] = mapped_column(Integer, default=0)
    protein: Mapped[float] = mapped_column(Numeric(6, 1), default=0)
    fat: Mapped[float] = mapped_column(Numeric(6, 1), default=0)
    carbs: Mapped[float] = mapped_column(Numeric(6, 1), default=0)
    # эмодзи — компактная подпись для админской таблицы; в клиенте показываем фото
    icon: Mapped[str] = mapped_column(String(16), default="🍲")
    # теги диеты: pp, veg, no_lactose, no_gluten, spicy, hit
    tags: Mapped[list] = mapped_column(JSON, default=list)
    # --- фотография блюда -------------------------------------------------- #
    image_url: Mapped[str] = mapped_column(String(300), default="")          # 800×600
    image_thumb_url: Mapped[str] = mapped_column(String(300), default="")    # 400×300
    image_placeholder: Mapped[str] = mapped_column(String(64), default="")   # HEX-фон
    image_author: Mapped[str] = mapped_column(String(160), default="")
    image_license: Mapped[str] = mapped_column(String(80), default="")
    image_source_url: Mapped[str] = mapped_column(String(400), default="")
    # --- состав и аллергены ------------------------------------------------ #
    ingredients: Mapped[list] = mapped_column(JSON, default=list)  # список строк
    allergens: Mapped[list] = mapped_column(JSON, default=list)    # коды из ALLERGENS
    stock_qty: Mapped[int] = mapped_column(Integer, default=50)   # порций на день
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    category: Mapped[Category] = relationship(back_populates="dishes")


# --------------------------------------------------------------------------- #
#  Слоты выдачи (привязаны к переменам)
# --------------------------------------------------------------------------- #
class PickupSlot(Base):
    __tablename__ = "pickup_slots"

    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(80))          # «Большая перемена»
    starts_at: Mapped[time] = mapped_column(Time)
    ends_at: Mapped[time] = mapped_column(Time)
    capacity: Mapped[int] = mapped_column(Integer, default=60)
    # приём заказов закрывается за N минут до начала выдачи — кухня собирает всё разом
    order_cutoff_minutes: Mapped[int] = mapped_column(Integer, default=60)
    point: Mapped[str] = mapped_column(String(120), default="Окно «Экспресс-выдача»")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    @property
    def time_range(self) -> str:
        return f"{self.starts_at.strftime('%H:%M')}–{self.ends_at.strftime('%H:%M')}"


# --------------------------------------------------------------------------- #
#  Корзина (серверная — синхронизируется между устройствами)
# --------------------------------------------------------------------------- #
class Cart(Base):
    __tablename__ = "carts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    user: Mapped[User] = relationship(back_populates="cart")
    items: Mapped[list[CartItem]] = relationship(
        back_populates="cart", cascade="all, delete-orphan", lazy="selectin"
    )


class CartItem(Base):
    __tablename__ = "cart_items"
    __table_args__ = (UniqueConstraint("cart_id", "dish_id", name="uq_cart_dish"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    cart_id: Mapped[int] = mapped_column(ForeignKey("carts.id", ondelete="CASCADE"), index=True)
    dish_id: Mapped[int] = mapped_column(ForeignKey("dishes.id", ondelete="CASCADE"))
    qty: Mapped[int] = mapped_column(Integer, default=1)

    cart: Mapped[Cart] = relationship(back_populates="items")
    dish: Mapped[Dish] = relationship(lazy="joined")


# --------------------------------------------------------------------------- #
#  Заказы
# --------------------------------------------------------------------------- #
class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(16), unique=True, index=True)  # RP-0431 (старые заказы — BE-0431)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    slot_id: Mapped[int | None] = mapped_column(
        ForeignKey("pickup_slots.id", ondelete="SET NULL"), nullable=True
    )
    slot_label: Mapped[str] = mapped_column(String(120), default="")   # снимок на момент заказа
    pickup_date: Mapped[date] = mapped_column(Date, index=True)
    pickup_point: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus, native_enum=False, length=20),
        default=OrderStatus.created,
        index=True,
    )
    subtotal: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    bonus_used: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    total: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    bonus_earned: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    comment: Mapped[str] = mapped_column(String(300), default="")
    pickup_code: Mapped[str] = mapped_column(String(64), index=True)   # тело QR-кода
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ready_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # почему отменён: expired — не оплатили вовремя, deadline — оплата после отсечки
    cancel_reason: Mapped[str] = mapped_column(String(40), default="")

    user: Mapped[User] = relationship(back_populates="orders", lazy="joined")
    slot: Mapped[PickupSlot | None] = relationship(lazy="joined")
    items: Mapped[list[OrderItem]] = relationship(
        back_populates="order", cascade="all, delete-orphan", lazy="selectin"
    )
    payments: Mapped[list[Payment]] = relationship(
        back_populates="order", cascade="all, delete-orphan", lazy="selectin"
    )


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    dish_id: Mapped[int | None] = mapped_column(
        ForeignKey("dishes.id", ondelete="SET NULL"), nullable=True
    )
    # снимки на момент заказа — цена и вид блюда в истории не должны «плыть»
    name: Mapped[str] = mapped_column(String(160))
    icon: Mapped[str] = mapped_column(String(16), default="🍲")
    image_thumb_url: Mapped[str] = mapped_column(String(300), default="")
    image_placeholder: Mapped[str] = mapped_column(String(64), default="")
    category_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price: Mapped[float] = mapped_column(Numeric(10, 2))
    qty: Mapped[int] = mapped_column(Integer, default=1)

    order: Mapped[Order] = relationship(back_populates="items")


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    method: Mapped[PaymentMethod] = mapped_column(Enum(PaymentMethod, native_enum=False, length=20))
    amount: Mapped[float] = mapped_column(Numeric(10, 2))
    status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus, native_enum=False, length=20), default=PaymentStatus.pending
    )
    provider_ref: Mapped[str] = mapped_column(String(64), default="")  # id «транзакции» в моке
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    order: Mapped[Order] = relationship(back_populates="payments")
