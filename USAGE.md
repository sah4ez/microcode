# USAGE

## Prerequisites

- Go toolchain 1.26+ (`go version`)
- Node.js 22+ (for frontend tests only: `node static/app.test.js`)
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
# 1) Register a user
curl -s -X POST http://127.0.0.1:8000/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"test@example.com","password":"Password1"}'

# 2) Login and get JWT
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"test@example.com","password":"Password1"}' | jq -r .access_token)

# 3) Create a todo (requires auth)
curl -s -X POST http://127.0.0.1:8000/todos \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $TOKEN" \
  -H 'x-lk-id: 1' \
  -d '{"title":"Buy milk"}'

# 4) Run tests
cd test-todo2/src && go test ./...
node test-todo2/src/static/app.test.js
```

## Stop

Ctrl+C to stop the server.
