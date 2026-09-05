"""Celery application factory for the ContentOS queue foundation."""

from celery import Celery

from contentos.core.config import Settings


def create_celery_app(settings: Settings) -> Celery:
    """Create a JSON-only, UTC Celery app; never instantiated at import time.

    Redis results are an operational convenience with a short expiry, never
    authoritative workflow state; tasks ignore results unless they opt in.
    """
    app = Celery("contentos")
    app.conf.update(
        broker_url=settings.redis_broker_url.get_secret_value(),
        result_backend=settings.redis_result_url.get_secret_value(),
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        enable_utc=True,
        timezone="UTC",
        task_default_queue=settings.celery_default_queue,
        task_ignore_result=True,
        result_expires=settings.celery_result_expires_seconds,
        task_always_eager=settings.celery_task_always_eager,
        broker_connection_retry_on_startup=settings.celery_broker_connection_retry_on_startup,
        broker_connection_timeout=settings.celery_broker_connection_timeout_seconds,
        # Keep the structured logging foundation authoritative in workers.
        worker_hijack_root_logger=False,
    )
    if getattr(settings, "performance_schedule_enabled", False):
        # The performance loop is the ONLY beat-driven work (agent E); the
        # autopilot keeps its self-re-arming sweep. Lazy import: the worker
        # module must not be pulled in by every producer.
        from contentos.worker.performance_tasks import performance_beat_schedule

        app.conf.beat_schedule = {
            **dict(app.conf.beat_schedule or {}),
            **performance_beat_schedule(settings),
        }
    return app
