"""Конфигурация приложения РосПит."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "rospit"
    # Полный DSN базы. По умолчанию — Postgres из docker-compose.
    database_url: str = "postgresql+asyncpg://bioeat:bioeat@db:5432/bioeat"
    secret_key: str = "dev-secret-change-me-in-production"
    access_token_ttl_minutes: int = 60 * 24 * 14  # 2 недели
    # Часовой пояс кампуса (Москва)
    tz_offset_hours: int = 3
    # Комиссия/бонусы
    loyalty_percent: int = 5  # % кэшбэка бонусами
    # Демо-режим: платежи не уходят в реальные системы
    demo_payments: bool = True
    # За сколько минут до начала перемены закрывается приём заказов (значение
    # для новых окон; у каждого окна своё поле order_cutoff_minutes)
    default_order_cutoff_minutes: int = 60
    # Сколько живёт неоплаченный заказ: потом он отменяется, порции возвращаются
    unpaid_order_ttl_minutes: int = 15
    # Как часто фоновая задача ищет просроченные неоплаченные заказы, секунд
    expire_sweep_seconds: int = 60
    # Постамат: срок жизни одноразового QR/PIN, «онлайн» по heartbeat,
    # допустимое расхождение часов устройства и лимит неверных PIN
    pickup_token_ttl_seconds: int = 120
    locker_online_seconds: int = 90
    device_clock_skew_seconds: int = 30
    pin_attempts_per_5min: int = 5
    cors_origins: str = "*"

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
