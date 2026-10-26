#!/usr/bin/env python3
"""Однократная загрузка фотографий блюд в репозиторий.

Фото кладутся в `static/img/dishes/` и коммитятся — в рантайме приложение
не ходит в сеть и не зависит от доступности внешних сервисов.

Провайдеры пробуются по порядку, пока не найдётся подходящий снимок:

  local      папка scripts/photos_in/ — наивысший приоритет, сеть не трогаем
  openverse  https://api.openverse.org — только свободные лицензии, без ключа
  wikimedia  Wikimedia Commons — хорошо покрывает русскую кухню
  pexels     только если в окружении задан PEXELS_API_KEY

Примеры:
    python scripts/fetch_dish_images.py                  # всё, чего ещё нет
    python scripts/fetch_dish_images.py --only "Борщ"    # одно блюдо
    python scripts/fetch_dish_images.py --force          # перекачать заново
    python scripts/fetch_dish_images.py --provider wikimedia

Подробности — в scripts/README.md.
"""
from __future__ import annotations

import argparse
import asyncio
import html
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal, create_all, engine, ensure_columns  # noqa: E402
from app.images import ImageError, process, save_pair  # noqa: E402
from app.models import Dish  # noqa: E402
from app.reference import slugify  # noqa: E402
from scripts.image_queries import IMAGE_QUERIES  # noqa: E402

OUT_DIR = ROOT / "static" / "img" / "dishes"
PHOTOS_IN = Path(__file__).resolve().parent / "photos_in"
PREVIEW_DIR = Path(__file__).resolve().parent / "out"
ATTRIBUTION = OUT_DIR / "attribution.json"

PROVIDERS = ("local", "openverse", "wikimedia", "pexels")
# заголовок только из ASCII — httpx кодирует его в latin-1
USER_AGENT = "RosPit/1.1 (student project; dish photo fetcher; +https://rosbiotech.ru)"
TIMEOUT = httpx.Timeout(20.0, connect=10.0)
MAX_DOWNLOAD_BYTES = 12 * 1024 * 1024

LOCAL_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")


@dataclass
class Candidate:
    """Найденный снимок до скачивания."""

    url: str
    provider: str
    author: str = ""
    license: str = ""
    source_url: str = ""
    title: str = ""


@dataclass
class Result:
    dish: str
    slug: str
    status: str            # ok | skipped | failed
    provider: str = ""
    reason: str = ""
    placeholder: str = ""
    author: str = ""
    license: str = ""
    source_url: str = ""


def log(message: str) -> None:
    print(message, flush=True)


# --------------------------------------------------------------------------- #
#  Провайдеры
# --------------------------------------------------------------------------- #
def find_local(slug: str) -> Candidate | None:
    """Своё фото из scripts/photos_in/<slug>.jpg — приоритетнее любого поиска."""
    for suffix in LOCAL_SUFFIXES:
        path = PHOTOS_IN / f"{slug}{suffix}"
        if path.exists():
            return Candidate(
                url=path.as_uri(),
                provider="local",
                author="Столовая РОСБИОТЕХ",
                license="Собственный снимок",
                source_url="",
                title=path.name,
            )
    return None


async def search_openverse(client: httpx.AsyncClient, query: str) -> list[Candidate]:
    response = await client.get(
        "https://api.openverse.org/v1/images/",
        params={
            "q": query,
            "page_size": 8,
            "license_type": "all-cc",
            "mature": "false",
            "aspect_ratio": "wide",
        },
    )
    response.raise_for_status()
    out = []
    for item in response.json().get("results", []):
        url = item.get("url")
        if not url:
            continue
        out.append(
            Candidate(
                url=url,
                provider="openverse",
                author=item.get("creator") or "",
                license=_pretty_license(item.get("license"), item.get("license_version")),
                source_url=item.get("foreign_landing_url") or url,
                title=item.get("title") or "",
            )
        )
    return out


async def search_wikimedia(client: httpx.AsyncClient, query: str) -> list[Candidate]:
    response = await client.get(
        "https://commons.wikimedia.org/w/api.php",
        params={
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": f"{query} filetype:bitmap",
            "gsrnamespace": 6,
            "gsrlimit": 8,
            "prop": "imageinfo",
            "iiprop": "url|extmetadata|size",
            "iiurlwidth": 1280,
        },
    )
    response.raise_for_status()
    pages = (response.json().get("query") or {}).get("pages") or {}
    out = []
    for page in pages.values():
        info = (page.get("imageinfo") or [{}])[0]
        url = info.get("thumburl") or info.get("url")
        if not url:
            continue
        meta = info.get("extmetadata") or {}
        out.append(
            Candidate(
                url=url,
                provider="wikimedia",
                author=_strip_html(_meta(meta, "Artist")),
                license=_meta(meta, "LicenseShortName") or _meta(meta, "License"),
                source_url=info.get("descriptionurl") or url,
                title=page.get("title", ""),
            )
        )
    return out


