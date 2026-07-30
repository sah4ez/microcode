# PRD: Notes API

## Цель
Минимальный REST-API для заметок с локальным SQLite-хранилищем. Создаётся
автономно через loki-mode (provider cline, модель GLM) внутри microsandbox VM.

## Функциональные требования

### Эндпоинты
- `POST   /notes`        — создать заметку. Тело: `{ "title": str, "body": str }`.
  Ответ `201`: `{ "id": int, "title": str, "body": str, "created_at": str }`.
- `GET    /notes`        — список всех заметок. Ответ `200`: массив объектов.
- `GET    /notes/{id}`   — одна заметка. `404` если не найдена.
- `PATCH  /notes/{id}`   — обновить title и/или body. `404` если не найдена.
- `DELETE /notes/{id}`   — удалить. `204` если успешно, `404` если не найдена.

### Модель данных
- `id` — integer, autoincrement primary key.
- `title` — строка, обязательна, непустая.
- `body` — строка, обязательна (может быть пустой).
- `created_at` — ISO-8601 timestamp, UTC.

### Хранение
- SQLite, файл `data/notes.db` (персистентный между рестартами).
- Доступ через repository-класс, не прямой SQL в хендлерах.

## Нефункциональные требования
- Python 3.11, FastAPI, Pydantic v2, uvicorn.
- Все тела запросов/ответов — Pydantic-модели (без bare dicts).
- Статус-коды по RFC 9110 (см. api-contract-rules.md overlay).
- Тест на каждый эндпоинт (см. tdd-rules.md overlay): RED-GREEN-REFACTOR.
- Сервер слушает `0.0.0.0:8000`.

## Критерии приёмки
1. `pytest` — зелёный, покрывает все 5 эндпоинтов + 404-кейсы.
2. Заметка, созданная и перезапущенным сервером прочитанная, сохраняется (SQLite).
3. `curl -s localhost:8000/notes` возвращает JSON-массив.
4. Ни один эндпоинт не падает на пустом/некорректном теле (422 от Pydantic).
