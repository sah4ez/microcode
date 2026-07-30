"""Database configuration and session management for SQLAlchemy."""
import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import SQLAlchemyError

# Database directory and file
DB_DIR = Path("./data")
DB_PATH = DB_DIR / "todos.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

# Create SQLAlchemy engine
# connect_args is needed for SQLite
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},  # Needed for SQLite in FastAPI
    echo=False
)

# Create SessionLocal class for database sessions
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Session:
    """
    Dependency function to get database session.

    Yields a database session and ensures it's closed after use.
    This is used with FastAPI's Depends().
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """
    Initialize the database by creating the data directory and all tables.

    This function creates the ./data directory if it doesn't exist,
    then creates all database tables defined in the models.
    """
    try:
        # Create data directory if it doesn't exist
        DB_DIR.mkdir(parents=True, exist_ok=True)

        # Import all models here to ensure they're registered with SQLAlchemy
        from todo_service.models import Base

        # Create all tables
        Base.metadata.create_all(bind=engine)

    except SQLAlchemyError as e:
        print(f"Database initialization error: {e}")
        raise