async def search_pexels(client: httpx.AsyncClient, query: str) -> list[Candidate]:
    key = os.environ.get("PEXELS_API_KEY", "").strip()
    if not key:
        return []
    response = await client.get(
        "https://api.pexels.com/v1/search",
        params={"query": query, "per_page": 8, "orientation": "landscape"},
        headers={"Authorization": key},
    )
    response.raise_for_status()
    out = []
    for item in response.json().get("photos", []):
        url = (item.get("src") or {}).get("large")
        if not url:
            continue
        out.append(
            Candidate(
                url=url,
                provider="pexels",
                author=item.get("photographer") or "",
                license="Pexels License",
                source_url=item.get("url") or url,
                title=item.get("alt") or "",
            )
        )
    return out


SEARCHERS = {
    "openverse": search_openverse,
    "wikimedia": search_wikimedia,
    "pexels": search_pexels,
}


def _meta(meta: dict, key: str) -> str:
    return (meta.get(key) or {}).get("value") or ""


def _strip_html(value: str) -> str:
    """В Commons поле Artist — кусок HTML со ссылкой на автора."""
    import re

    text = re.sub(r"<[^>]+>", " ", value or "")
    return " ".join(html.unescape(text).split())[:160]


def _pretty_license(code: str | None, version: str | None) -> str:
    if not code:
        return ""
    label = code.upper().replace("_", " ")
    if code.lower() in ("cc0", "pdm"):
        return label
    return f"CC {label} {version}".strip() if version else f"CC {label}"


# --------------------------------------------------------------------------- #
#  Скачивание и обработка
# --------------------------------------------------------------------------- #
async def fetch_bytes(client: httpx.AsyncClient, candidate: Candidate) -> bytes:
    if candidate.url.startswith("file://"):
        path = Path(candidate.url[7:])
        return path.read_bytes()

    async with client.stream("GET", candidate.url, follow_redirects=True) as response:
        response.raise_for_status()
        chunks, total = [], 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > MAX_DOWNLOAD_BYTES:
                raise ValueError("файл больше 12 МБ — пропускаем")
            chunks.append(chunk)
    return b"".join(chunks)


async def candidates_for(
    client: httpx.AsyncClient, dish_name: str, slug: str, providers: tuple[str, ...]
) -> list[Candidate]:
    """Кандидаты по всем провайдерам, в порядке приоритета."""
    found: list[Candidate] = []

    if "local" in providers:
        local = find_local(slug)
        if local:
            return [local]  # своё фото важнее любых результатов поиска

    queries = IMAGE_QUERIES.get(dish_name) or [dish_name]
    for provider in providers:
        if provider == "local":
            continue
        searcher = SEARCHERS.get(provider)
        if searcher is None:
            continue
        for query in queries:
            try:
                found.extend(await searcher(client, query))
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                log(f"    ! {provider}: запрос «{query}» не удался ({type(exc).__name__}: {exc})")
                continue
            if found:
                break
        if found:
            break
    return found


