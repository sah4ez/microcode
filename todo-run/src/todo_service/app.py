"""FastAPI application and route handlers for the Todo Service."""
from typing import List
from fastapi import FastAPI, Depends, HTTPException, status
from sqlalchemy.orm import Session

from todo_service.db import get_db, init_db
from todo_service.models import Todo
from todo_service.schemas import TodoCreate, TodoUpdate, TodoResponse


# Initialize FastAPI application
app = FastAPI(
    title="Todo Service",
    description="A minimal todo-list REST service with local SQLite persistence",
    version="1.0.0"
)


# Event handler: Initialize database on startup
@app.on_event("startup")
def on_startup():
    """Initialize the database when the application starts."""
    init_db()


@app.post("/todos", response_model=TodoResponse, status_code=status.HTTP_201_CREATED)
def create_todo(todo: TodoCreate, db: Session = Depends(get_db)) -> Todo:
    """
    Create a new todo item.

    Args:
        todo: The todo data from the request body
        db: Database session (injected by FastAPI)

    Returns:
        The created todo with generated id and timestamp
    """
    db_todo = Todo(
        title=todo.title,
        description=todo.description,
        completed=False  # Default value
    )
    db.add(db_todo)
    db.commit()
    db.refresh(db_todo)
    return db_todo


@app.get("/todos", response_model=List[TodoResponse])
def list_todos(db: Session = Depends(get_db)) -> List[Todo]:
    """
    List all todos, ordered by creation time (newest first).

    Args:
        db: Database session (injected by FastAPI)

    Returns:
        List of all todos in the database
    """
    todos = db.query(Todo).order_by(Todo.created_at.desc()).all()
    return todos


@app.get("/todos/{todo_id}", response_model=TodoResponse)
def get_todo(todo_id: int, db: Session = Depends(get_db)) -> Todo:
    """
    Get a single todo by its ID.

    Args:
        todo_id: The ID of the todo to retrieve
        db: Database session (injected by FastAPI)

    Returns:
        The requested todo

    Raises:
        HTTPException: If the todo is not found (404)
    """
    todo = db.query(Todo).filter(Todo.id == todo_id).first()
    if not todo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Todo with id {todo_id} not found"
        )
    return todo


@app.patch("/todos/{todo_id}", response_model=TodoResponse)
def update_todo(todo_id: int, todo_update: TodoUpdate, db: Session = Depends(get_db)) -> Todo:
    """
    Update a todo (partial updates supported).

    Only provided fields are updated. Missing fields remain unchanged.

    Args:
        todo_id: The ID of the todo to update
        todo_update: The fields to update
        db: Database session (injected by FastAPI)

    Returns:
        The updated todo

    Raises:
        HTTPException: If the todo is not found (404)
    """
    db_todo = db.query(Todo).filter(Todo.id == todo_id).first()
    if not db_todo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Todo with id {todo_id} not found"
        )

    # Update only the fields that are provided (not None)
    update_data = todo_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_todo, field, value)

    db.commit()
    db.refresh(db_todo)
    return db_todo


@app.delete("/todos/{todo_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_todo(todo_id: int, db: Session = Depends(get_db)) -> None:
    """
    Delete a todo by its ID.

    Args:
        todo_id: The ID of the todo to delete
        db: Database session (injected by FastAPI)

    Raises:
        HTTPException: If the todo is not found (404)
    """
    db_todo = db.query(Todo).filter(Todo.id == todo_id).first()
    if not db_todo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Todo with id {todo_id} not found"
        )

    db.delete(db_todo)
    db.commit()


@app.post("/todos/{todo_id}/toggle", response_model=TodoResponse)
def toggle_todo(todo_id: int, db: Session = Depends(get_db)) -> Todo:
    """
    Toggle the completed status of a todo.

    Flips the completed boolean from true to false or vice versa.

    Args:
        todo_id: The ID of the todo to toggle
        db: Database session (injected by FastAPI)

    Returns:
        The updated todo with flipped completed status

    Raises:
        HTTPException: If the todo is not found (404)
    """
    db_todo = db.query(Todo).filter(Todo.id == todo_id).first()
    if not db_todo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Todo with id {todo_id} not found"
        )

    # Toggle the completed status
    db_todo.completed = not db_todo.completed
    db.commit()
    db.refresh(db_todo)
    return db_todo
