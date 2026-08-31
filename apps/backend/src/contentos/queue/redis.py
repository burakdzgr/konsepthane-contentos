"""Redis client factory and bounded readiness check."""

from collections.abc import Callable

import structlog
from redis import Redis

from contentos.core.config import Settings

RedisClientFactory = Callable[[], Redis]

_logger = structlog.get_logger("contentos.readiness")


def create_redis_client(settings: Settings) -> Redis:
    """Create a short-lived Redis client with bounded timeouts; caller closes it."""
    timeout = float(settings.celery_broker_connection_timeout_seconds)
    return Redis.from_url(
        settings.redis_broker_url.get_secret_value(),
        socket_connect_timeout=timeout,
        socket_timeout=timeout,
    )


def check_redis(client_factory: RedisClientFactory) -> str:
    """PING Redis through a client that is always closed; never leak the URL."""
    try:
        with client_factory() as client:
            client.ping()
    except Exception as exc:
        _logger.warning(
            "readiness_check_failed",
            component="redis",
            error_type=type(exc).__name__,
        )
        return "failed"
    return "ok"
