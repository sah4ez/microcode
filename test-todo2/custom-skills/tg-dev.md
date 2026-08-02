---
name: tg
description: >-
  Build HTTP microservices in Go with github.com/seniorGolang/tg v3 — a
  contract-first codegen framework on top of go-fiber. Use when implementing
  any Go service for this project: defining a contract interface, running the
  transport codegen via the tgp-go plugin, wiring the generated transport, and
  connecting a SQLite repository. NOT the Tool-Gateway `tg` CLI plugin — this
  is the service framework at github.com/seniorGolang/tg/v3.
---

# tg (github.com/seniorGolang/tg/v3)

Contract-first Go service framework (v3). You write a Go **interface** annotated
with `// @tg ...` tags; the **tgp-go** plugin generates the go-fiber transport
layer (server, clients, swagger) via `go generate`. Business logic + persistence
are yours to write.

**This project uses v3, NOT v2.** v3's module path is `github.com/seniorGolang/tg/v3`,
requires **Go 1.26+**, and its codegen runs as WASM plugins (wazero runtime)
through the `tgp-go` package. The old v2 `tg transport --services ...` command
**does NOT exist in v3** — use the plugin workflow below.

## Environment (already installed by bootstrap)

- Go toolchain 1.26.x at `/usr/local/go/bin/go` (symlinked to `/usr/local/bin/go`).
- `tg` v3 CLI at `/usr/local/bin/tg` (`tg --version` works).
- transport plugin `tgp-go` installed via `tg pkg add` (plugins: `astg` parser,
  `server` = Fiber server, `client-go`, `client-ts`, `swagger`). `tg pkg list`
  shows `astg` and `server` (v1.0.8, ✓).
- built-in agent skills via `tg skills install`.

Confirm before coding: `go version` (≥1.26), `tg --version`, `tg pkg list`.

## ⚠️ Project rule: tg v3 codegen is MANDATORY — no hand-written fiber routes

**This is a hard requirement, not a preference.** The HTTP transport layer MUST
be **generated** by the tg v3 toolchain. Do NOT write fiber handlers / route
registration by hand with `fiber.New()` / `app.Get(...)` / `app.Post(...)`.

Every HTTP endpoint on this project is:
1. defined as a method on a `// @tg`-annotated Go interface in `contracts/`, then
2. the fiber transport is GENERATED via `tg server -o internal/transport`.

Only the business logic (service implementation of the contract) and the SQLite
repository are hand-written. The HTTP wiring (routing, request parsing, response
serialization, fiber app setup) comes ENTIRELY from `tg server`.

**The module path MUST include `/v3`:** `github.com/seniorGolang/tg/v3`. Without
the `/v3` suffix (`github.com/seniorGolang/tg`) the module resolves to nothing on
the Go proxy and you will incorrectly conclude tg is unavailable. It IS available
— `tg --version` and `tg pkg list` prove it. Do not fall back to hand-written
fiber "because tg cannot be installed" — tg is already installed; use it.

## Module bootstrap

```bash
go mod init github.com/<you>/<service>          # once
go get github.com/seniorGolang/tg/v3@latest     # the framework — /v3 is REQUIRED
# tg CLI + tgp-go are already installed in the VM; no `go install` needed.
```

## 1. Define the contract (the source of truth)

A contract is a plain Go interface. **Hard rules** the generator enforces:

- first argument is always `context.Context`;
- last return value is always `error`;
- every other argument AND every other return value **must be named**;
- the `// @tg ...` line sits directly above the interface (or a method).

```go
package todo

import "context"

// Todo is a stored item.
//
// @tg desc="A single todo item"
type Todo struct {
    ID          int64  `json:"id"`
    Title       string `json:"title"`
    Description string `json:"description"`
    Completed   bool   `json:"completed"`
    CreatedAt   string `json:"created_at"` // RFC3339
}

// @tg http-server log metrics
type Service interface {
    // Create a new todo.
    //
    // @tg http-method=POST http-path=/todos http-success=201
    Create(ctx context.Context, in CreateRequest) (out Todo, err error)

    // List all todos.
    //
    // @tg http-method=GET http-path=/todos
    List(ctx context.Context) (out []Todo, err error)

    // Get one todo by id.
    //
    // @tg http-method=GET http-path=/todos/:id
    Get(ctx context.Context, in GetRequest) (out Todo, err error)

    // Update fields of a todo (toggle completed, edit title/description).
    //
    // @tg http-method=PATCH http-path=/todos/:id
    Update(ctx context.Context, in UpdateRequest) (out Todo, err error)

    // Delete a todo.
    //
    // @tg http-method=DELETE http-path=/todos/:id http-success=204
    Delete(ctx context.Context, in DeleteRequest) (err error)

    // Toggle the completed flag.
    //
    // @tg http-method=POST http-path=/todos/:id/toggle
    Toggle(ctx context.Context, in ToggleRequest) (out Todo, err error)
}
```

Request structs carry path/body params with their own tags:

```go
// @tg desc="Create payload"
type CreateRequest struct {
    Title       string `json:"title"   tg:"required"`
    Description string `json:"description"`
}

// @tg desc="Path-bound id"
type GetRequest struct {
    ID int64 `path:"id" tg:"required"`
}
```

Annotation vocabulary (verbatim, from the docs):

| Tag | Meaning |
|---|---|
| `http-server` / `jsonRPC-server` | enable that transport on the interface |
| `log` `metrics` `trace` | enable the middleware on the interface |
| `http-method=POST` | HTTP verb for the method |
| `http-path=/todos/:id` | route + path params |
| `http-prefix=v1` | optional prefix |
| `http-success=201` | success status code (default 200) |
| `desc=...` / `summary=...` | docs (swagger) |
| `required` | non-zero validation |
| `example=...` | sample value |

