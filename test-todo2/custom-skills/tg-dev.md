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
- `tg` v3 CLI at `/usr/local/bin/tg`.
- transport plugin `tgp-go` installed via `tg pkg add` (plugins: `astg` parser,
  `server` = Fiber server, `client-go`, `client-ts`, `swagger`).
- built-in agent skills via `tg skills install`.

Confirm before coding: `go version` (≥1.26), `tg --version`, `tg plugin doc server`.

## Project rule: tg is the ONLY way to expose HTTP here

Every HTTP endpoint on this project is defined as a method on a `// @tg`-annotated
interface and served by the generated fiber transport. Do **not** register routes
by hand with `fiber.New()` — let codegen own routing. Access the running app via
the generated `srv.Fiber()` only when you must.

## Module bootstrap

```bash
go mod init github.com/<you>/<service>          # once
go get github.com/seniorGolang/tg/v3@latest     # the framework (v3!)
# tg CLI + tgp-go are already installed in the VM; no go install needed.
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

In v3 the transport is built by the **tgp-go** plugin via `go generate ./...`.
The plugin (WASM, runs on wazero) parses the `// @tg` interfaces and emits the
fiber server/client/swagger. Two equivalent ways to trigger it:

```bash
# (a) project-wide: the plugin registers `go generate` directives.
go generate ./...

# (b) explicit plugin invocation (if the project has no go:generate lines):
tg plugin run server    # generate the Fiber server into internal/transport
tg plugin run client-go # optional: typed Go client (use it in tests!)
tg plugin run swagger   # optional: OpenAPI 3.0 to api/swagger.yaml
```

If unsure which subcommand/flags a plugin takes, inspect it: `tg plugin doc server`.
Re-run after **every** contract change. Commit the generated tree (never edit it
by hand).

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
    go srv.Fiber().Listen(":8000")
    <-blockForever()
}
```

## Verification gate (this module feeds loki's VERIFY phase)

Before declaring a feature done:
- `go vet ./...` clean;
- `go build ./...` clean;
- transport regenerated (`go generate ./...`) and the generated tree committed;
- one test per contract method (see tdd-rules.md), including a persistence test
  that closes + reopens the sqlite file and asserts data survived;
- `go run ./cmd/server` boots and the curl examples in README return the
  documented status codes (see api-contract-rules.md).

## Never

- Use v2 (`tg transport`) — this project is v3 (`go generate` via tgp-go).
- Hand-write fiber routes for contract endpoints — codegen owns them.
- Skip regenerating `internal/transport` after editing a `// @tg` interface.
- Reach for CGO-backed `mattn/go-sqlite3` — use `modernc.org/sqlite`.
- Put SQL in the service layer — it lives in `storage/sqlite` only.
