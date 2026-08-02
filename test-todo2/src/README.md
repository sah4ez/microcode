# Todo Service (Go + tg v3)

A minimal todo-list REST API. Refactored to Go on top of
[`github.com/seniorGolang/tg/v3`](https://github.com/seniorGolang/tg) +
[go-fiber](https://gofiber.io), with todos persisted to a local SQLite file.

> **HTTP transport is generated, not hand-written.** The fiber routes/handlers
> in `internal/transport/` are produced by `tg server -o internal/transport`
> from the `// @tg` contract in [`contracts/`](contracts/). Only the business
> logic ([`internal/service`](internal/service)) and the SQLite repository
> ([`internal/storage/sqlite`](internal/storage/sqlite)) are hand-written.

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

| Method & path                | Body                                       | Success           | Errors |
|------------------------------|--------------------------------------------|-------------------|--------|
| `POST /todos`                | `{"title":"...","description":"..."}`      | `201` + Todo      | `422` blank title, `400` bad JSON |
| `GET /todos`                 | —                                          | `200` `{"todos":[...]}` | — |
| `GET /todos/{id}`            | —                                          | `200` + Todo      | `404` |
| `PATCH /todos/{id}`          | `{"title":...,"description":...,"completed":...}` (all optional) | `200` + Todo | `404`, `422` blank title |
| `DELETE /todos/{id}`         | —                                          | `204`             | `404` |
| `POST /todos/{id}/toggle`    | —                                          | `200` + Todo      | `404` |

A `Todo` looks like:

```json
{
  "id": 1,
  "title": "Buy milk",
  "description": "2 liters",
  "completed": false,
  "created_at": "2026-08-02T05:24:00Z"
}
```

Errors are returned as `{"error": "..."}`.

### curl examples

```bash
# Create a todo
curl -i -X POST http://127.0.0.1:8000/todos \
  -H 'Content-Type: application/json' \
  -d '{"title":"Buy milk","description":"2 liters"}'

# List all todos
curl -i http://127.0.0.1:8000/todos

# Get one
curl -i http://127.0.0.1:8000/todos/1

# Update (toggle completed via PATCH)
curl -i -X PATCH http://127.0.0.1:8000/todos/1 \
  -H 'Content-Type: application/json' \
  -d '{"completed":true}'

# Toggle completion
curl -i -X POST http://127.0.0.1:8000/todos/1/toggle

# Delete
curl -i -X DELETE http://127.0.0.1:8000/todos/1
```

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
