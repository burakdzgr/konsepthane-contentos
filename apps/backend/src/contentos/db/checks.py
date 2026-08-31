"""Bounded PostgreSQL readiness checks for ContentOS-owned storage."""

import structlog
from sqlalchemy import text

from contentos.db.session import SessionFactory, session_scope

_logger = structlog.get_logger("contentos.readiness")


def check_postgres_and_pgvector(session_factory: SessionFactory) -> tuple[str, str]:
    """Return safe ("ok"/"failed"/"unknown") statuses for connectivity and pgvector.

    Failures are logged with the component name and exception class only; raw
    exception text can carry hosts or credentials and must never propagate.
    """
    postgres_status = "failed"
    pgvector_status = "unknown"
    try:
        with session_scope(session_factory) as session:
            session.execute(text("SELECT 1"))
            postgres_status = "ok"
            installed = session.execute(
                text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
            ).first()
            if installed is None:
                pgvector_status = "failed"
                _logger.warning(
                    "readiness_check_failed",
                    component="pgvector",
                    error_type="extension_missing",
                )
            else:
                pgvector_status = "ok"
    except Exception as exc:
        component = "postgres" if postgres_status != "ok" else "pgvector"
        _logger.warning(
            "readiness_check_failed",
            component=component,
            error_type=type(exc).__name__,
        )
    return postgres_status, pgvector_status
