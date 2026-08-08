# USAGE

## Prerequisites

- Go toolchain 1.26+ (`go version`).
- Node.js 22+ (only for frontend tests: `node static/app.test.js`).
- The `tg` CLI (Tool Gateway) with the `astg` and `server` plugins installed
  (`tg pkg list`). The environment's `tg pkg add` needs the download-race patch
  in `skills/tg-patch/`; a working patched binary is at `/home/loki/bin/tg`.
- No external services (no database server). SQLite is an embedded file.
- Port `8000` must be free. The server binds `0.0.0.0:8000`.

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `AUTH_SECRET` | random 32-byte hex | HMAC key for JWT signing |
| `AUTH_ACCESS_TTL` | `15m` | Access token lifetime |
| `AUTH_REFRESH_TTL` | `168h` (7 days) | Refresh token lifetime |
| `AUTH_LOGIN_RATE` | `10` | Max login attempts per IP per 15 min |
| `AUTH_CSRF_SECRET` | random 32-byte hex | Key for CSRF token generation |

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
# 1) Register a user -> expect 201 with user + tokens
curl -s -i -X POST http://127.0.0.1:8000/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"user@example.com","password":"Password1"}'

# 2) Login -> expect 200 with access_token + refresh_token
curl -s -i -X POST http://127.0.0.1:8000/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"user@example.com","password":"Password1"}'

# 3) Get current user (use the access_token from step 2) -> expect 200
curl -s -i http://127.0.0.1:8000/auth/me \
  -H 'Authorization: Bearer <access_token>'

# 4) Create a cabinet (auth required) -> expect 201
curl -s -i -X POST http://127.0.0.1:8000/personal-profile \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer <access_token>' \
  -d '{"name":"Work"}'

# 5) Create a todo in cabinet 1 (auth required) -> expect 201
curl -s -i -X POST http://127.0.0.1:8000/todos \
  -H 'Content-Type: application/json' -H 'x-lk-id: 1' \
  -H 'Authorization: Bearer <access_token>' \
  -d '{"title":"Buy milk","description":"2 liters"}'

# 6) Unauthenticated access -> expect 401
curl -s -i http://127.0.0.1:8000/todos
```

## Web UI

The web UI at `http://127.0.0.1:8000` provides:
- **Login page** (`/login`): sign in or register with email + password.
- **Cabinet dropdown**: switch between personal cabinets (ЛК); todos reload on switch.
- **Create cabinet**: inline form to add a new cabinet.
- **Manage cabinets**: separate section to rename or delete cabinets.
- **Todo CRUD**: create, edit, toggle, and delete todos scoped to the active cabinet.
- **Sign Out**: clears token and redirects to login.

Access tokens are stored in `localStorage`. On 401, the UI attempts a token refresh
and retries the request. If refresh fails, the user is redirected to `/login`.

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

Covers auth flow (Bearer tokens, login/register forms), cabinet (ЛК) UI logic,
and todo isolation per cabinet.

