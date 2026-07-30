# PRD: Todo List API (локальное хранение)

## Цель
REST-сервис todo-заметок, который сохраняет всё локально в SQLite-файл.
Без внешних сервисов: одна БД-переменная, минимальные зависимости.

## Функциональные требования
1. **Создать** todo: `POST /todos` с `{"title": "...", "description": "..."}`
   → возвращает todo с `id`, `created_at`, `completed=false`.
2. **Список** всех: `GET /todos` → массив todo.
3. **Получить один**: `GET /todos/{id}`.
4. **Обновить**: `PATCH /todos/{id}` — переключить `completed`, изменить поля.
5. **Удалить**: `DELETE /todos/{id}`.
6. **Переключить готовность**: `POST /todos/{id}/toggle`.

## Нефункциональные требования
- **Локальное хранение**: SQLite-файл в `./data/todos.db` (создаётся автоматически).
- **Стек**: Python 3, FastAPI, SQLAlchemy, Pydantic.
- **Минимум зависимостей**: `fastapi`, `uvicorn`, `sqlalchemy`, `pydantic`.
- **Тесты**: `pytest`, покрывают create/list/get/update/delete/toggle + что
  данные переживают рестарт сервера (переоткрытие БД).
- **Запуск**: `python -m todo_service` или
  `uvicorn todo_service.app:app` — поднимается на `127.0.0.1:8000`.

## Артефакты (в этом каталоге src/)
- `todo_service/app.py` — FastAPI-приложение + маршруты.
- `todo_service/models.py` — SQLAlchemy-модель.
- `todo_service/schemas.py` — Pydantic-схемы.
- `todo_service/db.py` — сессия БД + init.
- `todo_service/__main__.py` — entrypoint `python -m todo_service`.
- `tests/test_todos.py` — набор pytest-тестов.
- `requirements.txt` — зафиксированные зависимости.
- `README.md` — как запустить + примеры curl.

## Критерий готовности
- `pip install -r requirements.txt && pytest -q` — зелёные.
- Запуск сервера и curl-примеры из README работают.
- SQLite-файл `./data/todos.db` переживает рестарт (заметки сохраняются).
