# USAGE

## Prerequisites

- Go toolchain 1.26+ (`go version`)
- Node.js 22+ (for frontend tests: `node static/app.test.js`)
- No external services required (SQLite is embedded)
- Port 8000 must be free

## Install

```bash
cd test-todo2/src
go mod tidy
```

## Start

```bash
cd test-todo2/src
go run main.go
```

The server listens on `http://127.0.0.1:8000` and auto-creates `./data/todos.db`.

## Verify

```bash
# 1) Create a cabinet (ЛК)
curl -s -X POST http://127.0.0.1:8000/personal-profile -H 'Content-Type: application/json' -d '{"name":"работа"}'

# 2) Create a todo in the cabinet
curl -s -X POST http://127.0.0.1:8000/todos -H 'Content-Type: application/json' -H 'x-lk-id: 1' -d '{"title":"Buy milk"}'

# 3) List todos for the cabinet
curl -s http://127.0.0.1:8000/todos -H 'x-lk-id: 1'

# 4) Run tests
cd test-todo2/src && go test ./...
node test-todo2/src/static/app.test.js
```

## Stop

`Ctrl+C` or `lsof -ti:8000 | xargs kill -TERM`.