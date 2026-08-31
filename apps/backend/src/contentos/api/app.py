"""FastAPI application factory."""

from fastapi import FastAPI

from contentos.api.error_handlers import install_error_handling
from contentos.api.middleware import RequestContextMiddleware
from contentos.core.config import Settings
from contentos.core.logging import configure_logging
from contentos.db.session import create_database_engine, create_session_factory


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create a FastAPI application without import-time initialization."""
    resolved_settings = settings if settings is not None else Settings()
    configure_logging(resolved_settings)
    docs_url = "/docs" if resolved_settings.api_docs_enabled else None
    redoc_url = "/redoc" if resolved_settings.api_docs_enabled else None
    openapi_url = "/openapi.json" if resolved_settings.api_docs_enabled else None

    app = FastAPI(
        title=resolved_settings.service_name,
        version=resolved_settings.application_version,
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url,
    )
    install_error_handling(app)
    # Engine creation is lazy: no database connection happens until first use.
    engine = create_database_engine(resolved_settings)
    app.state.db_session_factory = create_session_factory(engine)
    # RequestContextMiddleware must stay outermost so the request ID context and
    # X-Request-ID header also cover envelope responses for unhandled errors.
    app.add_middleware(RequestContextMiddleware)
    return app
