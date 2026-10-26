"""E2E: настоящий сервер в отдельном процессе + браузеры Playwright.

Запуск:   E2E=1 pytest tests/e2e            (нужны: python -m playwright install chromium webkit)
Без E2E=1 сценарии пропускаются — обычный `pytest` остаётся быстрым.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
SCREENS = Path(__file__).resolve().parent / "screens"
RESULTS = Path(__file__).resolve().parent / "results.json"

# Профили устройств. Важно: «iPhone» здесь — движок WebKit от Playwright с профилем
# iPhone, а не настоящий Safari на iOS; Android — Chromium с профилем Pixel 7.
DEVICES = {
    "iphone": {"browser": "webkit", "device": "iPhone 14"},
    "android": {"browser": "chromium", "device": "Pixel 7"},
    "tablet": {"browser": "webkit", "device": "iPad (gen 7)"},
    "desktop": {"browser": "chromium", "viewport": {"width": 1280, "height": 800}},
}


def pytest_collection_modifyitems(config, items):
    if os.environ.get("E2E") == "1":
        return
    skip = pytest.mark.skip(reason="e2e выключены: запустите E2E=1 pytest tests/e2e")
    for item in items:
        if "tests/e2e" in str(item.fspath):
            item.add_marker(skip)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def server(tmp_path_factory):
    if os.environ.get("E2E") != "1":
        pytest.skip("e2e выключены")
    db = tmp_path_factory.mktemp("e2e") / "e2e.db"
    port = _free_port()
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite+aiosqlite:///{db}",
        "SECRET_KEY": "dev-secret-change-me-in-production",   # эмулятор постамата выводит секрет из него
        "PAYMENT_PROVIDER": "demo",
        # короткий срок жизни кода постамата — проверяем, что экран сам берёт новый
        "PICKUP_TOKEN_TTL_SECONDS": "20",
    }
    subprocess.run([sys.executable, "-m", "app.demo_data"], cwd=ROOT, env=env, check=True,
                   capture_output=True)
    log = open(tmp_path_factory.mktemp("log") / "server.log", "w")  # noqa: SIM115
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)],
        cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{port}"
    for _ in range(60):
        try:
            if httpx.get(f"{base}/api/health", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.25)
    else:
        proc.kill()
        raise RuntimeError("сервер e2e не поднялся")
    yield {"base": base, "env": env}
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture(scope="session")
def pw():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        yield p


@pytest.fixture(scope="session")
def findings():
    """Находки всех прогонов — из них собирается docs/test_report.md."""
    data: dict = {}
    yield data
    RESULTS.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def new_context(pw, profile: str, **extra):
    spec = DEVICES[profile]
    browser = getattr(pw, spec["browser"]).launch()
    opts = dict(pw.devices[spec["device"]]) if "device" in spec else {"viewport": spec["viewport"]}
    opts.update(locale="ru-RU", timezone_id="Europe/Moscow", **extra)
    context = browser.new_context(**opts)
    context.set_default_timeout(15000)
    return browser, context
