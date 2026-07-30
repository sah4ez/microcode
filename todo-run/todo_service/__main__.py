"""Entry point for running the Todo Service with `python -m todo_service`."""
import uvicorn
from todo_service.db import init_db


def main():
    """Initialize the database and start the uvicorn server."""
    # Initialize database (create directory and tables if needed)
    init_db()

    # Start uvicorn server
    uvicorn.run(
        "todo_service.app:app",
        host="127.0.0.1",
        port=8000,
        reload=False  # Disable auto-reload for production use
    )


if __name__ == "__main__":
    main()
