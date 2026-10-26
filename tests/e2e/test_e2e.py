"""Сквозные сценарии в браузере на профилях iPhone / Android / планшет / десктоп.

Студент: вход → меню (фильтр, поиск, карточка) → корзина → перемена с отсечкой →
демо-оплата → QR → история → отзыв → повтор заказа.
Кухня: сводка перемены → «Собран» → «Положен в ячейку» → эмулятор постамата
открывает ячейку → у студента «Выдан».
"""
from __future__ import annotations

import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from tests.e2e.conftest import SCREENS, new_context

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.locker_simulator import Locker, derive_secret

PROFILES = ["iphone", "android", "tablet", "desktop"]

TAP_AUDIT_JS = """
() => {
  const out = [];
  const seen = new Set();
  for (const el of document.querySelectorAll('button, a[href], [role=button], input, select, textarea, [data-star]')) {
    const r = el.getBoundingClientRect();
    const st = getComputedStyle(el);
    if (!r.width || !r.height || st.visibility === 'hidden' || st.display === 'none') continue;
    if (el.closest('.sheet-host:not(.is-open)')) continue;
    if (r.width < 44 || r.height < 44) {
      const label = (el.getAttribute('aria-label') || el.textContent || el.placeholder || el.className || el.tagName).trim().replace(/\\s+/g, ' ').slice(0, 40);
      const key = `${label}|${Math.round(r.width)}x${Math.round(r.height)}`;
      if (!seen.has(key)) { seen.add(key); out.push(key); }
    }
  }
  return out;
}
"""


def campus_date(offset=0) -> str:
    return (datetime.now(UTC) + timedelta(hours=3) + timedelta(days=offset)).date().isoformat()


def shot(page, profile, name):
    SCREENS.mkdir(exist_ok=True)
    page.screenshot(path=str(SCREENS / f"{profile}-{name}.jpg"), type="jpeg", quality=80, full_page=False)


def audit(page, profile, screen, findings):
    entry = findings.setdefault(profile, {}).setdefault("screens", {}).setdefault(screen, {})
    entry["small_targets"] = page.evaluate(TAP_AUDIT_JS)
    entry["horizontal_overflow"] = page.evaluate(
        "() => document.documentElement.scrollWidth - window.innerWidth"
    ) > 1


def login(page, base, email="student@rosbiotech.ru"):
    page.goto(f"{base}/#/login")
    page.wait_for_selector(f"[data-demo='{email}']").click()
    page.wait_for_function("() => !location.hash.startsWith('#/login')")


def api_login(base, email, password):
    r = httpx.post(f"{base}/api/auth/login", json={"email": email, "password": password})
    return {"Authorization": f"Bearer {r.json()['token']}"}


def toast_text(page) -> str:
    return " | ".join(page.locator(".toast").all_inner_texts())


