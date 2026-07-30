"""SQLAlchemy models for the Todo Service."""
from datetime import datetime
from sqlalchemy import Boolean, Column, Integer, String, DateTime
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models."""
    pass


class Todo(Base):
    """
    Todo model representing a todo item in the database.

    Attributes:
        id: Auto-incrementing primary key
        title: The title of the todo (required)
        description: Optional description of the todo
        completed: Boolean flag for completion status (default: False)
        created_at: Timestamp when the todo was created (default: current time)
    """
    __tablename__ = "todos"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(500), nullable=False)
    description = Column(String(2000), nullable=True)
    completed = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<Todo(id={self.id}, title='{self.title}', completed={self.completed})>"
