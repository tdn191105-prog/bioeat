"""Наполнение базы демонстрационными данными.

Меню собрано по типовому ассортименту и ценам вузовской столовой Москвы.
Все позиции редактируются в админ-панели (раздел «Меню»).
"""
from __future__ import annotations

import json
import logging
from datetime import time
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import SessionLocal, create_all, engine, ensure_columns
from .dish_details import DISH_DETAILS
from .lockers import refresh_locker_points, seed_lockers
from .models import Category, Dish, PickupSlot, User, UserRole
from .reference import slugify
from .security import hash_password

log = logging.getLogger("rospit")

BASE_DIR = Path(__file__).resolve().parent.parent
DISH_IMAGES_DIR = BASE_DIR / "static" / "img" / "dishes"

# --------------------------------------------------------------------------- #
CATEGORIES = [
    # slug,      name,             icon, color,     sort
    ("combo",    "Комбо-обеды",    "🍱", "#4a7dff", 10),
    ("soups",    "Супы",           "🍲", "#f0803c", 20),
    ("hot",      "Горячее",        "🍗", "#e4574c", 30),
    ("sides",    "Гарниры",        "🍚", "#4cc38a", 40),
    ("salads",   "Салаты",         "🥗", "#2fb894", 50),
    ("bakery",   "Выпечка",        "🥐", "#f0b429", 60),
    ("drinks",   "Напитки",        "☕", "#3fb8d4", 70),
    ("desserts", "Десерты",        "🍰", "#b74cd4", 80),
]

