"""Подключение к базе данных."""
import logging
from collections.abc import AsyncGenerator

from sqlalchemy import JSON, Boolean, DateTime, Integer, Numeric, inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import settings
from .models import Base

log = logging.getLogger("rospit")

engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session


async def create_all() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


# --------------------------------------------------------------------------- #
#  Упрощённая автомиграция
#
#  create_all() создаёт только отсутствующие таблицы и не трогает уже
#  существующие, поэтому новые колонки моделей в развёрнутой базе не появятся.
#  Для MVP добавляем их вручную через ALTER TABLE. Это осознанное упрощение:
#  для боевого запуска нужен Alembic (переименования, изменения типов,
#  откаты и порядок применения здесь не поддерживаются).
# --------------------------------------------------------------------------- #
def _column_sql_type(column) -> str:
    """Тип колонки в синтаксисе, понятном и SQLite, и PostgreSQL."""
    type_ = column.type
    if isinstance(type_, JSON):
        # SQLite хранит JSON как TEXT, PostgreSQL умеет родной JSON
        return "TEXT" if settings.is_sqlite else "JSON"
    if isinstance(type_, Boolean):
        return "BOOLEAN"
    if isinstance(type_, Integer):
        return "INTEGER"
    if isinstance(type_, Numeric) and not isinstance(type_, Integer):
        precision = type_.precision or 10
        scale = type_.scale or 2
        return f"NUMERIC({precision}, {scale})"
    if isinstance(type_, DateTime):
        return "TIMESTAMP"
    try:
        return type_.compile(dialect=engine.dialect)
    except Exception:
        return "TEXT"


def _column_default_sql(column) -> str | None:
    """Значение по умолчанию для уже существующих строк."""
    default = column.default
    if default is None:
        return "NULL" if column.nullable else None
    if getattr(default, "is_callable", False):
        produced = default.arg(None)
    elif getattr(default, "is_scalar", False):
        produced = default.arg
    else:
        return None
    if isinstance(produced, (list, dict)):
        return "'[]'" if isinstance(produced, list) else "'{}'"
    if isinstance(produced, bool):
        return "TRUE" if produced else "FALSE"
    if isinstance(produced, (int, float)):
        return str(produced)
    if isinstance(produced, str):
        escaped = produced.replace("'", "''")
        return f"'{escaped}'"
    return None


def _missing_columns(sync_conn) -> list[tuple[str, str, str]]:
    """(таблица, колонка, SQL-фрагмент) для колонок, которых нет в базе."""
    inspector = inspect(sync_conn)
    present_tables = set(inspector.get_table_names())
    plan: list[tuple[str, str, str]] = []

    for table in Base.metadata.sorted_tables:
        if table.name not in present_tables:
            continue  # таблицу целиком создаст create_all
        existing = {c["name"] for c in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in existing or column.primary_key:
                continue
            sql_type = _column_sql_type(column)
            default_sql = _column_default_sql(column)
            fragment = f'ADD COLUMN "{column.name}" {sql_type}'
            if default_sql is not None:
                fragment += f" DEFAULT {default_sql}"
            plan.append((table.name, column.name, fragment))
    return plan


async def ensure_columns() -> list[str]:
    """Добавляет в существующие таблицы колонки, появившиеся в моделях.

    Возвращает список добавленных колонок в виде «таблица.колонка».
    Любая ошибка не роняет приложение — пишем предупреждение и работаем дальше.
    """
    added: list[str] = []
    try:
        async with engine.begin() as conn:
            plan = await conn.run_sync(_missing_columns)
            for table_name, column_name, fragment in plan:
                try:
                    await conn.execute(text(f'ALTER TABLE "{table_name}" {fragment}'))
                    added.append(f"{table_name}.{column_name}")
                    log.info("Автомиграция: добавлена колонка %s.%s", table_name, column_name)
                except Exception as exc:
                    log.warning(
                        "Автомиграция: не удалось добавить колонку %s.%s (%s). "
                        "Добавьте её вручную или примените миграцию.",
                        table_name,
                        column_name,
                        exc,
                    )
    except Exception as exc:
        log.warning(
            "Автомиграция пропущена: не удалось прочитать схему базы (%s). "
            "Приложение продолжит работу на текущей схеме.",
            exc,
        )
    return added
