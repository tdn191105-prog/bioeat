"""Общая настройка тестов.

Приложение импортируется один раз на весь прогон, поэтому база задаётся здесь,
до первого импорта `app`, — иначе её выбирал бы тот модуль, что соберётся первым.
"""
from __future__ import annotations

import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TEST_DB = ROOT / "test_rospit.db"
if TEST_DB.exists():
    TEST_DB.unlink()
# TEST_DATABASE_URL — прогнать те же тесты на PostgreSQL (база должна быть пустой):
#   TEST_DATABASE_URL=postgresql+asyncpg://bioeat:bioeat@localhost:5433/rospit_test pytest
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite+aiosqlite:///{TEST_DB}"
os.environ["SECRET_KEY"] = "test-secret"
os.environ["PAYMENT_PROVIDER"] = "demo"


def pytest_sessionfinish(session, exitstatus):
    if TEST_DB.exists():
        TEST_DB.unlink()