## 2. Run codegen (v3 plugin workflow — NOT `tg transport`)

In v3 the transport is built by the **tgp-go** plugin. Contracts live in a
`contracts/` dir (set `--contracts-dir`); codegen is invoked as a `tg`
subcommand (NOT `go generate`, NOT `tg plugin run`). The plugin parses the
`// @tg` interfaces and emits a fiber server (the `server` plugin), plus
optional clients/swagger. **Requires a `go.mod` at the project root** or it
fails with "go.mod not found".

```bash
tg server    -o transport                  # generate the Fiber server (REQUIRED)
tg client-go -o clients/go                 # optional: typed Go client (use in tests!)
tg swagger   -o api/swagger.yaml           # optional: OpenAPI 3.0
# contracts dir defaults to ./contracts; override with --contracts-dir <path>
```

Inspect a plugin's flags/annotations: `tg plugin doc server`, `tg plugin doc astg`.
Re-run `tg server -o transport` after **every** contract change. Commit the
generated tree (never edit it by hand).

## 3. Implement the service + repository

The generated transport takes YOUR implementation of the contract. Keep
transport, business, and storage separate:

```
internal/
  transport/   # generated by tgp-go — never edit by hand
  service/     # your Service implementation (business rules)
  storage/     # sqlite repository (database/sql)
cmd/server/main.go
```

Repository contract (interface in `storage`, sql impl in `storage/sqlite`):

```go
type Repository interface {
    Create(ctx context.Context, t Todo) (Todo, error)
    List(ctx context.Context) ([]Todo, error)
    Get(ctx context.Context, id int64) (Todo, error)
    Update(ctx context.Context, t Todo) (Todo, error)
    Delete(ctx context.Context, id int64) error
}
```

Inject it into the service:

```go
type service struct{ repo storage.Repository }
func New(r storage.Repository) todo.Service { return &service{repo: r} }
```

## 4. SQLite (pure-Go driver, no CGO)

This project uses **`modernc.org/sqlite`** (pure Go, builds without a C toolchain).
`database/sql` is the only SQL API.

```go
import _ "modernc.org/sqlite"            // registers driver "sqlite"
db, err := sql.Open("sqlite", "./data/todos.db")
db.ExecContext(ctx, "PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000;")
```

- Auto-create `./data/todos.db` and the schema on first run (`CREATE TABLE IF NOT EXISTS`).
- Use `context.Context` on every DB call; honor cancellation.
- `Scan` into typed fields, never `SELECT *` into `interface{}`.

## 5. Wire the server (main.go)

Adapt to whatever constructor/option names the v3 tgp-go `server` plugin emits —
inspect `internal/transport` after generation for the exact API. The shape is:

```go
func main() {
    db, _ := sql.Open("sqlite", "./data/todos.db")
    repo := sqlite.New(db)
    svc  := service.New(repo)
    srv  := transport.New( /* options incl. transport.NewService(svc) */ )
    go srv.Fiber().Listen("0.0.0.0:8000")
    <-blockForever()
}
```

**Listen address is `0.0.0.0:8000`, NEVER `127.0.0.1:8000`.** The service runs
inside a microsandbox VM; the host reaches it via msb port-forwarding, which
arrives on the VM's `eth0` (not loopback). Binding to `127.0.0.1` makes the port
map look open but every host request gets an empty reply (curl exit 52).
`0.0.0.0` binds all interfaces so port-forward works. This is a hard rule.

## Verification gate (this module feeds loki's VERIFY phase)

Before declaring a feature done — **all of these must pass**, in order:
- `go mod tidy` clean;
- `go vet ./...` clean;
- `go build ./...` clean;
- **`tg pkg list` shows `astg` + `server` installed** AND **`internal/transport/`
  exists and was produced by `tg server -o internal/transport`** (this is the
  hard gate — if the transport is hand-written, the task is NOT done);
- `github.com/seniorGolang/tg/v3` is a real line in `go.mod` (proves tg is wired
  in, not bypassed);
- one test per contract method (see tdd-rules.md), including a persistence test
  that closes + reopens the sqlite file and asserts data survived;
- `go run main.go` boots and the curl examples in README return the documented
  status codes (see api-contract-rules.md).

## Never

- **Hand-write fiber routes / handlers / `fiber.New()` / `app.Get/Post/...` for
  contract endpoints.** This is the #1 failure mode — falling back to hand-written
  fiber "because tg can't be installed". tg IS installed (`tg --version`); USE IT.
- Claim "tg has no resolvable versions" and skip codegen — that only happens if
  you drop the `/v3` suffix. The module is `github.com/seniorGolang/tg/v3`.
- Use v2 (`tg transport`) — this project is v3 (`tg server -o ...` via tgp-go).
- Skip regenerating `internal/transport` after editing a `// @tg` interface.
- Reach for CGO-backed `mattn/go-sqlite3` — use `modernc.org/sqlite`.
- Put SQL in the service layer — it lives in `storage/sqlite` only.
- **Import `github.com/seniorGolang/tg/v3/skills`** — that package does NOT exist
  in v3.0.5 (only `cmd/tg` is importable). If you pin the toolchain version in a
  build-tagged `tools.go`, import `github.com/seniorGolang/tg/v3/cmd/tg` — never
  `.../skills`, `.../agent`, or other invented subpackages. After writing tools.go,
  run `go mod tidy`; if it fails to resolve the import, the package does not exist.
