"""Comprehensive pytest suite for the Todo Service."""
import tempfile
import shutil
from pathlib import Path
from datetime import datetime

import pytest
from httpx import Client, ASGITransport

from todo_service.app import app
from todo_service.db import init_db, SessionLocal, get_db
from todo_service.models import Todo, Base


# ============================================
# Test Fixtures
# ============================================

@pytest.fixture(scope="function")
def test_db_dir(tmp_path):
    """
    Create a temporary directory for the test database.

    The database is created fresh for each test function.
    """
    db_dir = tmp_path / "test_data"
    db_dir.mkdir()
    yield db_dir
    # Cleanup: remove the test database directory
    if db_dir.exists():
        shutil.rmtree(db_dir)


@pytest.fixture(scope="function")
def test_engine(test_db_dir):
    """
    Create a test database engine with a temporary SQLite file.
    """
    from sqlalchemy import create_engine

    test_db_path = test_db_dir / "test_todos.db"
    engine = create_engine(
        f"sqlite:///{test_db_path}",
        connect_args={"check_same_thread": False}
    )

    # Create tables
    Base.metadata.create_all(bind=engine)

    yield engine

    # Cleanup: drop all tables
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def test_db_session(test_engine):
    """
    Create a test database session.
    """
    from sqlalchemy.orm import sessionmaker

    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    session = TestSessionLocal()

    yield session

    session.close()


@pytest.fixture(scope="function")
def test_client(test_db_session):
    """
    Create a test HTTP client that overrides the database dependency.
    """
    def override_get_db():
        yield test_db_session

    # Override the database dependency
    app.dependency_overrides[get_db] = override_get_db

    # Create ASGI transport for httpx
    transport = ASGITransport(app=app)
    with Client(transport=transport, base_url="http://test") as client:
        yield client

    # Clean up overrides
    app.dependency_overrides.clear()


# ============================================
# POST /todos Tests
# ============================================

def test_create_todo(test_client):
    """Test creating a new todo with valid data."""
    response = test_client.post(
        "/todos",
        json={"title": "Test Todo", "description": "Test description"}
    )

    assert response.status_code == 201

    data = response.json()
    assert data["title"] == "Test Todo"
    assert data["description"] == "Test description"
    assert data["completed"] is False
    assert "id" in data
    assert "created_at" in data


def test_create_todo_without_description(test_client):
    """Test creating a todo without a description (optional field)."""
    response = test_client.post(
        "/todos",
        json={"title": "Todo without description"}
    )

    assert response.status_code == 201

    data = response.json()
    assert data["title"] == "Todo without description"
    assert data["description"] is None
    assert data["completed"] is False


def test_create_todo_missing_title(test_client):
    """Test creating a todo without a title returns 422 validation error."""
    response = test_client.post(
        "/todos",
        json={"description": "Missing title"}
    )

    assert response.status_code == 422


def test_create_todo_empty_title(test_client):
    """Test creating a todo with empty title."""
    response = test_client.post(
        "/todos",
        json={"title": "", "description": "Empty title test"}
    )

    # Empty string is still valid for title (it's a string)
    # But if we want to reject it, we'd add validator
    assert response.status_code == 201


# ============================================
# GET /todos Tests
# ============================================

def test_list_todos_empty(test_client):
    """Test listing todos when database is empty."""
    response = test_client.get("/todos")

    assert response.status_code == 200
    assert response.json() == []


def test_list_todos_multiple(test_client, test_db_session):
    """Test listing multiple todos."""
    # Create test todos directly in the database
    todo1 = Todo(title="First todo", description="First", completed=False)
    todo2 = Todo(title="Second todo", description="Second", completed=True)
    test_db_session.add_all([todo1, todo2])
    test_db_session.commit()

    response = test_client.get("/todos")

    assert response.status_code == 200

    todos = response.json()
    assert len(todos) == 2

    # Check that todos are ordered by created_at descending
    # The second one added should be first (newest)
    assert todos[0]["title"] == "Second todo"
    assert todos[1]["title"] == "First todo"