# name, price, weight, kcal, p, f, c, icon, tags, stock
DISHES: dict[str, list[tuple]] = {
    "combo": [
        ("Комплексный обед «Студенческий»", 329, 650, 780, 34.0, 26.0, 92.0, "🍱",
         ["hit"], 60, "Суп дня, горячее с гарниром, салат, хлеб и напиток на выбор."),
        ("Комбо «Лёгкий ПП»", 349, 520, 520, 42.0, 14.0, 48.0, "🥙",
         ["pp", "hit"], 40, "Куриная грудка гриль, булгур, овощной салат и морс без сахара."),
        ("Комбо «Вегетарианское»", 299, 560, 610, 21.0, 18.0, 84.0, "🥬",
         ["veg", "pp"], 30, "Крем-суп из тыквы, овощное рагу, греческий салат и травяной чай."),
        ("Комбо «Завтрак»", 219, 430, 540, 22.0, 19.0, 62.0, "🍳",
         [], 45, "Омлет с сыром, сырники, кофе на выбор."),
    ],
    "soups": [
        ("Борщ с говядиной", 139, 300, 210, 11.0, 9.0, 21.0, "🍜", ["hit"], 50,
         "Классический борщ на говяжьем бульоне со сметаной."),
        ("Щи из свежей капусты", 119, 300, 165, 8.0, 6.5, 19.0, "🥬", [], 40,
         "Домашние щи с картофелем и зеленью."),
        ("Куриный суп с лапшой", 129, 300, 180, 12.0, 6.0, 20.0, "🍲", [], 50,
         "Лёгкий бульон с домашней лапшой и куриным филе."),
        ("Солянка мясная", 169, 300, 265, 15.0, 16.0, 12.0, "🥘", ["spicy"], 30,
         "Наваристая солянка с копчёностями, оливками и лимоном."),
        ("Крем-суп из тыквы", 129, 280, 145, 4.0, 6.0, 18.0, "🎃", ["veg", "pp", "no_lactose"], 25,
         "Бархатный крем-суп на кокосовом молоке с тыквенными семечками."),
        ("Гороховый суп с копчёностями", 119, 300, 205, 12.0, 7.0, 24.0, "🫛", [], 30,
         "Густой гороховый суп с копчёной грудинкой и гренками."),
    ],
    "hot": [
        ("Котлета по-киевски", 259, 180, 420, 26.0, 27.0, 18.0, "🍗", ["hit"], 40,
         "Куриное филе с травяным маслом в хрустящей панировке."),
        ("Куриная грудка гриль", 219, 160, 195, 36.0, 5.0, 1.0, "🍖", ["pp", "no_lactose", "no_gluten"], 55,
         "Филе на гриле с лимоном и розмарином. Без масла."),
        ("Плов с бараниной", 249, 300, 480, 22.0, 21.0, 52.0, "🍚", ["no_lactose"], 35,
         "Рассыпчатый плов с бараниной, морковью и зирой."),
        ("Бефстроганов", 269, 220, 355, 24.0, 22.0, 12.0, "🥩", [], 30,
         "Говядина в сливочно-грибном соусе."),
        ("Треска запечённая", 239, 180, 190, 28.0, 6.0, 4.0, "🐟", ["pp", "no_lactose"], 25,
         "Филе трески с лимоном и прованскими травами."),
        ("Тефтели в томатном соусе", 199, 200, 310, 19.0, 17.0, 20.0, "🍝", [], 40,
         "Мясные тефтели в густом томатном соусе."),
        ("Котлета рубленая куриная", 159, 150, 265, 18.0, 15.0, 12.0, "🍔", [], 60,
         "Домашняя котлета из куриного фарша."),
        ("Овощное рагу", 149, 250, 175, 5.0, 7.0, 24.0, "🍆", ["veg", "pp", "no_lactose", "no_gluten"], 30,
         "Сезонные овощи, томлёные с чесноком и базиликом."),
        ("Паста карбонара", 229, 280, 520, 21.0, 24.0, 55.0, "🍝", ["hit"], 35,
         "Спагетти с беконом в сливочном соусе с пармезаном."),
    ],
    "sides": [
        ("Картофельное пюре", 79, 200, 185, 4.0, 6.0, 28.0, "🥔", ["veg"], 80,
         "Пюре на сливочном масле."),
        ("Гречка отварная", 69, 200, 165, 6.0, 3.0, 30.0, "🌾", ["veg", "pp", "no_lactose"], 70,
         "Рассыпчатая гречневая крупа."),
        ("Рис припущенный", 69, 200, 175, 4.0, 3.5, 33.0, "🍚", ["veg", "no_lactose", "no_gluten"], 70,
         "Длиннозёрный рис с зеленью."),
        ("Булгур с овощами", 89, 200, 195, 6.0, 4.0, 34.0, "🥣", ["veg", "pp"], 40,
         "Булгур с болгарским перцем и морковью."),
        ("Макароны отварные", 65, 200, 210, 7.0, 3.0, 40.0, "🍜", ["veg"], 70,
         "Паста аль денте со сливочным маслом."),
        ("Овощи гриль", 119, 180, 110, 3.0, 5.0, 13.0, "🥦", ["veg", "pp", "no_lactose", "no_gluten"], 35,
         "Цукини, баклажан, перец и томаты черри на гриле."),
        ("Картофель по-деревенски", 99, 180, 245, 4.0, 11.0, 32.0, "🍟", ["veg"], 50,
         "Дольки картофеля со специями, запечённые в духовке."),
    ],
    "salads": [
        ("Салат «Цезарь» с курицей", 189, 200, 285, 18.0, 18.0, 11.0, "🥗", ["hit"], 40,
         "Романо, куриное филе, пармезан, гренки, соус цезарь."),
        ("Винегрет", 89, 180, 125, 2.5, 6.0, 15.0, "🥗", ["veg", "pp", "no_lactose"], 40,
         "Свёкла, картофель, морковь, горошек и квашеная капуста."),
        ("Салат «Оливье»", 119, 180, 230, 6.0, 17.0, 13.0, "🥔", [], 45,
         "Классический оливье с докторской колбасой."),
        ("Греческий салат", 149, 180, 165, 5.0, 12.0, 8.0, "🫒", ["veg", "pp", "no_gluten"], 35,
         "Огурцы, томаты, перец, фета, маслины и оливковое масло."),
        ("Витаминный салат", 79, 150, 75, 1.5, 3.5, 9.0, "🥕", ["veg", "pp", "no_lactose", "no_gluten"], 50,
         "Капуста, морковь и яблоко с лимонной заправкой."),
        ("Морковь по-корейски", 79, 150, 115, 1.5, 7.0, 12.0, "🥕", ["veg", "spicy", "no_lactose"], 40,
         "Пикантная морковь с кориандром и чесноком."),
    ],
    "bakery": [
        ("Пирожок с капустой", 65, 90, 210, 5.0, 7.0, 31.0, "🥟", ["veg"], 80,
         "Печёный пирожок из дрожжевого теста."),
        ("Сосиска в тесте", 95, 110, 305, 9.0, 16.0, 30.0, "🌭", ["hit"], 70,
         "Сочная сосиска в мягком тесте."),
        ("Слойка с творогом", 89, 100, 285, 7.0, 14.0, 32.0, "🥐", [], 50,
         "Слоёное тесто с творожной начинкой."),
        ("Круассан классический", 99, 80, 275, 6.0, 15.0, 28.0, "🥐", [], 45,
         "Хрустящий круассан на сливочном масле."),
        ("Ватрушка с творогом", 85, 110, 265, 8.0, 9.0, 36.0, "🧀", [], 40,
         "Домашняя ватрушка с ванилью."),
        ("Пицца «Пепперони», кусок", 139, 150, 340, 14.0, 15.0, 36.0, "🍕", ["spicy", "hit"], 40,
         "Кусок пиццы с пепперони и моцареллой."),
        ("Хлеб ржаной", 15, 40, 85, 2.5, 0.5, 17.0, "🍞", ["veg", "no_lactose"], 200,
         "Ломтик ржаного хлеба."),
    ],
    "drinks": [
        ("Кофе американо", 99, 250, 5, 0.3, 0.0, 0.5, "☕", ["no_lactose", "no_gluten"], 200,
         "Свежесваренный американо из зерновой обжарки."),
        ("Капучино", 139, 300, 120, 6.0, 6.0, 11.0, "☕", ["hit"], 200,
         "Эспрессо с молочной пенкой."),
        ("Латте", 149, 350, 145, 7.0, 6.5, 14.0, "🥛", [], 200,
         "Мягкий латте на цельном молоке."),
        ("Чай чёрный / зелёный", 55, 250, 2, 0.0, 0.0, 0.3, "🍵", ["veg", "no_lactose", "no_gluten"], 250,
         "Листовой чай в чайнике."),
        ("Компот из сухофруктов", 55, 250, 95, 0.3, 0.1, 23.0, "🍹", ["veg", "no_lactose", "no_gluten"], 120,
         "Домашний компот, сваренный утром."),
        ("Морс клюквенный", 79, 300, 105, 0.2, 0.0, 25.0, "🫐", ["veg", "no_lactose", "no_gluten"], 100,
         "Ягодный морс без искусственных добавок."),
        ("Вода питьевая 0,5 л", 55, 500, 0, 0.0, 0.0, 0.0, "💧", ["veg", "pp", "no_lactose", "no_gluten"], 150,
         "Негазированная питьевая вода."),
        ("Какао", 109, 300, 165, 5.0, 5.0, 24.0, "🍫", [], 60,
         "Горячее какао на молоке."),
    ],
    "desserts": [
        ("Сырники со сметаной", 159, 180, 320, 16.0, 12.0, 34.0, "🥞", ["hit"], 45,
         "Три сырника из творога 9% со сметаной."),
        ("Блины с джемом", 129, 160, 295, 7.0, 9.0, 45.0, "🥞", ["veg"], 40,
         "Тонкие блины с ягодным джемом."),
        ("Шарлотка яблочная", 109, 130, 245, 4.0, 7.0, 41.0, "🍎", ["veg"], 35,
         "Пышный яблочный пирог."),
        ("Овсяное печенье", 45, 60, 210, 3.0, 8.0, 31.0, "🍪", ["veg"], 90,
         "Печенье с цельными овсяными хлопьями."),
        ("Йогурт натуральный", 89, 150, 105, 5.0, 3.5, 12.0, "🥛", ["pp"], 50,
         "Питьевой йогурт без сахара."),
    ],
}

