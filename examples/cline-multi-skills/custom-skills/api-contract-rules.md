### api-contract-rules.md
**When:** Writing HTTP endpoints, request/response validation, API design

Unified style for this project's HTTP API:
- Every request body and response is a Pydantic model. No bare dicts.
- Status codes follow RFC 9110 semantics:
  200 OK (GET/PUT success), 201 Created (POST), 204 No Content (DELETE),
  400 Bad Request, 404 Not Found, 409 Conflict, 422 Unprocessable Entity.
- Every endpoint has a one-line docstring + a test (per tdd-rules.md).
- Validate input at the boundary; trust nothing past the Pydantic model.
- Persist via the repository pattern, not direct SQL in the handler.
- Errors are a single `{"detail": "<message>"}` shape (FastAPI default).
