"""Картинки к инструкции «РосПит на iPhone в 3 шага» (docs/students_iphone.md).

Схемы, а не снимки iOS: панель Safari и меню «Поделиться» нарисованы упрощённо, экран
приложения — настоящий скриншот из e2e (tests/e2e/screens/iphone-01-login.jpg).

    python scripts/brand/render_student_guide.py
"""
from __future__ import annotations

import base64
import pathlib

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "img"
SHOT = ROOT / "tests" / "e2e" / "screens" / "iphone-01-login.jpg"
ICON = ROOT / "static" / "icons" / "icon-180.png"


def b64(path: pathlib.Path) -> str:
    return base64.b64encode(path.read_bytes()).decode()


CSS = """
body { margin:0; background:#eef1f7; font-family:-apple-system,"SF Pro Text",Roboto,sans-serif; }
.card { width:560px; padding:28px 30px 32px; box-sizing:border-box; }
.step { font-size:15px; font-weight:800; color:#1f5bff; text-transform:uppercase; letter-spacing:.6px; }
.title { font-size:26px; font-weight:800; margin:6px 0 18px; color:#111; }
.phone { width:300px; height:600px; margin:0 auto; border-radius:46px; background:#111; padding:12px;
         box-shadow:0 20px 50px rgba(0,0,0,.25); position:relative; }
.screen { width:100%; height:100%; border-radius:36px; overflow:hidden; position:relative; background:#0a0a0c; }
.shot { width:100%; display:block; }
.bar { position:absolute; left:0; right:0; bottom:0; height:76px; background:rgba(248,248,250,.96);
       display:flex; justify-content:space-around; align-items:center; padding-bottom:10px; color:#1f6bff; font-size:22px; }
.url { position:absolute; left:14px; right:14px; bottom:84px; height:38px; border-radius:12px; background:#fff;
       box-shadow:0 2px 8px rgba(0,0,0,.15); display:flex; align-items:center; justify-content:center; font-size:14px; color:#333; }
.ring { position:absolute; border:4px solid #ff3b30; border-radius:50%; }
.sheet { position:absolute; left:0; right:0; bottom:0; background:#f2f2f7; border-radius:22px 22px 0 0; padding:14px 14px 26px; }
.row { background:#fff; padding:14px 16px; font-size:16px; color:#111; display:flex; justify-content:space-between;
       border-bottom:1px solid #e5e5ea; }
.row:first-child { border-radius:12px 12px 0 0; } .row:last-child { border-radius:0 0 12px 12px; border-bottom:0; }
.hl { outline:4px solid #ff3b30; outline-offset:-4px; border-radius:12px; font-weight:700; }
.home { background:linear-gradient(160deg,#2b3a67,#0f1630); height:100%; display:grid; grid-template-columns:repeat(4,1fr);
        align-content:start; gap:20px 0; padding:60px 14px; box-sizing:border-box; }
.app { display:flex; flex-direction:column; align-items:center; gap:6px; color:#fff; font-size:11px; }
.app i { width:54px; height:54px; border-radius:14px; background:rgba(255,255,255,.18); display:block; }
.app img { width:54px; height:54px; border-radius:14px; }
.app.me span { font-weight:700; }
.app.me img { outline:4px solid #ff3b30; outline-offset:5px; }
.note { font-size:15px; color:#444; margin-top:18px; line-height:1.45; }
.tag { position:absolute; right:30px; top:28px; font-size:11px; color:#999; }
"""

SAFARI_BAR = """
<div class="url">🔒 rospit.example.ru</div>
<div class="bar"><span>‹</span><span>›</span><span id="share">⬆︎</span><span>📖</span><span>⧉</span></div>
"""


def step1(shot: str) -> str:
    return f"""<div class="card"><div class="tag">схема</div>
      <div class="step">Шаг 1</div><div class="title">Откройте сайт в Safari и нажмите «Поделиться»</div>
      <div class="phone"><div class="screen">
        <img class="shot" src="data:image/jpeg;base64,{shot}">{SAFARI_BAR}
        <div class="ring" style="width:52px;height:52px;left:111px;bottom:6px"></div>
      </div></div>
      <div class="note">Удобнее всего в Safari. В Chrome на iOS 16.4 и новее пункт тоже есть в меню «Поделиться».</div></div>"""


def step2(shot: str) -> str:
    return f"""<div class="card"><div class="tag">схема</div>
      <div class="step">Шаг 2</div><div class="title">Выберите «На экран „Домой“» → «Добавить»</div>
      <div class="phone"><div class="screen">
        <img class="shot" src="data:image/jpeg;base64,{shot}" style="filter:brightness(.45)">
        <div class="sheet">
          <div class="row">Скопировать <span>⧉</span></div>
          <div class="row">Добавить в Избранное <span>☆</span></div>
          <div class="row hl">На экран «Домой» <span>⊞</span></div>
          <div class="row">Найти на странице <span>🔍</span></div>
        </div>
      </div></div>
      <div class="note">Если пункта не видно — пролистайте меню вниз. Название оставьте «РосПит».</div></div>"""


def step3(icon: str) -> str:
    apps = "".join('<div class="app"><i></i><span>&nbsp;</span></div>' for _ in range(6))
    return f"""<div class="card"><div class="tag">схема</div>
      <div class="step">Шаг 3</div><div class="title">Откройте РосПит с иконки и войдите</div>
      <div class="phone"><div class="screen"><div class="home">
        {apps}<div class="app me"><img src="data:image/png;base64,{icon}"><span>РосПит</span></div>
        <div class="app"><i></i><span>&nbsp;</span></div>
      </div>
      </div></div>
      <div class="note">Приложение откроется на весь экран. Войдите ещё раз — у иконки своё хранилище,
      вход из Safari туда не переносится.</div></div>"""


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    shot, icon = b64(SHOT), b64(ICON)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 560, "height": 900}, device_scale_factor=2)
        for n, html in ((1, step1(shot)), (2, step2(shot)), (3, step3(icon))):
            page.set_content(f"<style>{CSS}</style>{html}")
            page.wait_for_timeout(200)
            page.locator(".card").screenshot(path=str(OUT / f"iphone-step-{n}.png"))
            print("✓", (OUT / f"iphone-step-{n}.png").relative_to(ROOT))
        browser.close()


if __name__ == "__main__":
    main()
