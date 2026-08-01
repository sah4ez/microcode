### tdd-rules.md
**When:** Implementing any feature/bugfix, BEFORE writing implementation code (Go)

Hard rules (overlay on top of loki's built-in testing.md), Go edition:

- RED-GREEN-REFACTOR, always. Write the test first, watch it FAIL (`go test`),
  then implement. `go test ./...` is the red/green signal.
- If you didn't watch the test fail, you don't know if it tests the right thing.
- Never delete or weaken a failing test. Fix the code, not the test.
- No mocks where real behavior is cheap to exercise. This project uses a **real
  SQLite file** (temp dir per test via `t.TempDir()`) — exercise the real
  repository + real transport, never an interface mock. Reserve mocks for
  external network only (there is none here).
- **Table-driven tests** for handler/contract behavior:
  ```go
  func TestCreate_statusCodes(t *testing.T) {
      cases := []struct{
          name string
          body string
          want int
      }{
          {"valid",    `{"title":"x"}`, http.StatusCreated},
          {"no title", `{}`,             http.StatusUnprocessableEntity},
      }
      for _, c := range cases {
          t.Run(c.name, func(t *testing.T) { /* ... assert c.want ... */ })
      }
  }
  ```
- One behavior per test. Name tests `Test<Unit>_<Condition>_<Expected>`.
- Tests live next to the code: `service.go` → `service_test.go` in the same
  package. Integration tests that boot the fiber app go in `cmd/server` or a
  top-level `testdata` package.

## Required test inventory (PRD-001 Definition of Done)

The suite MUST cover, at minimum:

1. **Create** — `POST /todos` returns 201, body has `id`, `created_at`,
   `completed=false`.
2. **List** — `GET /todos` returns the previously created todo.
3. **Get** — `GET /todos/{id}` returns it; 404 on unknown id.
4. **Update** — `PATCH /todos/{id}` edits title/description and toggles
   `completed`; 404 on unknown id.
5. **Delete** — `DELETE /todos/{id}` returns 204; subsequent Get returns 404.
6. **Toggle** — `POST /todos/{id}/toggle` flips `completed` and returns the todo.
7. **Persistence across restart** — create a todo, close the DB / stop the
   server, reopen the DB file / restart the server, assert the todo is still
   there. This is the load-bearing non-functional requirement.

## Persistence test pattern (the must-have)

```go
func TestRepository_persistsAcrossReopen(t *testing.T) {
    dbPath := filepath.Join(t.TempDir(), "todos.db")

    // first session: create
    db1, _ := sql.Open("sqlite", dbPath)
    r1 := sqlite.New(db1)
    created, _ := r1.Create(ctx, Todo{Title: "persist me"})
    db1.Close()

    // second session: reopen the SAME file, data must survive
    db2, _ := sql.Open("sqlite", dbPath)
    r2 := sqlite.New(db2)
    got, err := r2.Get(ctx, created.ID)
    require.NoError(t, err)
    require.Equal(t, "persist me", got.Title)
}
```

## HTTP-level test pattern (use the generated client or net/http)

Prefer the **generated Go client** (`tg client -go`) against the booted fiber app
so you exercise the real transport + serialization:

```go
srv := bootTestServer(t)            // fiber on a random port, temp sqlite
cli := client.New(srv.URL)
todo, err := cli.Create(ctx, client.CreateRequest{Title: "x"})
require.NoError(t, err)
require.NotZero(t, todo.ID)
```

For status-code assertions the generated client doesn't surface, fall back to
`net/http` + `httptest` against `srv.Fiber().Handler()`.

## Verify gate (this module feeds loki's VERIFY phase)

- `go vet ./...` is clean.
- `go test ./...` is green — including the persistence-reopen test.
- Every public function/type has at least one test.
- `go test -race ./...` is green where concurrency is involved.
