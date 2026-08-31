"""FastAPI application factory."""

from fastapi import FastAPI

from contentos import __version__

APP_TITLE = "Konsepthane ContentOS"


def create_app() -> FastAPI:
    """Create a FastAPI application without import-time initialization."""
    return FastAPI(title=APP_TITLE, version=__version__)
