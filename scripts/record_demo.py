"""Запись демо-ролика РосПит для презентации (30–45 с, профиль iPhone).

    python scripts/record_demo.py            # → media/rospit_demo.mp4 и media/rospit_demo_cover.png

Поднимает сервер на чистой базе с демо-данными (python -m app.demo_data), проходит сценарий
в Playwright с записью видео и склеивает сегменты в MP4 H.264 через ffmpeg.
Оплата — демонстрационная (PAYMENT_PROVIDER=demo): это видно по плашке «Демо-режим».

Нужны: python -m playwright install chromium; ffmpeg (берётся из PATH или из пакета imageio-ffmpeg).
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.locker_simulator import Locker, derive_secret  # noqa: E402

MEDIA = ROOT / "media"
PAUSE = 950          # мс между действиями — зритель успевает прочитать
SECRET_KEY = "demo-recording-secret-key-0123456789abcdef"
VIEW = {"width": 390, "height": 844}
# Видео Playwright пишется в CSS-пикселях (390×844) и игнорирует device_scale_factor,
# поэтому кадры берём напрямую из CDP screencast Chromium — в физическом разрешении ×3.


class Screencast:
    """Кадры экрана через Page.startScreencast: время + JPEG, только при изменениях."""

    def __init__(self, page):
        self.frames: list[tuple[float, bytes]] = []
        self.cdp = page.context.new_cdp_session(page)
        self.cdp.on("Page.screencastFrame", self._frame)
        self.cdp.send("Page.startScreencast", {
            "format": "jpeg", "quality": 95, "everyNthFrame": 1, "maxWidth": 1170, "maxHeight": 2532,
        })

    def _frame(self, event):
        import base64

        self.frames.append((event["metadata"]["timestamp"], base64.b64decode(event["data"])))
        try:
            self.cdp.send("Page.screencastFrameAck", {"sessionId": event["sessionId"]})
        except Exception:
            pass

    def stop(self, out: Path) -> Path:
        """Сохраняет кадры и список для ffmpeg concat с длительностью каждого кадра."""
        self.cdp.send("Page.stopScreencast")
        end = time.time()
        out.mkdir(parents=True, exist_ok=True)
        lines = []
        for i, (ts, data) in enumerate(self.frames):
            name = out / f"{i:05d}.jpg"
            name.write_bytes(data)
            nxt = self.frames[i + 1][0] if i + 1 < len(self.frames) else end
            lines.append(f"file '{name}'\nduration {max(0.001, nxt - ts):.3f}")
        # последний кадр повторяем — иначе concat-демультиплексор теряет его длительность
        lines.append(f"file '{out / f'{len(self.frames) - 1:05d}.jpg'}'")
        listing = out / "frames.txt"
        listing.write_text("\n".join(lines) + "\n")
        return listing


def ffmpeg_bin() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return found
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_server(workdir: Path) -> tuple[subprocess.Popen, str]:
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite+aiosqlite:///{workdir / 'demo.db'}",
        "SECRET_KEY": SECRET_KEY,
        "PAYMENT_PROVIDER": "demo",
    }
    subprocess.run([sys.executable, "-m", "app.demo_data"], cwd=ROOT, env=env, check=True, capture_output=True)
    port = free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    for _ in range(80):
        try:
            if httpx.get(f"{base}/api/health", timeout=1).status_code == 200:
                return proc, base
        except httpx.HTTPError:
            time.sleep(0.25)
    proc.kill()
    raise RuntimeError("сервер не поднялся")


def phone(pw, video_dir: Path):
    browser = pw.chromium.launch()
    device = dict(pw.devices["iPhone 14"])
    device.update(viewport=VIEW, screen=VIEW, device_scale_factor=3)
    context = browser.new_context(**device, locale="ru-RU", timezone_id="Europe/Moscow")
    context.video_dir = video_dir
    return browser, context


def start(context):
    page = context.new_page()
    page.goto("about:blank")
    context.cast = Screencast(page)
    return page


def finish(context, browser):
    context.listing = context.cast.stop(context.video_dir)
    context.close()
    browser.close()
    return context.listing


def pause(page, k: float = 1.0):
    page.wait_for_timeout(int(PAUSE * k))


def login(page, base, email):
    page.goto(f"{base}/#/login")
    page.wait_for_selector(".brand-logo")
    pause(page, 1.6)
    page.click(f"[data-demo='{email}']")
    page.wait_for_function("() => !location.hash.startsWith('#/login')")


def segment_student_order(pw, base, out: Path) -> int:
    browser, context = phone(pw, out)
    page = start(context)
    login(page, base, "student@rosbiotech.ru")
    pause(page, 1.2)

    page.goto(f"{base}/#/menu")
    page.wait_for_selector("#list .dish")
    pause(page)
    page.mouse.wheel(0, 380)
    pause(page)
    page.locator("#list a.dish:not(.dish--out)").nth(1).click()
    page.wait_for_selector("[data-buy]")
    pause(page, 1.2)
    page.click("[data-buy]")
    pause(page)

    page.goto(f"{base}/#/cart")
    page.wait_for_selector("#action-bar [data-goto='#/checkout']")
    pause(page)
    page.click("#action-bar [data-goto='#/checkout']")
    page.wait_for_selector(".slot-deadline")
    pause(page)
    # перемена с выдачей в постамате, подпись «приём до 13:20»
    slot = page.locator("[data-slot]:not([disabled])", has_text="Постамат").first
    slot.scroll_into_view_if_needed()
    slot.click()
    pause(page, 1.6)
    page.click("#action-bar [data-submit]")
    page.wait_for_selector("#action-bar [data-pay]")
    pause(page, 1.2)
    page.click("#action-bar [data-pay]")
    page.wait_for_url("**/#/order/*", timeout=20000)
    page.wait_for_selector(".big-number")
    pause(page, 1.6)
    order_id = int(page.url.rsplit("/", 1)[-1].split("?")[0])
    finish(context, browser)
    return order_id


def segment_kitchen(pw, base, out: Path, order_id: int, day: str, slot_id: int):
    browser, context = phone(pw, out)
    page = start(context)
    login(page, base, "operator@rosbiotech.ru")
    page.goto(f"{base}/#/operator")
    page.wait_for_selector(f"[data-day='{day}']").click()
    section = page.locator(f"[data-slot-section='{slot_id}']")
    section.wait_for()
    if not section.locator(".shift-slot__body").count():
        section.locator("[data-toggle]").click()
    section.locator(".collect").scroll_into_view_if_needed()
    pause(page, 1.4)
    ready = page.locator(f"[data-ready='{order_id}']")
    ready.scroll_into_view_if_needed()
    pause(page)
    ready.click()
    place = page.wait_for_selector(f"[data-place='{order_id}']")
    pause(page)
    place.click()
    pause(page, 0.6)
    page.click(".sheet [data-yes]")
    page.wait_for_selector(f".ticket:has([data-unload='{order_id}'])")
    page.locator(f"[data-unload='{order_id}']").scroll_into_view_if_needed()
    pause(page, 1.4)
    finish(context, browser)


def segment_pickup(pw, base, out: Path, order_id: int, student_headers: dict):
    browser, context = phone(pw, out)
    page = start(context)
    login(page, base, "student@rosbiotech.ru")
    page.goto(f"{base}/#/order/{order_id}")
    page.wait_for_selector("#locker-qr svg")
    pause(page, 3)

    # «сканер» постамата считывает код с экрана студента
    token = httpx.post(f"{base}/api/orders/{order_id}/pickup-token", headers=student_headers).json()
    locker = Locker(base, "locker-b1", derive_secret("locker-b1", secret_key=SECRET_KEY))
    opened = locker.scan(token["code"])
    locker.event("door_opened", opened["cell"])
    locker.event("door_closed", opened["cell"])
    page.wait_for_selector("#review-box", timeout=15000)
    page.locator("#review-box").scroll_into_view_if_needed()
    pause(page, 1.2)
    page.click("[data-star='5']")
    pause(page, 0.8)
    page.click("[data-tag='tasty']")
    page.click("[data-tag='fast']")
    pause(page, 0.8)
    page.click("[data-send]")
    page.wait_for_selector(".review")
    pause(page, 2)
    finish(context, browser)


def main() -> None:
    MEDIA.mkdir(exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="rospit-demo-"))
    proc, base = start_server(work)
    try:
        student = {"Authorization": "Bearer " + httpx.post(
            f"{base}/api/auth/login", json={"email": "student@rosbiotech.ru", "password": "student"}
        ).json()["token"]}
        httpx.delete(f"{base}/api/cart", headers=student)
        with sync_playwright() as pw:
            # обложка: экран входа с логотипом
            browser, context = phone(pw, work / "cover")
            page = context.new_page()
            page.goto(f"{base}/#/login")
            page.wait_for_selector(".brand-logo")
            page.wait_for_timeout(600)
            page.screenshot(path=str(MEDIA / "rospit_demo_cover.png"))
            context.close()
            browser.close()

            order_id = segment_student_order(pw, base, work / "a")
            order = httpx.get(f"{base}/api/orders/{order_id}", headers=student).json()
            day = order["pickup_date"]
            slot_id = next(
                s["id"] for s in httpx.get(f"{base}/api/slots?date={day}").json()
                if order["slot_label"].startswith(s["label"])
            )
            segment_kitchen(pw, base, work / "b", order_id, day, slot_id)
            segment_pickup(pw, base, work / "c", order_id, student)
    finally:
        proc.terminate()

    parts = [work / name / "frames.txt" for name in ("a", "b", "c")]
    inputs: list[str] = []
    for part in parts:
        # первые 0,4 с — пустая страница до загрузки
        inputs += ["-ss", "0.4", "-f", "concat", "-safe", "0", "-i", str(part)]
    w, h = 1170, 2532
    chains = "".join(
        f"[{i}:v]scale={w}:{h}:flags=lanczos:out_range=tv,fps=30,format=yuv420p,setsar=1[v{i}];"
        for i in range(len(parts))
    )
    concat = "".join(f"[v{i}]" for i in range(len(parts))) + f"concat=n={len(parts)}:v=1:a=0[out]"
    target = MEDIA / "rospit_demo.mp4"
    subprocess.run(
        [ffmpeg_bin(), "-y", "-loglevel", "error", *inputs, "-filter_complex", chains + concat,
         "-map", "[out]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
         "-pix_fmt", "yuv420p", "-color_range", "tv", "-r", "30", "-movflags", "+faststart", str(target)],
        check=True,
    )
    probe = subprocess.run([ffmpeg_bin(), "-i", str(target)], capture_output=True, text=True).stderr
    duration = next((line.split("Duration:")[1].split(",")[0].strip() for line in probe.splitlines()
                     if "Duration:" in line), "?")
    print(f"✓ {target.relative_to(ROOT)} ({duration}), обложка media/rospit_demo_cover.png")
    print(f"  записано {datetime.now(UTC) + timedelta(hours=3):%d.%m.%Y %H:%M} МСК, оплата — демо-режим")
    shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
