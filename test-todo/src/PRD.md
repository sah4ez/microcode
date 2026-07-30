# PRD: Todo App с UI

## Цель
Todo-приложение с веб-UI и REST-API, локальным SQLite-хранилищем. Создаётся
автономно через loki-mode (provider cline, модель GLM) внутри microsandbox VM.
Результат — готовое приложение в `/workspace`, которое можно скопировать из VM.

## Функциональные требования

### REST API (бекенд)
- `POST   /api/todos`     — создать задачу. Тело: `{ "title": str, "body": str }`.
  Ответ `201`: `{ "id": int, "title": str, "body": str, "done": bool, "created_at": str }`.
- `GET    /api/todos`     — список всех задач. Ответ `200`: массив объектов.
- `GET    /api/todos/{id}` — одна задача. `404` если не найдена.
- `PATCH  /api/todos/{id}` — обновить title/body/done. `404` если не найдена.
- `DELETE /api/todos/{id}` — удалить. `204` если успешно, `404` если не найдена.

### Веб-UI (фронтенд)
- `GET /` — главная страница с UI (HTML, обслуживается тем же сервером).
- UI должен:
  - Показывать список всех задач (title, body, статус done/не done).
  - Форму создания новой задачи (title + body).
  - Кнопку отметки задачи как выполненной (toggle done).
  - Кнопку удаления задачи.
  - Кнопку редактирования (опционально).
- UI обновляется без перезагрузки страницы (fetch к /api/todos).
- Минимальный, но аккуратный CSS (без внешних фреймворков, inline `<style>`).
- Чистый vanilla JS (без React/Vue), один `index.html` + `app.js` + `styles.css`.

### Модель данных
- `id` — integer, autoincrement primary key.
- `title` — строка, обязательна, непустая.
- `body` — строка, опциональна (может быть пустой).
- `done` — boolean, default false.
- `created_at` — ISO-8601 timestamp, UTC.

### Хранение
- SQLite, файл `data/todos.db` (персистентный между рестартами).
- Доступ через repository-класс, не прямой SQL в хендлерах.

## Структура проекта
```
/workspace/
├── main.py              # FastAPI app: API + статика UI
├── models.py            # Pydantic-модели
├── repository.py        # SQLite repository
├── tests/
│   └── test_api.py      # тесты эндпоинтов
├── static/
│   ├── index.html       # UI
│   ├── app.js           # логика UI
│   └── styles.css       # стили
├── data/
│   └── todos.db         # SQLite (создаётся при первом запуске)
└── requirements.txt     # fastapi, uvicorn, pydantic, aiosqlite
```

## Нефункциональные требования
- Python 3.11, FastAPI, Pydantic v2, uvicorn.
- Все тела запросов/ответов API — Pydantic-модели (без bare dicts).
- Статус-коды по RFC 9110.
- Тест на каждый эндпоинт (RED-GREEN-REFACTOR).
- Сервер слушает `0.0.0.0:8000`.
- Статика UI обслуживается через FastAPI StaticFiles или FileResponse.

## Критерии приёмки
1. `pytest` — зелёный, покрывает все 5 эндпоинтов + 404-кейсы.
2. Задача, созданная и перезапущенным сервером прочитанная, сохраняется (SQLite).
3. `curl -s localhost:8000/api/todos` возвращает JSON-массив.
4. `curl -s localhost:8000/` возвращает HTML-страницу с UI.
5. UI: можно создать задачу, отметить выполненной, удалить — без перезагрузки страницы.
6. Ни один эндпоинт не падает на пустом/некорректном теле (422 от Pydantic).