def test_list_todos_includes_all_fields(test_client, test_db_session):
    """Test that GET /todos returns all expected fields."""
    todo = Todo(
        title="Complete todo",
        description="Full description",
        completed=True
    )
    test_db_session.add(todo)
    test_db_session.commit()

    response = test_client.get("/todos")

    assert response.status_code == 200

    todos = response.json()
    assert len(todos) == 1

    todo_data = todos[0]
    assert "id" in todo_data
    assert "title" in todo_data
    assert "description" in todo_data
    assert "completed" in todo_data
    assert "created_at" in todo_data


# ============================================
# GET /todos/{id} Tests
# ============================================

def test_get_todo_by_id(test_client, test_db_session):
    """Test getting a single todo by its ID."""
    todo = Todo(title="Specific todo", description="Find me", completed=False)
    test_db_session.add(todo)
    test_db_session.commit()

    # Get the ID from the created todo
    todo_id = todo.id

    response = test_client.get(f"/todos/{todo_id}")

    assert response.status_code == 200

    data = response.json()
    assert data["id"] == todo_id
    assert data["title"] == "Specific todo"
    assert data["description"] == "Find me"
    assert data["completed"] is False


def test_get_todo_not_found(test_client):
    """Test getting a non-existent todo returns 404."""
    response = test_client.get("/todos/99999")

    assert response.status_code == 404

    assert "not found" in response.json()["detail"].lower()


def test_get_todo_invalid_id(test_client):
    """Test getting a todo with invalid ID format."""
    response = test_client.get("/todos/invalid")

    # FastAPI returns 422 for invalid path parameter types
    assert response.status_code == 422


# ============================================
# PATCH /todos/{id} Tests
# ============================================

def test_update_todo_title(test_client, test_db_session):
    """Test updating just the title of a todo."""
    todo = Todo(title="Old title", description="Description", completed=False)
    test_db_session.add(todo)
    test_db_session.commit()

    todo_id = todo.id

    response = test_client.patch(
        f"/todos/{todo_id}",
        json={"title": "New title"}
    )

    assert response.status_code == 200

    data = response.json()
    assert data["id"] == todo_id
    assert data["title"] == "New title"
    assert data["description"] == "Description"
    assert data["completed"] is False


def test_update_todo_completed(test_client, test_db_session):
    """Test updating the completed status of a todo."""
    todo = Todo(title="Task", description="Do this", completed=False)
    test_db_session.add(todo)
    test_db_session.commit()

    todo_id = todo.id

    response = test_client.patch(
        f"/todos/{todo_id}",
        json={"completed": True}
    )

    assert response.status_code == 200

    data = response.json()
    assert data["completed"] is True
    assert data["title"] == "Task"  # Other fields unchanged


def test_update_todo_multiple_fields(test_client, test_db_session):
    """Test updating multiple fields at once."""
    todo = Todo(title="Old", description="Old desc", completed=False)
    test_db_session.add(todo)
    test_db_session.commit()

    todo_id = todo.id

    response = test_client.patch(
        f"/todos/{todo_id}",
        json={"title": "New", "description": "New desc", "completed": True}
    )

    assert response.status_code == 200

    data = response.json()
    assert data["title"] == "New"
    assert data["description"] == "New desc"
    assert data["completed"] is True


def test_update_todo_not_found(test_client):
    """Test updating a non-existent todo returns 404."""
    response = test_client.patch(
        "/todos/99999",
        json={"title": "Won't work"}
    )

    assert response.status_code == 404


# ============================================
# DELETE /todos/{id} Tests
# ============================================

def test_delete_todo(test_client, test_db_session):
    """Test deleting a todo."""
    todo = Todo(title="Delete me", description="Temporary", completed=False)
    test_db_session.add(todo)
    test_db_session.commit()

    todo_id = todo.id

    response = test_client.delete(f"/todos/{todo_id}")

    assert response.status_code == 204
    assert response.content == b""  # No body on 204


def test_delete_todo_not_found(test_client):
    """Test deleting a non-existent todo returns 404."""
    response = test_client.delete("/todos/99999")

    assert response.status_code == 404


