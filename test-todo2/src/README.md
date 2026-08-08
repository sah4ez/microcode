# Todo Service (Go + tg v3)

A minimal todo-list REST API with multi-cabinet (ЛК) support. Refactored to Go on
top of [`github.com/seniorGolang/tg/v3`](https://github.com/seniorGolang/tg) +
[go-fiber](https://gofiber.io), with todos persisted to a local SQLite file.

> **HTTP transport is generated, not hand-written.** The fiber routes/handlers
> in `internal/transport/` are produced by `tg server -o internal/transport`
> from the `// @tg` contract in [`contracts/`](contracts/). Only the business
> logic ([`internal/service`](internal/service)) and the SQLite repository
> ([`internal/storage/sqlite`](internal/storage/sqlite)) are hand-written.

## Features

- **User authentication**: JWT-based auth with registration, login, refresh token
  rotation, and password validation (8+ chars, upper/lower/digit). All cabinet
  and todo operations require a valid Bearer access token.
- **Personal cabinets (ЛК)**: create multiple cabinets; each owns an
  independent todo list. Switch between them via the web UI dropdown or the
  `x-lk-id` request header.
- **Web UI**: vanilla-JS single page at `/` with cabinet switching, create,
  rename, delete, and full todo CRUD scoped to the active cabinet.
- **Cabinet isolation**: a todo request with `x-lk-id=1` never sees cabinet 2's
  records; cross-cabinet GET returns 404.

## Requirements

- Go 1.26+
- The `tg` CLI with the `astg` + `server` plugins (already installed in this
  environment; verify with `tg pkg list`). The stock `tg pkg add` has a
  download race that truncates the `-skills.tar.gz` archives; this project was
  built with the patched binary described in [`skills/tg-patch/`](skills/tg-patch/).

## Run

```bash
go mod tidy
go run main.go     # serves http://127.0.0.1:8000
```

The SQLite database is auto-created at `./data/todos.db` on first start and
survives restarts.

## API

All request/response bodies are JSON. Single-resource responses are the bare
todo object; the list endpoint wraps the array.

> **Every `/todos` request requires the `x-lk-id` header** — the id of the
> personal cabinet (ЛК) the todo belongs to. See
> [Работа с личными кабинетами (ЛК)](#работа-с-личными-кабинетами-лк) below.

| Method & path                | Headers          | Body                                       | Success           | Errors |
|------------------------------|------------------|--------------------------------------------|-------------------|--------|
| `POST /todos`                | `x-lk-id`        | `{"title":"...","description":"..."}`      | `201` + Todo      | `422` blank title, `400` bad JSON / missing `x-lk-id` |
| `GET /todos`                 | `x-lk-id`        | —                                          | `200` `{"todos":[...]}` | `400` missing `x-lk-id` |
| `GET /todos/{id}`            | `x-lk-id`        | —                                          | `200` + Todo      | `404`, `400` missing `x-lk-id` |
| `PATCH /todos/{id}`          | `x-lk-id`        | `{"title":...,"description":...,"completed":...}` (all optional) | `200` + Todo | `404`, `422` blank title, `400` missing `x-lk-id` |
| `DELETE /todos/{id}`         | `x-lk-id`        | —                                          | `204`             | `404`, `400` missing `x-lk-id` |
| `POST /todos/{id}/toggle`    | `x-lk-id`        | —                                          | `200` + Todo      | `404`, `400` missing `x-lk-id` |

A `Todo` looks like:

```json
{
  "id": 1,
  "lk_id": 1,
  "title": "Buy milk",
  "description": "2 liters",
  "completed": false,
  "created_at": "2026-08-02T05:24:00Z"
}
```

Errors are returned as `{"error": "..."}`. A missing `x-lk-id` yields
`400 {"error":"x-lk-id header is required"}`.

### curl examples

```bash
# Create a todo in cabinet 1
curl -i -X POST http://127.0.0.1:8000/todos \
  -H 'Content-Type: application/json' \
  -H 'x-lk-id: 1' \
  -d '{"title":"Buy milk","description":"2 liters"}'

# List todos in cabinet 1 (only that cabinet's todos)
curl -i -H 'x-lk-id: 1' http://127.0.0.1:8000/todos

# Get one
curl -i -H 'x-lk-id: 1' http://127.0.0.1:8000/todos/1

# Update (toggle completed via PATCH)
curl -i -X PATCH http://127.0.0.1:8000/todos/1 \
  -H 'Content-Type: application/json' \
  -H 'x-lk-id: 1' \
  -d '{"completed":true}'

# Toggle completion
curl -i -X POST -H 'x-lk-id: 1' http://127.0.0.1:8000/todos/1/toggle

# Delete
curl -i -X DELETE -H 'x-lk-id: 1' http://127.0.0.1:8000/todos/1
```

## Работа с личными кабинетами (ЛК)

Личный кабинет (ЛК, personal profile/cabinet) — это独立ный набор задач. Каждый
ЛК владеет своим disjoint-множеством todo: запрос с `x-lk-id: N` видит **только**
todo, принадлежащие кабинету `N`. Это позволяет вести, например, отдельные списки
«Работа» и «Дом» и переключаться между ними.

### Модель данных

ЛК хранятся в **отдельной таблице** `personal_profiles` (см.
[`internal/storage/sqlite`](internal/storage/sqlite)). Таблица `todos` несёт
внешний ключ `lk_id`, ссылающийся на кабинет-владельца. При старте сервис
проверяет схему: старая таблица `todos` без колонки `lk_id` удаляется и
создаётся заново («удалить старые данные и создать с нуля»), уже-мигрированная
таблица остаётся нетронутой.

`PersonalProfile`:

```json
{ "id": 1, "name": "Работа", "created_at": "2026-08-05T19:34:46Z" }
```

### API личных кабинетов (`/personal-profile`)

CRUD кабинетов. Авторизация ресурса при работе с todo идёт по `x-lk-id`
(значение = `id` кабинета).

| Method & path                  | Body                  | Success                   | Errors |
|--------------------------------|-----------------------|---------------------------|--------|
| `POST /personal-profile`       | `{"name":"..."}`      | `201` + Profile           | `422` blank name |
| `GET /personal-profile`        | —                     | `200` `{"profiles":[...]}` | — |
| `GET /personal-profile/{id}`   | —                     | `200` + Profile           | `404` |
| `PATCH /personal-profile/{id}` | `{"name":"..."}`      | `200` + Profile           | `404`, `422` blank name |
| `DELETE /personal-profile/{id}`| —                     | `204`                     | `404` |

```bash
# Создать кабинет
curl -i -X POST http://127.0.0.1:8000/personal-profile \
  -H 'Content-Type: application/json' -d '{"name":"Работа"}'

# Список кабинетов
curl -i http://127.0.0.1:8000/personal-profile
```

### Web UI

Веб-интерфейс (`/`, [`static/index.html`](static/index.html) +
[`static/app.js`](static/app.js)) содержит **dropdown** со списком всех ЛК.
Переключение в dropdown:

1. обновляет активный кабинет (`x-lk-id`);
2. перезагружает список todo — видны **только** записи выбранного кабинета
   (Non-functional requirement: «при переключении между лк должны
   перезагружаться все доступные записи»);
3. новый todo создаётся в активном кабинете.

Выбранный кабинет сохраняется в `localStorage`, так что перезагрузка страницы
сохраняет контекст. Кабинет можно создать инлайн-формой рядом с dropdown.

## Regenerate the transport

After editing the `// @tg` contract under `contracts/`, regenerate and rebuild:

```bash
tg server -o internal/transport
go mod tidy && go vet ./... && go build ./...
```

`tools.go` (build-tag `tools`) pins the `github.com/seniorGolang/tg/v3` module
version in `go.mod`: tg v3 is a codegen toolchain whose generated output is
self-contained Go, so the framework is a build-time dependency, not a runtime
import.


## Tests

```bash
go test ./...
```

Covers create/list/get/update/delete/toggle, status codes, and that data
persists across a database reopen.
