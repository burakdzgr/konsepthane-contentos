"""FastAPI application factory."""

from fastapi import FastAPI

from contentos.core.config import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create a FastAPI application without import-time initialization."""
    resolved_settings = settings if settings is not None else Settings()
    docs_url = "/docs" if resolved_settings.api_docs_enabled else None
    redoc_url = "/redoc" if resolved_settings.api_docs_enabled else None
    openapi_url = "/openapi.json" if resolved_settings.api_docs_enabled else None

    return FastAPI(
        title=resolved_settings.service_name,
        version=resolved_settings.application_version,
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url,
    )
