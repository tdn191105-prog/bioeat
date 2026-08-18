.PHONY: up down demo reset test logs local photos

up:            ## Поднять приложение и базу
	docker compose up --build

down:          ## Остановить (данные сохраняются)
	docker compose down

clean:         ## Остановить и удалить базу
	docker compose down -v

demo:          ## Налить демонстрационные заказы
	docker compose exec app python -m app.demo_data

reset:         ## Убрать демонстрационные заказы
	docker compose exec app python -m app.demo_data --reset

logs:
	docker compose logs -f app

test:          ## Прогнать тесты (PostgreSQL не нужен)
	pytest

local:         ## Запуск без Docker на SQLite
	DATABASE_URL=sqlite+aiosqlite:///./bioeat.db uvicorn app.main:app --reload

photos:        ## Скачать недостающие фотографии блюд (см. scripts/README.md)
	DATABASE_URL=sqlite+aiosqlite:///./bioeat.db python scripts/fetch_dish_images.py
