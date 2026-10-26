"""РосПит — предзаказ питания в столовой РОСБИОТЕХ.

Точка входа FastAPI: подключает роутеры, отдаёт клиент (PWA) и поднимает схему БД.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import SessionLocal, create_all, engine, ensure_columns
from .routers import admin, auth, cart, menu, operator, orders
from .seed import seed

log = logging.getLogger("rospit")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio

    # ждём готовности БД — контейнер Postgres может подниматься дольше приложения
    last_error: Exception | None = None
    for attempt in range(1, 31):
        try:
            await create_all()
            last_error = None
            break
        except Exception as exc:
            last_error = exc
            log.warning("База ещё не готова (попытка %s/30): %s", attempt, exc)
            await asyncio.sleep(2)
    if last_error is not None:
        raise last_error

    # упрощённая замена миграций для MVP — см. комментарий в app/db.py
    added = await ensure_columns()
    if added:
        log.info("Автомиграция добавила колонки: %s", ", ".join(added))

    async with SessionLocal() as session:
        result = await seed(session)
    log.info("РосПит запущен. Seed: %s", result)
    yield

    # закрываем пул: рабочий поток aiosqlite не демонический и иначе
    # не даёт процессу завершиться (заметно в тестах и при Ctrl+C)
    await engine.dispose()


app = FastAPI(
    title="РосПит API",
    description=(
        "Предзаказ питания в столовой РОСБИОТЕХ. "
        "Платежи работают в демонстрационном режиме и не обращаются к реальным системам."
    ),
    version="1.1.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    """Читаемое сообщение вместо простыни pydantic."""
    first = exc.errors()[0] if exc.errors() else {}
    field = ".".join(str(p) for p in first.get("loc", [])[1:]) or "запрос"
    return JSONResponse(
        status_code=422,
        content={"detail": f"Проверьте поле «{field}»: {first.get('msg', 'некорректное значение')}"},
    )


app.include_router(auth.router)
app.include_router(menu.router)
app.include_router(cart.router)
app.include_router(orders.router)
app.include_router(operator.router)
app.include_router(admin.router)


@app.get("/api/health")
async def health():
    return {"status": "ok", "app": settings.app_name, "demo_payments": settings.demo_payments}


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/manifest.webmanifest", include_in_schema=False)
async def manifest():
    return FileResponse(STATIC_DIR / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/sw.js", include_in_schema=False)
async def service_worker():
    return FileResponse(
        STATIC_DIR / "sw.js",
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse(STATIC_DIR / "icons" / "favicon.ico", media_type="image/x-icon")


@app.get("/{full_path:path}", include_in_schema=False)
async def spa(full_path: str):
    """Все остальные адреса отдают клиент — маршрутизация на стороне приложения."""
    if full_path.startswith("api/"):
        return JSONResponse(status_code=404, content={"detail": "Метод не найден"})
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})
