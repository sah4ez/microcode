# USAGE

## Prerequisites

- Go toolchain 1.26+ (`go version`).
- The `tg` CLI (Tool Gateway) with the `astg` and `server` plugins installed
  (`tg pkg list`). The environment's `tg pkg add` needs the download-race patch
  in `skills/tg-patch/`; a working patched binary is at `/home/loki/bin/tg`.
- No external services (no database server). SQLite is an embedded file.
- Port `8000` must be free. The server **binds `0.0.0.0:8000`** (all interfaces)
  so msb port-forwarding works; clients connect to `http://127.0.0.1:8000`.
- Env: Go module proxy. The `github.com/seniorGolang/tg/v3` module is not on the
  public Go proxy, so use a direct fallback:
  `go env -w GOPROXY=https://proxy.golang.org,direct GOSUMDB=off`.

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
# 1) Create a cabinet (ЛК) -> 201
curl -s -i -X POST http://127.0.0.1:8000/personal-profile -H 'Content-Type: application/json' -d '{"name":"работа"}'

# 2) Create a todo in the cabinet -> 201
curl -s -i -X POST http://127.0.0.1:8000/todos -H 'Content-Type: application/json' -H 'x-lk-id: 1' -d '{"title":"Buy milk","description":"2 liters"}'

# 3) List todos for the cabinet -> 200
curl -s -i http://127.0.0.1:8000/todos -H 'x-lk-id: 1'

# 4) Open the web UI in a browser: http://127.0.0.1:8000
#    The dropdown shows all cabinets; switching reloads todos for the selected cabinet.
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
