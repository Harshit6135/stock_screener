"""Stable WSGI launcher for the application gates."""

from src.gates.app import configure_logging, create_app, main

__all__ = ["configure_logging", "create_app", "main"]

if __name__ == "__main__":
    main()
