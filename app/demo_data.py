"""Генератор демонстрационных заказов.

Наполняет базу правдоподобной активностью, чтобы на презентации экран оператора
и отчёты администратора не были пустыми.

Запуск:
    docker compose exec app python -m app.demo_data
    docker compose exec app python -m app.demo_data --reset   # удалить прежние демо-заказы
"""
from __future__ import annotations

import asyncio
import random
import sys
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import SessionLocal, create_all, engine, ensure_columns
from .models import (
    Dish,
    Order,
    OrderItem,
    OrderStatus,
    Payment,
    PaymentMethod,
    PaymentStatus,
    PickupSlot,
    User,
    UserRole,
)
from .security import hash_password, make_pickup_code
from .seed import seed
from .services import campus_now, campus_today, generate_order_number, money

STUDENTS = [
    ("Тапильский Роман", "roman@rosbiotech.ru", "23о-380302-УБ/1"),
    ("Кусля Валентин", "valentin@rosbiotech.ru", "23о-380302-УБ/1"),
    ("Грачёв Владимир", "vladimir@rosbiotech.ru", "23о-380302-УБ/1"),
    ("Смирнова Анна", "anna@rosbiotech.ru", "24о-190302-ИБ/2"),
    ("Кузнецов Илья", "ilya@rosbiotech.ru", "24о-190302-ИБ/2"),
    ("Петрова Мария", "maria@rosbiotech.ru", "22о-380302-УБ/3"),
    ("Соколов Дмитрий", "sokolov@rosbiotech.ru", "22о-380302-УБ/3"),
    ("Новикова Елена", "elena@rosbiotech.ru", "25о-060301-БТ/1"),
]

COMMENTS = ["", "", "", "без лука", "приборы не нужны", "два соуса, пожалуйста", "без хлеба"]


async def ensure_students(session: AsyncSession) -> list[User]:
    users = []
    for full_name, email, group in STUDENTS:
        user = await session.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(
                email=email,
                password_hash=hash_password("student"),
                full_name=full_name,
                role=UserRole.student,
                group_name=group,
                bonus_balance=random.choice([0, 45, 120, 250, 310]),
            )
            session.add(user)
        users.append(user)
    await session.commit()
    for user in users:
        await session.refresh(user)
    return users


async def make_order(
    session: AsyncSession,
    user: User,
    dishes: list[Dish],
    slot: PickupSlot,
    on_date,
    status: OrderStatus,
) -> Order:
    picked = random.sample(dishes, random.randint(1, 4))
    items, subtotal = [], money(0)
    for dish in picked:
        qty = random.choices([1, 1, 1, 2], k=1)[0]
        price = money(dish.price)
        subtotal += money(price * qty)
        items.append(
            OrderItem(dish_id=dish.id, name=dish.name, icon=dish.icon, price=price, qty=qty)
        )
        dish.stock_qty = max(0, dish.stock_qty - qty)

    bonus_used = money(0)
    if random.random() < 0.25 and money(user.bonus_balance) > 0:
        bonus_used = min(money(user.bonus_balance), money(subtotal * 3 / 10))
        user.bonus_balance = money(money(user.bonus_balance) - bonus_used)

    total = money(subtotal - bonus_used)
    number = await generate_order_number(session)
    created = campus_now() - timedelta(minutes=random.randint(15, 240))

    order = Order(
        number=number,
        user_id=user.id,
        slot_id=slot.id,
        slot_label=f"{slot.label} · {slot.time_range}",
        pickup_point=slot.point,
        pickup_date=on_date,
        status=status,
        subtotal=money(subtotal),
        bonus_used=bonus_used,
        total=total,
        bonus_earned=money(total * 5 / 100),
        comment=random.choice(COMMENTS),
        pickup_code=make_pickup_code(number),
        created_at=created,
        items=items,
    )

    if status != OrderStatus.created:
        order.paid_at = created + timedelta(seconds=random.randint(20, 180))
        session.add(
            Payment(
                order=order,
                method=random.choice([PaymentMethod.sbp, PaymentMethod.card]),
                amount=total,
                status=PaymentStatus.succeeded,
                provider_ref=f"DEMO-{random.randint(100000, 999999)}",
            )
        )
        user.bonus_balance = money(money(user.bonus_balance) + money(order.bonus_earned))
    if status in (OrderStatus.ready, OrderStatus.issued):
        order.ready_at = order.paid_at + timedelta(minutes=random.randint(8, 25))
    if status == OrderStatus.issued:
        order.issued_at = order.ready_at + timedelta(minutes=random.randint(1, 20))

    session.add(order)
    return order


async def generate(session: AsyncSession) -> dict:
    users = await ensure_students(session)
    dishes = list(
        (await session.scalars(select(Dish).where(Dish.is_active.is_(True)))).all()
    )
    slots = list(
        (await session.scalars(select(PickupSlot).where(PickupSlot.is_active.is_(True)))).all()
    )
    if not dishes or not slots:
        return {"error": "Сначала наполните меню (app.seed)"}

    today = campus_today()
    plan = [
        # (дата, статус, количество)
        (today - timedelta(days=1), OrderStatus.issued, 14),
        (today, OrderStatus.issued, 9),
        (today, OrderStatus.ready, 3),
        (today, OrderStatus.cooking, 3),
        (today, OrderStatus.accepted, 2),
        (today, OrderStatus.paid, 4),
        (today + timedelta(days=1), OrderStatus.paid, 6),
        (today + timedelta(days=1), OrderStatus.accepted, 2),
    ]

    created = 0
    for on_date, status, count in plan:
        for _ in range(count):
            await make_order(
                session, random.choice(users), dishes, random.choice(slots), on_date, status
            )
            created += 1

    await session.commit()
    return {"orders": created, "students": len(users)}


async def reset(session: AsyncSession) -> int:
    emails = [email for _, email, _ in STUDENTS]
    users = (await session.scalars(select(User).where(User.email.in_(emails)))).all()
    ids = [u.id for u in users]
    if not ids:
        return 0
    orders = (await session.scalars(select(Order).where(Order.user_id.in_(ids)))).all()
    count = len(orders)
    await session.execute(delete(Order).where(Order.user_id.in_(ids)))
    await session.commit()
    return count


async def main() -> None:
    await create_all()
    await ensure_columns()
    try:
        async with SessionLocal() as session:
            await seed(session)
            if "--reset" in sys.argv:
                removed = await reset(session)
                print(f"Удалено демо-заказов: {removed}")
                return
            result = await generate(session)
        print("Демо-данные:", result)
    finally:
        # без этого рабочий поток aiosqlite не даёт процессу завершиться
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
