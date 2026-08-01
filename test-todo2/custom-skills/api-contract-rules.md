### api-contract-rules.md
**When:** Writing HTTP endpoints, request/response validation, API design (Go + tg)

Unified style for this project's HTTP API. Endpoints are declared on a `// @tg`-
annotated interface (see tg-dev.md); this module governs the request/response
shapes, status codes, and error contract the generator + your handlers emit.

## Status codes (RFC 9110 semantics)

| Method | Success | On miss | On bad input |
|---|---|---|---|
| `POST /todos` | **201 Created** + body | n/a | 422 |
| `GET /todos` | 200 + `[]Todo` | 200 + `[]` | n/a |
| `GET /todos/:id` | 200 + `Todo` | **404** | 422 |
| `PATCH /todos/:id` | 200 + `Todo` | 404 | 422 |
| `DELETE /todos/:id` | **204 No Content** (empty body) | 404 | n/a |
| `POST /todos/:id/toggle` | 200 + `Todo` | 404 | n/a |

- Use the `http-success=<code>` tg tag on the contract method to set the non-default
  codes (201 for Create, 204 for Delete). Default is 200.
- 404 vs 422 distinction matters: 404 = resource id not found; 422 = semantically
  invalid payload (e.g. empty title on create).

## Request / response shapes

- Every request body and every response is a Go **struct with `json:` tags**.
  No bare `map[string]any`, no `interface{}` bodies.
- Field names are `snake_case` in JSON, `CamelCase` in Go:
  ```go
  type Todo struct {
      ID          int64  `json:"id"`
      Title       string `json:"title"`
      Description string `json:"description"`
      Completed   bool   `json:"completed"`
      CreatedAt   string `json:"created_at"`
  }
  ```
- `created_at` is an RFC3339 string (UTC). `id` is `int64`.
- Path params live in their own request struct with a `path:"id"` tag; body fields
  in the same struct with `json:"..."` tags. Keep one request struct per method.

## Error contract

Single, consistent error body everywhere:

```json
{ "error": "todo not found" }
```

```go
type ErrorResponse struct {
    Error string `json:"error"`
}
```

- Map domain errors to HTTP status at the service boundary (the generated
  transport passes through the error; return it from the handler so the fiber
  error handler can format it). Use typed sentinel errors:
  ```go
  var ErrNotFound = errors.New("todo not found")
  ```
- Never leak internal SQL text or stack traces in the error string. Map
  `sql.ErrNoRows` → `ErrNotFound` in the repository, not in the handler.

## Validation

- Validate at the boundary (the contract request struct). Use the `tg:"required"`
  tag for non-zero fields; reject empty `title` on Create with 422.
- Trust nothing past the request struct — handlers/transport receive validated
  values.

## Persistence boundary

- Handlers → service → repository. **No SQL in handlers or service.** SQL lives
  in `internal/storage/sqlite` only (see tg-dev.md).

## Docs & tests

- Every contract method has a one-line godoc comment + a tg `desc=` annotation.
- Every contract method has at least one test (see tdd-rules.md) asserting both
  the success status code AND the error status code (e.g. Create returns 201;
  Create with empty title returns 422; Get on missing id returns 404).