SLOTS = [
    ("Перемена 1", time(9, 30), time(9, 45), 40, "Окно «Экспресс-выдача», корпус А", 10),
    ("Перемена 2 (пик)", time(10, 0), time(10, 25), 80, "Окно «Экспресс-выдача», корпус А", 20),
    ("Большая перемена", time(12, 0), time(12, 45), 120, "Окно «Экспресс-выдача», корпус А", 30),
    ("Перемена 4", time(14, 20), time(14, 35), 50, "Постамат, 1 этаж корпуса Б", 40),
    ("Вечерняя выдача", time(17, 30), time(18, 0), 40, "Постамат, 1 этаж корпуса Б", 50),
]

USERS = [
    ("student@rosbiotech.ru", "student", "Дмитрий Тапильский", UserRole.student, "23о-380302-УБ/1", 250),
    ("operator@rosbiotech.ru", "operator", "Оператор столовой", UserRole.operator, None, 0),
    ("admin@rosbiotech.ru", "admin", "Администратор РосПит", UserRole.admin, None, 0),
]


def _attribution() -> dict:
    """Автор, лицензия и первоисточник по каждому файлу из static/img/dishes."""
    path = DISH_IMAGES_DIR / "attribution.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("Не удалось прочитать attribution.json: %s", exc)
        return {}


