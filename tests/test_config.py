"""Настройки боевого запуска: с секретом по умолчанию и CORS «*» приложение не стартует."""
from app.config import Settings


def test_production_rejects_unsafe_defaults():
    problems = Settings(environment="production").production_problems()
    assert any("SECRET_KEY" in p for p in problems)
    assert any("CORS" in p for p in problems)
    assert any("COOKIE_SECURE" in p for p in problems)
    assert any("PUBLIC_BASE_URL" in p for p in problems)


def test_production_accepts_proper_settings():
    good = Settings(
        environment="production",
        secret_key="x" * 64,
        cors_origins="https://rospit.example.ru",
        cookie_secure=True,
        public_base_url="https://rospit.example.ru",
    )
    assert good.is_production
    assert good.production_problems() == []
