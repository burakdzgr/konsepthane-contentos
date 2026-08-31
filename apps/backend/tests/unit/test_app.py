"""Tests for the minimal FastAPI application factory."""

from fastapi import FastAPI

import contentos
from contentos.api.app import APP_TITLE, create_app


def test_create_app_returns_fastapi_with_expected_metadata() -> None:
    app = create_app()

    assert contentos.__version__ == "0.1.0"
    assert isinstance(app, FastAPI)
    assert app.title == APP_TITLE
    assert app.version == contentos.__version__
