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
    # Платёжный провайдер: demo | yookassa | cloudpayments | bank.
    # Пусто — решает старый флаг DEMO_PAYMENTS (true → demo, false → yookassa).
    payment_provider: str = ""
    # Демо-режим: платежи не уходят в реальные системы (синоним PAYMENT_PROVIDER=demo)
    demo_payments: bool = True
    # ЮKassa: секреты только из окружения
    yookassa_shop_id: str = ""
    yookassa_secret_key: str = ""
    yookassa_api_url: str = "https://api.yookassa.ru/v3"
    # проверять, что вебхук пришёл с адресов ЮKassa (за прокси нужен --proxy-headers)
    yookassa_check_ip: bool = True
    # Публичный адрес приложения — сюда банк вернёт студента после оплаты
    public_base_url: str = ""
    # Чек 54-ФЗ через провайдера: ставка НДС (код ЮKassa: 1 — без НДС, 11 — 22 %),
    # признак предмета расчёта. Значения подтверждает бухгалтерия столовой.
    receipt_enabled: bool = True
    receipt_vat_code: int = 1
    receipt_payment_subject: str = "commodity"
    receipt_tax_system_code: int | None = None
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
    # production: отказываемся стартовать с секретом по умолчанию и CORS «*»
    environment: str = "development"
    # cookie сессии только по HTTPS — включается на боевом домене
    cookie_secure: bool = False

    @property
    def active_payment_provider(self) -> str:
        if self.payment_provider:
            return self.payment_provider.strip().lower()
        return "demo" if self.demo_payments else "yookassa"

    @property
    def is_demo_payments(self) -> bool:
        return self.active_payment_provider == "demo"

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in ("production", "prod")

    def production_problems(self) -> list[str]:
        """Что не так с настройками для боевого запуска."""
        problems = []
        if self.secret_key in ("dev-secret-change-me-in-production", "change-me-to-a-long-random-string") \
                or len(self.secret_key) < 32:
            problems.append("SECRET_KEY по умолчанию или короче 32 символов")
        if self.cors_origins.strip() == "*":
            problems.append("CORS_ORIGINS=* — укажите адрес сайта")
        if not self.cookie_secure:
            problems.append("COOKIE_SECURE=false — cookie сессии уйдёт и по HTTP")
        if not self.public_base_url.startswith("https://"):
            problems.append("PUBLIC_BASE_URL не https:// — банк не вернёт студента и не пришлёт вебхук")
        return problems

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