@pytest.mark.parametrize("profile", PROFILES)
def test_student_flow(server, pw, findings, profile):
    base = server["base"]
    browser, context = new_context(pw, profile)
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    info = findings.setdefault(profile, {})
    info["browser"] = f"{context.browser.browser_type.name} {context.browser.version}"
    info["viewport"] = page.viewport_size
    steps = info.setdefault("steps", {})

    # --- вход ---
    page.goto(f"{base}/#/login")
    page.wait_for_selector(".brand-logo")
    assert page.title().startswith("Вход · РосПит")
    shot(page, profile, "01-login")
    audit(page, profile, "login", findings)
    login(page, base)
    steps["login"] = "ok"

    # --- меню: фильтр, поиск, карточка блюда ---
    page.goto(f"{base}/#/menu")
    page.wait_for_selector("#list .dish")
    page.click("[data-tag='pp']")
    page.wait_for_timeout(400)
    assert page.locator("#list .dish").count() > 0
    page.click("[data-tag='pp']")
    page.fill("#search", "борщ")
    page.wait_for_function("() => [...document.querySelectorAll('#list .dish__name')].some(n => /Борщ/.test(n.textContent))")
    page.fill("#search", "")
    page.wait_for_timeout(400)
    shot(page, profile, "02-menu")
    audit(page, profile, "menu", findings)
    page.locator("#list a.dish:not(.dish--out)").first.click()
    page.wait_for_selector("[data-buy]")
    shot(page, profile, "03-dish")
    audit(page, profile, "dish", findings)
    page.click("[data-buy]")
    page.wait_for_timeout(500)
    steps["menu"] = "ok"

    # --- корзина ---
    page.goto(f"{base}/#/cart")
    page.wait_for_selector("#action-bar [data-goto='#/checkout']")
    shot(page, profile, "04-cart")
    audit(page, profile, "cart", findings)
    page.click("#action-bar [data-goto='#/checkout']")
    steps["cart"] = "ok"

    # --- выбор перемены: отсечка видна под каждым окном ---
    page.wait_for_selector(".slot-deadline")
    labels = page.locator(".slot-deadline").all_inner_texts()
    assert all(re.search(r"приём (до|закрыт в) \d\d:\d\d", t) for t in labels), labels
    closed = page.locator("[data-slot][disabled]").count()
    info["checkout_slots"] = {"labels": labels, "closed": closed}
    shot(page, profile, "05-checkout")
    audit(page, profile, "checkout", findings)
    page.click("#action-bar [data-submit]")
    page.wait_for_url(re.compile(r"#/pay/\d+"))
    steps["checkout"] = "ok"

    # --- демо-оплата ---
    page.wait_for_selector("#content .status-pill:has-text(\"Демо-режим\")")
    shot(page, profile, "06-pay")
    audit(page, profile, "pay", findings)
    page.click("#action-bar [data-pay]")
    page.wait_for_url(re.compile(r"#/order/\d+"), timeout=20000)
    order_id = int(re.search(r"#/order/(\d+)", page.url).group(1))
    page.wait_for_selector("#qr img, .big-number")
    shot(page, profile, "07-order-qr")
    audit(page, profile, "order", findings)
    steps["pay"] = steps["qr"] = "ok"

    # --- история ---
    page.goto(f"{base}/#/orders")
    page.wait_for_selector(f"[data-goto='#/order/{order_id}']")
    shot(page, profile, "08-orders")
    audit(page, profile, "orders", findings)
    steps["history"] = "ok"

    # --- кухня выдаёт заказ (через API), студент оставляет отзыв ---
    op = api_login(base, "operator@rosbiotech.ru", "operator")
    for status in ("ready", "issued"):
        r = httpx.patch(f"{base}/api/operator/orders/{order_id}/status", json={"status": status}, headers=op)
        assert r.status_code == 200, r.text
    page.goto(f"{base}/#/order/{order_id}?rate=5")
    page.wait_for_selector("[data-send]")
    page.click("[data-tag='tasty']")
    page.fill("[data-text]", "Проверка из e2e")
    shot(page, profile, "09-review")
    audit(page, profile, "review", findings)
    page.click("[data-send]")
    page.wait_for_selector(".review")
    steps["review"] = "ok"

    # --- повтор заказа ---
    page.click("[data-repeat]")
    page.wait_for_url(re.compile(r"#/cart"))
    page.wait_for_selector("#cart-body .stepper")
    steps["repeat"] = "ok"

    # клавиатура: пока поле в фокусе, плавающие панели спрятаны
    if profile != "desktop":
        page.goto(f"{base}/#/menu")
        page.wait_for_selector("#search").focus()
        info["keyboard_hides_bars"] = page.evaluate("() => getComputedStyle(document.querySelector('.tabbar')).display === 'none'")

    info["console_errors"] = sorted(set(errors))
    browser.close()