def test_deleted_todo_not_in_list(test_client, test_db_session):
    """Test that deleted todo is not returned in GET /todos."""
    todo = Todo(title="Going away", description="Soon to be deleted", completed=False)
    test_db_session.add(todo)
    test_db_session.commit()

    todo_id = todo.id

    # Verify it's in the list before deletion
    response = test_client.get("/todos")
    assert len(response.json()) == 1

    # Delete it
    test_client.delete(f"/todos/{todo_id}")

    # Verify it's no longer in the list
    response = test_client.get("/todos")
    assert len(response.json()) == 0


def test_get_deleted_todo_returns_404(test_client, test_db_session):
    """Test that getting a deleted todo returns 404."""
    todo = Todo(title="Delete then get", description="Test", completed=False)
    test_db_session.add(todo)
    test_db_session.commit()

    todo_id = todo.id

    # Delete the todo
    test_client.delete(f"/todos/{todo_id}")

    # Try to get it - should return 404
    response = test_client.get(f"/todos/{todo_id}")
    assert response.status_code == 404


# ============================================
# POST /todos/{id}/toggle Tests
# ============================================

def test_toggle_todo_from_false_to_true(test_client, test_db_session):
    """Test toggling an incomplete todo to complete."""
    todo = Todo(title="Task", description="Do it", completed=False)
    test_db_session.add(todo)
    test_db_session.commit()

    todo_id = todo.id

    response = test_client.post(f"/todos/{todo_id}/toggle")

    assert response.status_code == 200

    data = response.json()
    assert data["completed"] is True
    assert data["id"] == todo_id


def test_toggle_todo_from_true_to_false(test_client, test_db_session):
    """Test toggling a complete todo back to incomplete."""
    todo = Todo(title="Done task", description="Already done", completed=True)
    test_db_session.add(todo)
    test_db_session.commit()

    todo_id = todo.id

    response = test_client.post(f"/todos/{todo_id}/toggle")

    assert response.status_code == 200

    data = response.json()
    assert data["completed"] is False


def test_toggle_todo_not_found(test_client):
    """Test toggling a non-existent todo returns 404."""
    response = test_client.post("/todos/99999/toggle")

    assert response.status_code == 404


# ============================================
# Persistence Tests
# ============================================

def test_data_persists_across_restart(test_client, test_db_session):
    """Test that data survives closing and reopening the database connection."""
    # Create a todo
    response = test_client.post(
        "/todos",
        json={"title": "Persistent todo", "description": "Should survive restart"}
    )
    assert response.status_code == 201

    todo_id = response.json()["id"]

    # Verify it exists
    response = test_client.get(f"/todos/{todo_id}")
    assert response.status_code == 200

    # Simulate restart by closing and reopening the session
    test_db_session.close()
    test_db_session.bind.connect()
    test_db_session.expire_all()

    # Verify the todo still exists after "restart"
    response = test_client.get(f"/todos/{todo_id}")
    assert response.status_code == 200

    data = response.json()
    assert data["id"] == todo_id
    assert data["title"] == "Persistent todo"


# ============================================
# Edge Cases
# ============================================

def test_long_title(test_client, test_db_session):
    """Test creating a todo with a very long title (within limits)."""
    long_title = "A" * 500  # Max length
    response = test_client.post(
        "/todos",
        json={"title": long_title, "description": "Long title test"}
    )

    assert response.status_code == 201

    data = response.json()
    assert len(data["title"]) == 500


def test_long_description(test_client, test_db_session):
    """Test creating a todo with a very long description (within limits)."""
    long_description = "B" * 2000  # Max length
    response = test_client.post(
        "/todos",
        json={"title": "Todo", "description": long_description}
    )

    assert response.status_code == 201

    data = response.json()
    assert len(data["description"]) == 2000


def test_special_characters_in_fields(test_client):
    """Test that special characters are handled properly."""
    special_title = "Todo with émojis 🎉 and spëcial çhars"
    special_desc = "Description with \"quotes\" and 'apostrophes' & symbols"

    response = test_client.post(
        "/todos",
        json={"title": special_title, "description": special_desc}
    )

    assert response.status_code == 201

    data = response.json()
    assert data["title"] == special_title
    assert data["description"] == special_desc
