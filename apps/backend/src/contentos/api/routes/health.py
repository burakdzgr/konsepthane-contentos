"""Operational liveness/readiness endpoints with their own stable contract.

Health responses intentionally bypass the generic API error envelope and never
carry exception text, URLs, hostnames, or credentials.
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from contentos.db.checks import check_postgres_and_pgvector
from contentos.queue.redis import check_redis

router = APIRouter(prefix="/health")


@router.get("/live")
def live(request: Request) -> dict[str, str]:
    """Process liveness only: no database, Redis, or worker dependency.

    The environment NAME is operational metadata (never a secret): the
    admin renders it as the deployment badge."""
    return {
        "status": "ok",
        "service": request.app.title,
        "version": request.app.version,
        "environment": request.app.state.settings.environment.value,
    }


@router.get("/ready")
def ready(request: Request) -> JSONResponse:
    """Readiness of mandatory Phase 1 dependencies: PostgreSQL, pgvector, Redis."""
    postgres_status, pgvector_status = check_postgres_and_pgvector(
        request.app.state.db_session_factory
    )
    redis_status = check_redis(request.app.state.redis_client_factory)

    checks = {
        "postgres": postgres_status,
        "pgvector": pgvector_status,
        "redis": redis_status,
    }
    is_ready = all(status == "ok" for status in checks.values())
    return JSONResponse(
        status_code=200 if is_ready else 503,
        content={"status": "ready" if is_ready else "not_ready", "checks": checks},
    )
