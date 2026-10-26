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
    ready = "ready"           # собран, готов к выдаче (push «Заказ готов»)
    in_locker = "in_locker"   # положен в ячейку постамата, ждёт студента
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
    OrderStatus.in_locker,
)

# ещё не собраны — их кухня собирает после отсечки перемены
TO_COLLECT_STATUSES = (OrderStatus.paid, OrderStatus.accepted, OrderStatus.cooking)


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
    # --- постамат ---------------------------------------------------------- #
    locker_id: Mapped[int | None] = mapped_column(
        ForeignKey("lockers.id", ondelete="SET NULL"), nullable=True
    )
    cell_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    placed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    picked_up_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped[User] = relationship(back_populates="orders", lazy="joined")
    slot: Mapped[PickupSlot | None] = relationship(lazy="joined")
    locker: Mapped[Locker | None] = relationship(lazy="joined")
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


# --------------------------------------------------------------------------- #
#  Постамат
#
#  Постамат привязан к точке выдачи строкой — тем же текстом, что в
#  PickupSlot.point и Order.pickup_point. Отдельная сущность PickupPoint
#  потребовала бы переносить данные в уже развёрнутых базах, а автомиграция
#  умеет только добавлять колонки. Когда появится Alembic, строку стоит
#  заменить внешним ключом на таблицу точек.
# --------------------------------------------------------------------------- #
class CellState(str, enum.Enum):
    free = "free"                      # пустая, можно класть
    reserved = "reserved"              # зарезервирована под заказ (кладут прямо сейчас)
    occupied = "occupied"              # в ячейке лежит заказ
    out_of_service = "out_of_service"  # не открывается / сломана


class CellSize(str, enum.Enum):
    S = "S"
    M = "M"
    L = "L"


class Locker(Base):
    __tablename__ = "lockers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))                    # «Корпус Б, 1 этаж»
    point: Mapped[str] = mapped_column(String(120), index=True)       # = PickupSlot.point
    device_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # секрет устройства выводится из SECRET_KEY и версии ключа (см. app/lockers.py);
    # в базе — только хэш, чтобы заметить рассинхрон после смены ключа
    device_secret_hash: Mapped[str] = mapped_column(String(64), default="")
    key_version: Mapped[int] = mapped_column(Integer, default=1)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_online: Mapped[bool] = mapped_column(Boolean, default=False)
    firmware: Mapped[str] = mapped_column(String(40), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    cells: Mapped[list[LockerCell]] = relationship(
        back_populates="locker", cascade="all, delete-orphan", lazy="selectin",
        order_by="LockerCell.number",
    )


class LockerCell(Base):
    __tablename__ = "locker_cells"
    __table_args__ = (UniqueConstraint("locker_id", "number", name="uq_locker_cell"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    locker_id: Mapped[int] = mapped_column(ForeignKey("lockers.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    size: Mapped[CellSize] = mapped_column(Enum(CellSize, native_enum=False, length=4), default=CellSize.M)
    state: Mapped[CellState] = mapped_column(
        Enum(CellState, native_enum=False, length=20), default=CellState.free, index=True
    )
    # без внешнего ключа: orders уже ссылается на lockers, цикл FK SQLite не создаст
    order_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    locker: Mapped[Locker] = relationship(back_populates="cells")


class PickupToken(Base):
    """Одноразовый код выдачи из постамата: QR (128 бит) или 6-значный PIN.

    В базе — только хэш. Использование атомарное: UPDATE … WHERE used_at IS NULL.
    """

    __tablename__ = "pickup_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(8), default="qr")      # qr | pin
    token_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class DeviceNonce(Base):
    """Одноразовые nonce запросов постамата — защита от повтора перехваченного запроса."""

    __tablename__ = "device_nonces"
    __table_args__ = (UniqueConstraint("locker_id", "nonce", name="uq_device_nonce"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    locker_id: Mapped[int] = mapped_column(ForeignKey("lockers.id", ondelete="CASCADE"), index=True)
    nonce: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class LockerCommand(Base):
    """Команда серверу → постамату (open ячейки), забирается long-polling."""

    __tablename__ = "locker_commands"

    id: Mapped[int] = mapped_column(primary_key=True)
    locker_id: Mapped[int] = mapped_column(ForeignKey("lockers.id", ondelete="CASCADE"), index=True)
    action: Mapped[str] = mapped_column(String(20), default="open")
    cell_number: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(40), default="")    # load | unload | service | pickup
    order_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class LockerEvent(Base):
    """Журнал постамата: сканы, двери, датчики, неудачные PIN (для лимита попыток)."""

    __tablename__ = "locker_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    locker_id: Mapped[int] = mapped_column(ForeignKey("lockers.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(30), index=True)
    cell_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    order_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detail: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