async def handle_dish(
    client: httpx.AsyncClient,
    dish: Dish,
    providers: tuple[str, ...],
    force: bool,
) -> Result:
    slug = slugify(dish.name, fallback=f"dish-{dish.id}")
    target = OUT_DIR / f"{slug}.webp"

    if target.exists() and not force:
        return Result(dish.name, slug, "skipped", reason="файл уже есть (--force перекачает)")

    log(f"  · {dish.name}")
    try:
        found = await candidates_for(client, dish.name, slug, providers)
    except Exception as exc:
        return Result(dish.name, slug, "failed", reason=f"поиск не удался: {exc}")

    if not found:
        return Result(dish.name, slug, "failed", reason="ни один провайдер не дал результатов")

    last_error = ""
    for candidate in found[:5]:
        try:
            raw = await fetch_bytes(client, candidate)
            processed = process(raw)
        except (httpx.HTTPError, OSError, ValueError, ImageError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            continue

        save_pair(processed, OUT_DIR, slug)
        log(
            f"    ✓ {candidate.provider} · {processed.source_size[0]}×{processed.source_size[1]}"
            f" → {processed.placeholder}"
        )
        return Result(
            dish.name,
            slug,
            "ok",
            provider=candidate.provider,
            placeholder=processed.placeholder,
            author=candidate.author,
            license=candidate.license,
            source_url=candidate.source_url,
        )

    return Result(dish.name, slug, "failed", reason=f"скачать не удалось ({last_error})")


# --------------------------------------------------------------------------- #
#  Контактный лист
# --------------------------------------------------------------------------- #
def write_preview(results: list[Result], attribution: dict, all_dishes: list[str]) -> Path:
    """Сетка со всеми фото — человек глазами отбраковывает мусор.

    Автоматический поиск всегда приносит 10–20% не того: под «Солянкой»
    может оказаться пицца. Без просмотра глазами публиковать нельзя.
    """
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    path = PREVIEW_DIR / "preview.html"

    # контактный лист всегда собираем по всему меню, даже если прогон был с --only:
    # иначе после точечной перекачки лист превратился бы в одну карточку
    by_dish = {r.dish: r for r in results}
    rows = [
        by_dish.get(name)
        or Result(name, slugify(name), "skipped", provider=attribution.get(slugify(name), {}).get("provider", ""))
        for name in all_dishes
    ]

    cards = []
    for result in sorted(rows, key=lambda r: r.dish):
        meta = attribution.get(result.slug, {})
        image = OUT_DIR / f"{result.slug}.webp"
        rel = os.path.relpath(image, PREVIEW_DIR)
        author = meta.get("author") or result.author or "—"
        license_ = meta.get("license") or result.license or "—"
        source = meta.get("source_url") or result.source_url
        provider = meta.get("provider") or result.provider or "—"

        if image.exists():
            visual = f'<img src="{html.escape(rel)}" alt="{html.escape(result.dish)}" loading="lazy">'
            state = ""
        else:
            visual = '<div class="no-photo">фото нет</div>'
            state = " card--empty"

        cards.append(f"""
        <figure class="card{state}">
          {visual}
          <figcaption>
            <b>{html.escape(result.dish)}</b>
            <span class="slug">{html.escape(result.slug)}</span>
            <span>Источник: {html.escape(provider)}</span>
            <span>Автор: {html.escape(author)}</span>
            <span>Лицензия: {html.escape(license_)}</span>
            {f'<a href="{html.escape(source)}" target="_blank" rel="noreferrer">первоисточник →</a>' if source else ''}
            {f'<span class="warn">{html.escape(result.reason)}</span>' if result.reason else ''}
          </figcaption>
        </figure>""")

    ok = sum(1 for r in rows if (OUT_DIR / f"{r.slug}.webp").exists())
    total = len(rows)

    path.write_text(
        f"""<!doctype html>
<html lang="ru">
<meta charset="utf-8">
<title>РосПит — контактный лист фотографий блюд</title>
<style>
  body {{ background:#111; color:#eee; font:14px/1.45 -apple-system, Segoe UI, Roboto, sans-serif;
         margin:0; padding:28px; }}
  h1 {{ font-size:22px; margin:0 0 6px; }}
  .lead {{ color:#aaa; margin:0 0 22px; max-width:760px; }}
  .grid {{ display:grid; gap:16px; grid-template-columns:repeat(auto-fill,minmax(260px,1fr)); }}
  .card {{ background:#1c1c20; border-radius:14px; overflow:hidden; margin:0; }}
  .card--empty {{ outline:1px solid #7a3b3b; }}
  .card img {{ width:100%; aspect-ratio:4/3; object-fit:cover; display:block; }}
  .no-photo {{ width:100%; aspect-ratio:4/3; display:grid; place-items:center; color:#777;
               background:repeating-linear-gradient(45deg,#222,#222 8px,#1a1a1a 8px,#1a1a1a 16px); }}
  figcaption {{ padding:11px 13px; display:flex; flex-direction:column; gap:3px; font-size:12px; color:#9a9aa2; }}
  figcaption b {{ color:#fff; font-size:14px; }}
  .slug {{ font-family:ui-monospace,Menlo,monospace; color:#666; }}
  .warn {{ color:#e2a04a; }}
  a {{ color:#6ea0ff; }}
</style>
<h1>Контактный лист · {ok} из {total} блюд с фотографией</h1>
<p class="lead">
  Просмотрите глазами: автоматический поиск регулярно приносит не то блюдо.
  Плохой снимок заменяется своим — положите файл в <code>scripts/photos_in/&lt;слаг&gt;.jpg</code>
  и запустите <code>python scripts/fetch_dish_images.py --only "Название" --force</code>.
</p>
<div class="grid">{''.join(cards)}</div>
</html>""",
        encoding="utf-8",
    )
    return path


# --------------------------------------------------------------------------- #
#  Точка входа
# --------------------------------------------------------------------------- #
async def run(args: argparse.Namespace) -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    PHOTOS_IN.mkdir(parents=True, exist_ok=True)

    providers: tuple[str, ...] = (args.provider,) if args.provider else PROVIDERS
    if args.provider and args.provider != "local":
        providers = ("local", args.provider)

    await create_all()
    await ensure_columns()

    attribution: dict = {}
    if ATTRIBUTION.exists():
        try:
            attribution = json.loads(ATTRIBUTION.read_text(encoding="utf-8"))
        except ValueError:
            log("! attribution.json повреждён — файл будет перезаписан")

    async with SessionLocal() as session:
        dishes = list((await session.scalars(select(Dish).order_by(Dish.id))).all())
        all_dish_names = [d.name for d in dishes]
        if args.only:
            needle = args.only.lower()
            dishes = [d for d in dishes if needle in d.name.lower()]
            if not dishes:
                log(f"Не нашёл блюда по запросу «{args.only}»")
                return 1

        log(f"Блюд к обработке: {len(dishes)}. Провайдеры: {', '.join(providers)}")
        results: list[Result] = []

        async with httpx.AsyncClient(
            timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}, follow_redirects=True
        ) as client:
            for dish in dishes:
                result = await handle_dish(client, dish, providers, args.force)
                results.append(result)

                if result.status == "ok":
                    attribution[result.slug] = {
                        "dish": dish.name,
                        "provider": result.provider,
                        "author": result.author,
                        "license": result.license,
                        "source_url": result.source_url,
                        "placeholder": result.placeholder,
                    }
                    dish.image_url = f"/static/img/dishes/{result.slug}.webp"
                    dish.image_thumb_url = f"/static/img/dishes/{result.slug}-thumb.webp"
                    dish.image_placeholder = result.placeholder
                    dish.image_author = result.author[:160]
                    dish.image_license = result.license[:80]
                    dish.image_source_url = result.source_url[:400]
                elif result.status == "skipped" and (OUT_DIR / f"{result.slug}.webp").exists():
                    # файл на месте, а в базе ссылки нет — например, новая база
                    meta = attribution.get(result.slug, {})
                    if not dish.image_url:
                        dish.image_url = f"/static/img/dishes/{result.slug}.webp"
                        dish.image_thumb_url = f"/static/img/dishes/{result.slug}-thumb.webp"
                        dish.image_placeholder = meta.get("placeholder", "")
                        dish.image_author = meta.get("author", "")
                        dish.image_license = meta.get("license", "")
                        dish.image_source_url = meta.get("source_url", "")

            await session.commit()

    ATTRIBUTION.write_text(
        json.dumps(attribution, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )
    preview = write_preview(results, attribution, all_dish_names)

    # ------------------------------- Сводка -------------------------------- #
    ok = [r for r in results if r.status == "ok"]
    skipped = [r for r in results if r.status == "skipped"]
    failed = [r for r in results if r.status == "failed"]

    by_provider: dict[str, int] = {}
    for r in ok:
        by_provider[r.provider] = by_provider.get(r.provider, 0) + 1

    log("")
    log("─" * 62)
    log(f"Скачано:   {len(ok)}")
    for provider, count in sorted(by_provider.items(), key=lambda kv: -kv[1]):
        log(f"             {provider}: {count}")
    log(f"Пропущено: {len(skipped)} (файл уже был)")
    log(f"Не вышло:  {len(failed)}")
    for r in failed:
        log(f"             {r.dish} — {r.reason}")
    log("")
    log(f"Контактный лист: {preview}")
    log("Просмотрите его глазами: часть совпадений почти наверняка окажется не тем блюдом.")
    await engine.dispose()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Скачивает фотографии блюд в static/img/dishes/",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--force", action="store_true", help="перекачать даже то, что уже есть")
    parser.add_argument("--only", metavar="ПОДСТРОКА", help='обработать одно блюдо, например --only "Борщ"')
    parser.add_argument(
        "--provider",
        choices=PROVIDERS,
        help="использовать только этот источник (local всегда проверяется первым)",
    )
    args = parser.parse_args()
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        log("\nПрервано пользователем — уже скачанное осталось на месте.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
