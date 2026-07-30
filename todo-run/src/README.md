# Todo Service

A minimal todo-list REST service with local SQLite persistence. Built with FastAPI, SQLAlchemy, and Pydantic.

## Features

- **Create** new todos with title and description
- **List** all todos
- **Get** a specific todo by ID
- **Update** todo fields (title, description, completed status)
- **Delete** todos
- **Toggle** completion status with a dedicated endpoint
- **Persistent storage** using SQLite database at `./data/todos.db`

## Installation

1. Install dependencies:
```bash
pip install -r requirements.txt
```

## Running the Server

Start the server with either command:

```bash
python -m todo_service
```

or:

```bash
uvicorn todo_service.app:app --host 127.0.0.1 --port 8000
```

The server will start on `http://127.0.0.1:8000`

## API Endpoints

### Create a Todo
```bash
curl -X POST http://127.0.0.1:8000/todos \
  -H "Content-Type: application/json" \
  -d '{"title": "Buy groceries", "description": "Milk, eggs, bread"}'
```

Response:
```json
{
  "id": 1,
  "title": "Buy groceries",
  "description": "Milk, eggs, bread",
  "completed": false,
  "created_at": "2024-01-15T10:30:00"
}
```

### List All Todos
```bash
curl http://127.0.0.1:8000/todos
```

Response:
```json
[
  {
    "id": 1,
    "title": "Buy groceries",
    "description": "Milk, eggs, bread",
    "completed": false,
    "created_at": "2024-01-15T10:30:00"
  }
]
```

### Get a Specific Todo
```bash
curl http://127.0.0.1:8000/todos/1
```

Response:
```json
{
  "id": 1,
  "title": "Buy groceries",
  "description": "Milk, eggs, bread",
  "completed": false,
  "created_at": "2024-01-15T10:30:00"
}
```

### Update a Todo
```bash
curl -X PATCH http://127.0.0.1:8000/todos/1 \
  -H "Content-Type: application/json" \
  -d '{"completed": true}'
```

Response:
```json
{
  "id": 1,
  "title": "Buy groceries",
  "description": "Milk, eggs, bread",
  "completed": true,
  "created_at": "2024-01-15T10:30:00"
}
```

### Delete a Todo
```bash
curl -X DELETE http://127.0.0.1:8000/todos/1
```

Response: `204 No Content`

### Toggle Complete Status
```bash
curl -X POST http://127.0.0.1:8000/todos/1/toggle
```

Response:
```json
{
  "id": 1,
  "title": "Buy groceries",
  "description": "Milk, eggs, bread",
  "completed": true,
  "created_at": "2024-01-15T10:30:00"
}
```

## Testing

Run the test suite:

```bash
pytest -q
```

The tests cover:
- Creating todos
- Listing all todos
- Getting specific todos
- Updating todos
- Deleting todos
- Toggling completion status
- Data persistence across restarts
- Edge cases and validation

## Project Structure

```
.
├── todo_service/
│   ├── __init__.py
│   ├── __main__.py       # Entry point for `python -m todo_service`
│   ├── app.py            # FastAPI application and routes
│   ├── db.py             # Database configuration and session management
│   ├── models.py         # SQLAlchemy models
│   └── schemas.py        # Pydantic schemas
├── tests/
│   ├── __init__.py
│   └── test_todos.py     # Comprehensive test suite
├── data/
│   └── todos.db          # SQLite database (auto-created)
├── requirements.txt
├── README.md
└── USAGE.md
```

## Database

The service uses SQLite for local persistence. The database file is created at `./data/todos.db` on first run.

**Schema:**
- `id`: Integer primary key (auto-increment)
- `title`: String (required, max 500 chars)
- `description`: String (optional, max 2000 chars)
- `completed`: Boolean (default: False)
- `created_at`: DateTime (default: current time)

## Dependencies

- **FastAPI** (0.115.0) - Web framework
- **Uvicorn** (0.32.0) - ASGI server
- **SQLAlchemy** (2.0.35) - ORM
- **Pydantic** (2.9.2) - Data validation
- **pytest** (8.3.3) - Testing framework
- **httpx** (0.27.2) - Async HTTP client for testing