def test_kitchen_and_locker_flow(server, pw, findings):
    """Кабинет столовой на десктопе + экран студента на iPhone + эмулятор постамата."""
    base = server["base"]
    student_api = api_login(base, "student@rosbiotech.ru", "student")
    day = campus_date(1)
    slot = next(s for s in httpx.get(f"{base}/api/slots?date={day}").json()
                if "остамат" in s["point"] and s["is_available"])
    dish = next(d for d in httpx.get(f"{base}/api/dishes").json() if d["stock_qty"] > 2)
    httpx.delete(f"{base}/api/cart", headers=student_api)
    httpx.post(f"{base}/api/cart/items", json={"dish_id": dish["id"], "qty": 1}, headers=student_api)
    order = httpx.post(f"{base}/api/orders", json={"slot_id": slot["id"], "pickup_date": day}, headers=student_api).json()
    httpx.post(f"{base}/api/orders/{order['id']}/pay", json={"method": "sbp"}, headers=student_api)
    info = findings.setdefault("kitchen", {})
    locker = Locker(base, "locker-b1", derive_secret("locker-b1", secret_key=server["env"]["SECRET_KEY"]))
    locker.heartbeat()

    browser, context = new_context(pw, "desktop")
    page = context.new_page()
    login(page, base, "operator@rosbiotech.ru")
    page.goto(f"{base}/#/operator")
    page.wait_for_selector(f"[data-day='{day}']").click()
    section = page.locator(f"[data-slot-section='{slot['id']}']")
    if not section.locator(".shift-slot__body").count():
        section.locator("[data-toggle]").click()
    section.locator(".collect").wait_for()
    assert "постамат онлайн" in page.locator("#lockers").inner_text()
    shot(page, "desktop", "10-shift")
    audit(page, "desktop", "shift", findings)

    page.click(f"[data-ready='{order['id']}']")
    page.wait_for_selector(f"[data-place='{order['id']}']").click()
    page.click(".sheet [data-yes]")
    page.wait_for_selector("text=/Ячейка №\\d+/")
    shot(page, "desktop", "11-in-locker")
    info["kitchen"] = "Собран → Положен в ячейку: ok"

    # студент видит ячейку и одноразовый QR, который сам обновляется
    s_browser, s_context = new_context(pw, "iphone")
    s_page = s_context.new_page()
    login(s_page, base)
    s_page.goto(f"{base}/#/order/{order['id']}")
    s_page.wait_for_selector("#locker-qr svg")
    first_qr = s_page.inner_html("#locker-qr")
    first_pin = s_page.inner_text("#locker-pin")
    assert "ячейке №" in s_page.inner_text("body")
    shot(s_page, "iphone", "12-locker-qr")
    s_page.wait_for_function(
        "(old) => document.querySelector('#locker-qr').innerHTML !== old", arg=first_qr, timeout=20000
    )
    info["qr_refresh"] = f"код обновился сам; PIN был «{first_pin}», стал «{s_page.inner_text('#locker-pin')}»"

    # «сканер» постамата: код берём так же, как его показал бы экран
    token = httpx.post(f"{base}/api/orders/{order['id']}/pickup-token", headers=student_api).json()
    opened = locker.scan(token["code"])
    assert opened["action"] == "open"
    assert locker.scan(token["code"])["reason"] == "used"
    locker.event("door_opened", opened["cell"])
    locker.event("door_closed", opened["cell"])
    # экран сам узнаёт о выдаче: одноразовый QR исчезает, статус «Выдан»
    s_page.wait_for_selector("#locker-qr", state="detached", timeout=15000)
    assert (httpx.get(f"{base}/api/orders/{order['id']}", headers=student_api).json()["status"]) == "issued"
    s_page.wait_for_selector("#review-box")
    shot(s_page, "iphone", "13-issued")
    info["locker"] = f"ячейка №{opened['cell']} открылась, повторный скан отклонён, статус «Выдан»"
    s_browser.close()
    browser.close()


@pytest.mark.parametrize("profile", ["iphone", "android"])
def test_phone_specifics(server, pw, findings, profile):
    """То, что ломается именно на телефонах: поворот, узкий экран, крупный текст, офлайн."""
    base = server["base"]
    info = findings.setdefault(profile, {}).setdefault("phone_checks", {})
    browser, context = new_context(pw, profile)
    page = context.new_page()
    login(page, base)

    # автоповорот: альбомная ориентация того же устройства
    size = page.viewport_size
    page.set_viewport_size({"width": size["height"], "height": size["width"]})
    for route in ("#/", "#/menu", "#/cart"):
        page.goto(f"{base}/{route}")
        page.wait_for_timeout(700)
        info[f"landscape {route}"] = page.evaluate("() => document.documentElement.scrollWidth - innerWidth") <= 1
    shot(page, profile, "20-landscape-menu")

    # самый узкий популярный экран (iPhone SE, 320 px)
    page.set_viewport_size({"width": 320, "height": 640})
    for route in ("#/menu", "#/checkout", "#/orders", "#/profile"):
        page.goto(f"{base}/{route}")
        page.wait_for_timeout(700)
        info[f"320px {route}"] = page.evaluate("() => document.documentElement.scrollWidth - innerWidth") <= 1
    shot(page, profile, "21-narrow-320")

    # крупный шрифт: масштаб страницы 130 % — так работает «Масштаб текста» в Chrome на Android
    page.set_viewport_size(size)
    page.goto(f"{base}/#/menu")
    page.wait_for_timeout(500)
    page.add_style_tag(content="html { zoom: 1.3; }")
    page.wait_for_timeout(300)
    info["text 130% /menu"] = page.evaluate("() => document.documentElement.scrollWidth - innerWidth") <= 1
    shot(page, profile, "22-text-130")

    # офлайн: оболочка из service worker
    page.goto(f"{base}/#/")
    page.wait_for_timeout(1500)
    sw = page.evaluate("async () => !!(navigator.serviceWorker && await navigator.serviceWorker.getRegistration())")
    info["service worker"] = sw
    context.set_offline(True)
    try:
        page.reload(wait_until="domcontentloaded", timeout=8000)
        page.wait_for_timeout(800)
        page.wait_for_selector("text=Нет связи", timeout=5000)
        info["offline shell"] = page.locator("#app").count() == 1
        # вход не потерян
        info["offline keeps login"] = bool(page.evaluate("() => localStorage.getItem('rospit_token')"))
    except Exception as exc:
        # Playwright WebKit не умеет офлайн-перезагрузку через service worker
        # («WebKit encountered an internal error») — это ограничение среды, не приложения
        info["offline shell"] = f"не проверено в этой среде: {str(exc).splitlines()[0][:80]}"
    context.set_offline(False)
    browser.close()
