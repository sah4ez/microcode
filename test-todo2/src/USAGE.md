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
# 1) Create a todo -> expect HTTP/1.1 201 Created and a JSON body with id, created_at, completed:false
curl -s -i -X POST http://127.0.0.1:8000/todos -H 'Content-Type: application/json' -d '{"title":"Buy milk","description":"2 liters"}'

# 2) List -> expect HTTP/1.1 200 and {"todos":[ ... ]}
curl -s -i http://127.0.0.1:8000/todos

# 3) Persistence across restart: create a todo, stop the server (Ctrl+C),
#    `go run main.go` again, then GET it -> it must still be present.
curl -s http://127.0.0.1:8000/todos/1
```

## Stop

`Ctrl+C` (the server drains and closes the SQLite handle on SIGINT/SIGTERM).
If backgrounded: `lsof -ti:8000 | xargs -r kill -TERM`.

## Regenerate transport (only if you edit contracts/)

```bash
tg server -o internal/transport && go mod tidy && go vet ./... && go build ./...
```
