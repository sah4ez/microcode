# PRD: Todo List Service (local storage)

## Goal
A minimal todo-list REST service that persists all notes/todos **locally** to disk
(SQLite file). Single-file database, no external services.

## Functional requirements
1. **Create** a todo: `POST /todos` with `{"title": "...", "description": "..."}` →
   returns the created todo with `id`, `created_at`, `completed=false`.
2. **List** all todos: `GET /todos` → array of todos.
3. **Get** one: `GET /todos/{id}`.
4. **Update**: `PATCH /todos/{id}` — toggle `completed`, edit `title`/`description`.
5. **Delete**: `DELETE /todos/{id}`.
6. **Toggle complete**: `POST /todos/{id}/toggle`.

## Non-functional requirements
- **Local persistence**: SQLite database file at `./data/todos.db` (auto-created).
- **Stack**: Python 3, FastAPI, SQLAlchemy (or raw sqlite3), Pydantic.
- **Minimal dependencies**: `fastapi`, `uvicorn`, `sqlalchemy` (+ `pydantic`).
- **Tests**: `pytest` covering create/list/get/update/delete/toggle, and that
  data persists across a server restart (re-open the DB file).
- **Runnable**: `python -m todo_service` or `uvicorn todo_service.app:app` boots
  on `127.0.0.1:8000`.

## Deliverables (in this src/ directory)
- `todo_service/app.py` — FastAPI app + routes.
- `todo_service/models.py` — SQLAlchemy model.
- `todo_service/schemas.py` — Pydantic schemas.
- `todo_service/db.py` — DB session + init.
- `todo_service/__main__.py` — `python -m todo_service` entrypoint.
- `tests/test_todos.py` — pytest suite.
- `requirements.txt` — pinned deps.
- `README.md` — how to run + curl examples.

## Definition of done
- `pip install -r requirements.txt && pytest -q` is green.
- Starting the server and running the curl examples in README works.
- The SQLite file at `./data/todos.db` survives a restart (todos persist).
