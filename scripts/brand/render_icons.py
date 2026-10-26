"""Растеризует логотип РосПит из SVG в PNG-иконки и favicon.

Запуск (нужен Playwright с Chromium: `python -m playwright install chromium`):
    python scripts/brand/render_icons.py

Источник правды — SVG в static/icons/. PNG генерируются, руками их не правим.
"""
from __future__ import annotations

import asyncio
import io
import pathlib

from PIL import Image
from playwright.async_api import async_playwright

ROOT = pathlib.Path(__file__).resolve().parents[2]
ICONS = ROOT / "static" / "icons"

# (исходник, файл, сторона в px)
TARGETS = [
    ("icon.svg", "icon-180.png", 180),         # apple-touch-icon
    ("icon.svg", "icon-192.png", 192),
    ("icon.svg", "icon-512.png", 512),
    ("icon.svg", "favicon-32.png", 32),
    ("icon-maskable.svg", "icon-maskable-512.png", 512),
    ("icon-maskable.svg", "icon-maskable-192.png", 192),
    # Capacitor: иконка и сплэш для мобильной обёртки (mobile/resources)
    ("icon-maskable.svg", "../../mobile/resources/icon.png", 1024),
]

SPLASH = ("logo.svg", "../../mobile/resources/splash.png", 2732)


async def render(page, svg: pathlib.Path, size: int, *, splash: bool = False) -> bytes:
    markup = svg.read_text(encoding="utf-8")
    if splash:
        # логотип по центру тёмного фона приложения, ширина — треть экрана
        html = f"""<html><body style="margin:0;background:#0a0a0c;width:{size}px;height:{size}px;
                   display:grid;place-items:center">
                   <div style="width:{size // 3}px">{markup}</div></body></html>"""
    else:
        html = f"""<html><body style="margin:0;background:transparent">
                   <div style="width:{size}px;height:{size}px">{markup}</div></body></html>"""
    html = html.replace("<svg ", '<svg width="100%" height="100%" ', 1)
    await page.set_viewport_size({"width": size, "height": size})
    await page.set_content(html)
    return await page.screenshot(omit_background=not splash, clip={
        "x": 0, "y": 0, "width": size, "height": size,
    })


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        for source, name, size in TARGETS:
            out = (ICONS / name).resolve()
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(await render(page, ICONS / source, size))
            print("✓", out.relative_to(ROOT), f"{size}×{size}")

        source, name, size = SPLASH
        out = (ICONS / name).resolve()
        out.write_bytes(await render(page, ICONS / source, size, splash=True))
        print("✓", out.relative_to(ROOT), f"{size}×{size}")
        await browser.close()

    # favicon.ico с несколькими размерами внутри — для старых браузеров
    big = Image.open(io.BytesIO((ICONS / "icon-512.png").read_bytes()))
    big.save(ICONS / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
    print("✓ static/icons/favicon.ico")


if __name__ == "__main__":
    asyncio.run(main())
