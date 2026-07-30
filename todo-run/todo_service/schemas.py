"""Pydantic schemas for request validation and response serialization."""
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict


class TodoCreate(BaseModel):
    """
    Schema for creating a new todo via POST /todos.

    Attributes:
        title: The title of the todo (required, max 500 chars)
        description: Optional description of the todo (max 2000 chars)
    """
    title: str = Field(..., max_length=500, description="The title of the todo")
    description: str | None = Field(
        None,
        max_length=2000,
        description="Optional description of the todo"
    )


class TodoUpdate(BaseModel):
    """
    Schema for updating a todo via PATCH /todos/{id}.

    All fields are optional to support partial updates.

    Attributes:
        title: Optional new title (max 500 chars)
        description: Optional new description (max 2000 chars)
        completed: Optional completion status
    """
    title: str | None = Field(None, max_length=500)
    description: str | None = Field(None, max_length=2000)
    completed: bool | None = Field(None, description="Toggle completion status")


class TodoResponse(BaseModel):
    """
    Schema for todo responses from the API.

    This schema is used for GET responses and POST/PATCH return values.

    Attributes:
        id: The unique identifier of the todo
        title: The title of the todo
        description: The description of the todo (can be None)
        completed: Whether the todo is completed
        created_at: When the todo was created
    """
    id: int
    title: str
    description: str | None
    completed: bool
    created_at: datetime

    # Configure Pydantic to work with SQLAlchemy ORM models
    model_config = ConfigDict(from_attributes=True)
