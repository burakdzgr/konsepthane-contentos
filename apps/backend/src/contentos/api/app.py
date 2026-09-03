"""FastAPI application factory."""

from functools import partial

from fastapi import Depends, FastAPI

from contentos.api.error_handlers import install_error_handling
from contentos.api.middleware import RequestContextMiddleware
from contentos.api.routes.auth import router as auth_router
from contentos.api.routes.dashboard import router as dashboard_router
from contentos.api.routes.decisions import router as decisions_router
from contentos.api.routes.editorial import router as editorial_router
from contentos.api.routes.editorial_control import router as editorial_control_router
from contentos.api.routes.health import router as health_router
from contentos.api.routes.intake import router as intake_router
from contentos.api.routes.research import router as research_router
from contentos.api.routes.research_control import router as research_control_router
from contentos.api.security import require_operator, require_reviewer
from contentos.core.config import Settings
from contentos.core.logging import configure_logging
from contentos.db.session import create_database_engine, create_session_factory
from contentos.media.store import MediaStore
from contentos.queue.redis import create_redis_client
from contentos.worker.producer import (
    CeleryEditorialControlDispatcher,
    CeleryIntakeControlDispatcher,
    CeleryResearchControlDispatcher,
)


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
    app.state.settings = resolved_settings
    app.state.db_session_factory = create_session_factory(engine)
    # ContentOS-owned media byte store; the key layout stays internal.
    app.state.media_store = MediaStore(resolved_settings.media_store_root)
    app.state.redis_client_factory = partial(create_redis_client, resolved_settings)
    # Phase 5 G1: health stays open; login is the only other open route.
    # Every pipeline surface requires an authenticated OPERATOR session.
    operator_guard = [Depends(require_operator)]
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(research_router, dependencies=operator_guard)
    app.include_router(research_control_router, dependencies=operator_guard)
    app.include_router(editorial_router, dependencies=operator_guard)
    app.include_router(editorial_control_router, dependencies=operator_guard)
    app.include_router(dashboard_router, dependencies=operator_guard)
    app.include_router(intake_router, dependencies=operator_guard)
    # Human decisions require the REVIEWER role (ADR 0004): a pure reviewer
    # may decide without being able to drive the pipeline, and vice versa.
    app.include_router(decisions_router, dependencies=[Depends(require_reviewer)])
    # Producer-only dispatchers for explicit operator job triggers; lazy, so
    # creating the app never touches Redis. Tests replace them on app.state.
    app.state.research_control_dispatcher = CeleryResearchControlDispatcher(resolved_settings)
    app.state.editorial_control_dispatcher = CeleryEditorialControlDispatcher(resolved_settings)
    app.state.intake_control_dispatcher = CeleryIntakeControlDispatcher(resolved_settings)
    # RequestContextMiddleware must stay outermost so the request ID context and
    # X-Request-ID header also cover envelope responses for unhandled errors.
    app.add_middleware(RequestContextMiddleware)
    return app
