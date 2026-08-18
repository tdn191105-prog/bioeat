"""Поисковые запросы для фотографий блюд.

Ключ — название блюда из меню, значение — запросы по убыванию точности.
Английский вариант обязателен: и Openverse, и Wikimedia Commons размечены
преимущественно по-английски, по русскому запросу выдача почти пустая.

Запросы описывают, что должно быть на снимке, а не переводят название буквально:
«Ватрушка с творогом» ищется как `vatrushka cottage cheese pastry`,
«Морс клюквенный» — как `cranberry drink mors`.
"""
from __future__ import annotations

IMAGE_QUERIES: dict[str, list[str]] = {
    # ------------------------------- Комбо-обеды ---------------------------- #
    "Комплексный обед «Студенческий»": [
        "cafeteria lunch tray meal",
        "canteen set meal soup main course",
        "комплексный обед поднос",
    ],
    "Комбо «Лёгкий ПП»": [
        "healthy lunch bowl chicken vegetables",
        "chicken salad bowl healthy",
        "здоровый обед курица булгур",
    ],
    "Комбо «Вегетарианское»": [
        "vegetarian lunch soup vegetables salad",
        "vegetarian meal plate pumpkin soup greek salad",
        "вегетарианский обед",
    ],
    "Комбо «Завтрак»": [
        "breakfast omelette cheese coffee",
        "breakfast plate omelet syrniki coffee",
        "завтрак омлет кофе",
    ],

    # ---------------------------------- Супы -------------------------------- #
    "Борщ с говядиной": [
        "borscht beef sour cream",
        "borshch russian beet soup",
        "борщ со сметаной",
    ],
    "Щи из свежей капусты": [
        "shchi cabbage soup",
        "russian cabbage soup bowl",
        "щи капустные",
    ],
    "Куриный суп с лапшой": [
        "chicken noodle soup bowl",
        "homemade chicken soup noodles",
        "куриный суп с лапшой",
    ],
    "Солянка мясная": [
        "solyanka soup",
        "selyanka soup meat",
        "солянка суп",
    ],
    "Крем-суп из тыквы": [
        "pumpkin soup",
        "squash soup bowl food",
        "тыквенный суп",
    ],
    "Гороховый суп с копчёностями": [
        "pea soup smoked meat croutons",
        "split pea soup bowl",
        "гороховый суп",
    ],

    # -------------------------------- Горячее ------------------------------- #
    "Котлета по-киевски": [
        "chicken kiev",
        "chicken cordon bleu breaded fillet plate",
        "котлета по-киевски",
    ],
    "Куриная грудка гриль": [
        "grilled chicken breast rosemary lemon",
        "grilled chicken fillet plate",
        "куриная грудка гриль",
    ],
    "Плов с бараниной": [
        "plov lamb rice pilaf",
        "uzbek pilaf plov carrot rice",
        "плов с бараниной",
    ],
    "Бефстроганов": [
        "beef stroganoff",
        "beef stroganoff mushroom cream sauce",
        "бефстроганов",
    ],
    "Треска запечённая": [
        "baked cod fillet lemon herbs",
        "oven baked cod fish plate",
        "треска запечённая",
    ],
    "Тефтели в томатном соусе": [
        "meatballs tomato sauce",
        "tefteli meatballs in tomato gravy",
        "тефтели в томатном соусе",
    ],
    "Котлета рубленая куриная": [
        "chicken patty cutlet plate",
        "minced chicken cutlet kotleta",
        "куриная котлета рубленая",
    ],
    "Овощное рагу": [
        "vegetable stew",
        "stewed vegetables zucchini pepper tomato",
        "овощное рагу",
    ],
    "Паста карбонара": [
        "spaghetti carbonara",
        "pasta carbonara bacon parmesan",
        "паста карбонара",
    ],

    # -------------------------------- Гарниры ------------------------------- #
    "Картофельное пюре": [
        "mashed potatoes food",
        "potato puree dish",
        "картофельное пюре",
    ],
    "Гречка отварная": [
        "buckwheat porridge",
        "grechnevaya kasha buckwheat cooked",
        "гречневая каша",
    ],
    "Рис припущенный": [
        "boiled rice food",
        "steamed rice dish",
        "отварной рис",
    ],
    "Булгур с овощами": [
        "bulgur salad tabbouleh",
        "cooked bulgur wheat bowl",
        "булгур крупа",
    ],
    "Макароны отварные": [
        "boiled pasta butter side dish",
        "cooked macaroni plain plate",
        "макароны отварные",
    ],
    "Овощи гриль": [
        "grilled vegetables zucchini eggplant pepper",
        "grilled vegetable platter",
        "овощи на гриле",
    ],
    "Картофель по-деревенски": [
        "potato wedges baked",
        "rustic roasted potato wedges paprika",
        "картофель по-деревенски",
    ],

    # --------------------------------- Салаты ------------------------------- #
    "Салат «Цезарь» с курицей": [
        "caesar salad chicken parmesan croutons",
        "chicken caesar salad bowl",
        "салат цезарь с курицей",
    ],
    "Винегрет": [
        "vinaigrette salad beetroot",
        "diced beetroot salad bowl",
        "винегрет",
    ],
    "Салат «Оливье»": [
        "olivier salad",
        "russian potato salad bowl",
        "салат оливье",
    ],
    "Греческий салат": [
        "greek salad feta olives",
        "greek salad tomato cucumber feta",
        "греческий салат",
    ],
    "Витаминный салат": [
        "cabbage carrot apple salad",
        "fresh cabbage salad shredded",
        "витаминный салат капуста морковь",
    ],
    "Морковь по-корейски": [
        "korean carrot salad morkovcha",
        "spicy korean style carrot salad",
        "морковь по-корейски",
    ],

    # -------------------------------- Выпечка ------------------------------- #
    "Пирожок с капустой": [
        "pirozhki",
        "russian pie cabbage baked bun",
        "пирожок с капустой",
    ],
    "Сосиска в тесте": [
        "sausage roll food",
        "hot dog pastry baked",
        "сосиска в тесте",
    ],
    "Слойка с творогом": [
        "cheese danish",
        "quark pastry bun",
        "слойка",
    ],
    "Круассан классический": [
        "croissant",
        "croissants basket bakery",
        "круассан",
    ],
    "Ватрушка с творогом": [
        "vatrushka cottage cheese pastry",
        "vatrushka russian curd bun",
        "ватрушка с творогом",
    ],
    "Пицца «Пепперони», кусок": [
        "pepperoni pizza slice",
        "pizza pepperoni mozzarella slice",
        "пицца пепперони кусок",
    ],
    "Хлеб ржаной": [
        "rye bread slice",
        "dark rye bread loaf sliced",
        "ржаной хлеб",
    ],

    # -------------------------------- Напитки ------------------------------- #
    "Кофе американо": [
        "americano coffee cup black",
        "black coffee cup espresso americano",
        "кофе американо",
    ],
    "Капучино": [
        "cappuccino cup latte art",
        "cappuccino coffee milk foam",
        "капучино",
    ],
    "Латте": [
        "caffe latte cup coffee",
        "latte macchiato glass",
        "латте",
    ],
    "Чай чёрный / зелёный": [
        "tea cup teapot black green",
        "hot tea in glass cup",
        "чай в чашке",
    ],
    "Компот из сухофруктов": [
        "kompot dried fruit drink",
        "compote dried fruits glass jug",
        "компот из сухофруктов",
    ],
    "Морс клюквенный": [
        "cranberry drink mors",
        "cranberry juice glass red berry drink",
        "морс клюквенный",
    ],
    "Вода питьевая 0,5 л": [
        "bottled drinking water plastic bottle",
        "still water bottle glass",
        "бутылка питьевой воды",
    ],
    "Какао": [
        "hot chocolate drink",
        "cocoa beverage cup",
        "какао напиток",
    ],

    # -------------------------------- Десерты ------------------------------- #
    "Сырники со сметаной": [
        "syrniki cottage cheese pancakes sour cream",
        "syrniki russian curd fritters",
        "сырники со сметаной",
    ],
    "Блины с джемом": [
        "pancakes with jam plate",
        "crepes with berry jam",
        "блины с вареньем",
    ],
    "Шарлотка яблочная": [
        "sharlotka apple cake russian",
        "apple sponge cake charlotte",
        "шарлотка яблочная",
    ],
    "Овсяное печенье": [
        "oatmeal cookies",
        "oat cookies stack biscuit",
        "овсяное печенье",
    ],
    "Йогурт натуральный": [
        "yogurt food",
        "yoghurt bowl dairy",
        "йогурт",
    ],
}
