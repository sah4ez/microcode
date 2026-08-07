# USAGE

## Prerequisites

- Go toolchain 1.26+ (`go version`).
- Node.js 22+ (only for frontend tests: `node static/app.test.js`).
- The `tg` CLI (Tool Gateway) with the `astg` and `server` plugins installed
  (`tg pkg list`). The environment's `tg pkg add` needs the download-race patch
  in `skills/tg-patch/`; a working patched binary is at `/home/loki/bin/tg`.
- No external services (no database server). SQLite is an embedded file.
- Port `8000` must be free. The server binds `0.0.0.0:8000`.

## Install

```bash
go mod tidy
```

## Start

```bash
go run main.go
```

The server listens on `http://127.0.0.1:8000` and auto-creates `./data/todos.db`.

## Verify

Run the server in one terminal, then:

```bash
# 1) Create a personal cabinet (ЛК) -> expect 201 with id and name
curl -s -i -X POST http://127.0.0.1:8000/personal-profile \
  -H 'Content-Type: application/json' -d '{"name":"Work"}'

# 2) Create a todo in that cabinet (x-lk-id = 1) -> expect 201
curl -s -i -X POST http://127.0.0.1:8000/todos \
  -H 'Content-Type: application/json' -H 'x-lk-id: 1' \
  -d '{"title":"Buy milk","description":"2 liters"}'

# 3) List todos in cabinet 1 -> expect 200 {"todos":[ ... ]}
curl -s -i -H 'x-lk-id: 1' http://127.0.0.1:8000/todos
```

## Web UI

The web UI at `http://127.0.0.1:8000` provides:
- **Cabinet dropdown**: switch between personal cabinets (ЛК); todos reload on switch.
- **Create cabinet**: inline form to add a new cabinet.
- **Manage cabinets**: separate section to rename or delete cabinets.
- **Todo CRUD**: create, edit, toggle, and delete todos scoped to the active cabinet.

## Stop

`Ctrl+C` (the server drains and closes the SQLite handle on SIGINT/SIGTERM).
If backgrounded: `lsof -ti:8000 | xargs -r kill -TERM`.

## Regenerate transport (only if you edit contracts/)

```bash
tg server -o internal/transport && go mod tidy && go vet ./... && go build ./...
```

## Tests

Backend (Go):

```bash
go test ./...
```

Frontend (Node.js, vanilla — no framework, no build step):

```bash
node static/app.test.js
```

Covers the cabinet (ЛК) UI logic: dropdown population, switching reloads todos
via `x-lk-id`, cabinet create/rename/delete, and todo isolation per cabinet.