async def backfill_dish_details(session: AsyncSession) -> dict:
    """Дозаполняет состав, аллергены и фото у уже существующих блюд.

    Ничего не перезаписывает: трогаем только пустые поля, поэтому ручные
    правки администратора в админ-панели остаются на месте.
    """
    attribution = _attribution()
    dishes = (await session.scalars(select(Dish))).all()

    filled_details = 0
    filled_images = 0
    for dish in dishes:
        changed = False

        details = DISH_DETAILS.get(dish.name)
        if details:
            if not dish.ingredients and details["ingredients"]:
                dish.ingredients = list(details["ingredients"])
                changed = True
            if not dish.allergens and details["allergens"]:
                dish.allergens = list(details["allergens"])
                changed = True
        if changed:
            filled_details += 1

        # фотографии лежат в репозитории — привязываем их к свежей базе
        if not dish.image_url:
            slug = slugify(dish.name, fallback=f"dish-{dish.id}")
            if (DISH_IMAGES_DIR / f"{slug}.webp").exists():
                meta = attribution.get(slug, {})
                dish.image_url = f"/static/img/dishes/{slug}.webp"
                dish.image_thumb_url = f"/static/img/dishes/{slug}-thumb.webp"
                dish.image_placeholder = meta.get("placeholder", "") or dish.image_placeholder
                dish.image_author = meta.get("author", "")
                dish.image_license = meta.get("license", "")
                dish.image_source_url = meta.get("source_url", "")
                filled_images += 1

    if filled_details or filled_images:
        await session.commit()
    return {"details": filled_details, "images": filled_images}


async def rename_legacy_brand(session: AsyncSession) -> None:
    """Подписи из времён BioEat в уже развёрнутой базе меняем на РосПит.

    Трогаем только то, что seed сам когда-то создал, — ручные правки не задеваем.
    """
    admin = await session.scalar(
        select(User).where(User.full_name == "Администратор BioEat")
    )
    if admin is not None:
        admin.full_name = "Администратор РосПит"
        await session.commit()


async def seed(session: AsyncSession, force: bool = False) -> dict:
    await rename_legacy_brand(session)
    # постамат появился позже меню — заводим его и в уже наполненной базе
    await seed_lockers(session)
    await refresh_locker_points(session)
    existing = await session.scalar(select(func.count()).select_from(Category))
    if existing and not force:
        # меню уже есть, но новые поля могли появиться вместе с обновлением
        return {"skipped": True, "reason": "База уже наполнена", **await backfill_dish_details(session)}

    cats: dict[str, Category] = {}
    for slug, name, icon, color, sort in CATEGORIES:
        cat = await session.scalar(select(Category).where(Category.slug == slug))
        if cat is None:
            cat = Category(slug=slug, name=name, icon=icon, color=color, sort_order=sort)
            session.add(cat)
        cats[slug] = cat
    await session.flush()

    dishes_created = 0
    for slug, rows in DISHES.items():
        cat = cats[slug]
        for i, row in enumerate(rows):
            name, price, weight, kcal, p, f, c, icon, tags, stock, desc = row
            exists = await session.scalar(
                select(Dish).where(Dish.name == name, Dish.category_id == cat.id)
            )
            if exists:
                continue
            session.add(
                Dish(
                    category_id=cat.id,
                    name=name,
                    description=desc,
                    price=price,
                    weight_g=weight,
                    kcal=kcal,
                    protein=p,
                    fat=f,
                    carbs=c,
                    icon=icon,
                    tags=tags,
                    ingredients=list(DISH_DETAILS.get(name, {}).get("ingredients", [])),
                    allergens=list(DISH_DETAILS.get(name, {}).get("allergens", [])),
                    stock_qty=stock,
                    sort_order=i * 10,
                )
            )
            dishes_created += 1

    for label, start, end, cap, point, sort in SLOTS:
        exists = await session.scalar(select(PickupSlot).where(PickupSlot.label == label))
        if exists:
            continue
        session.add(
            PickupSlot(
                label=label,
                starts_at=start,
                ends_at=end,
                capacity=cap,
                order_cutoff_minutes=settings.default_order_cutoff_minutes,
                point=point,
                sort_order=sort,
            )
        )

    for email, password, name, role, group, bonus in USERS:
        exists = await session.scalar(select(User).where(User.email == email))
        if exists:
            continue
        session.add(
            User(
                email=email,
                password_hash=hash_password(password),
                full_name=name,
                role=role,
                group_name=group,
                bonus_balance=bonus,
            )
        )

    await session.commit()
    return {"skipped": False, "dishes": dishes_created, **await backfill_dish_details(session)}


async def main() -> None:
    await create_all()
    await ensure_columns()
    async with SessionLocal() as session:
        result = await seed(session)
    print("Seed:", result)
    await engine.dispose()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
