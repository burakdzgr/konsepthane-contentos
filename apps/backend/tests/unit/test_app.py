"""Tests for the minimal FastAPI application factory."""

from fastapi import FastAPI

import contentos
from contentos.api.app import create_app
from contentos.core.config import Environment, LogLevel, Settings


def test_create_app_uses_supplied_settings() -> None:
    settings = Settings(
        environment=Environment.TEST,
        service_name="ContentOS Test Service",
        application_version="9.8.7",
        log_level=LogLevel.DEBUG,
        api_docs_enabled=True,
    )

    app = create_app(settings=settings)

    assert contentos.__version__ == "0.1.0"
    assert isinstance(app, FastAPI)
    assert app.title == "ContentOS Test Service"
    assert app.version == "9.8.7"


def test_create_app_disables_api_documentation() -> None:
    settings = Settings(
        environment=Environment.TEST,
        service_name="ContentOS Test Service",
        application_version="9.8.7",
        log_level=LogLevel.INFO,
        api_docs_enabled=False,
    )

    app = create_app(settings=settings)

    assert app.docs_url is None
    assert app.redoc_url is None
    assert app.openapi_url is None
