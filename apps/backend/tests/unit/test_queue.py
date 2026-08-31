"""Tests for the Redis + Celery queue and worker foundation."""

from types import SimpleNamespace

import pytest
import structlog
from pydantic import ValidationError

from contentos.core.config import Environment, LogLevel, Settings
from contentos.core.context import get_request_id
from contentos.queue.celery import create_celery_app
from contentos.worker.main import create_worker_app
from contentos.worker.signals import bind_task_context, clear_task_context

BROKER_URL = "redis://:broker-secret-pw@localhost:56399/0"
RESULT_URL = "redis://:result-secret-pw@localhost:56399/1"


def queue_test_settings(
    broker_url: str = BROKER_URL,
    result_url: str = RESULT_URL,
    task_always_eager: bool = True,
) -> Settings:
    return Settings(
        environment=Environment.TEST,
        service_name="ContentOS Queue Test",
        application_version="1.0.0-test",
        log_level=LogLevel.INFO,
        api_docs_enabled=False,
        redis_broker_url=broker_url,
        redis_result_url=result_url,
        celery_default_queue="contentos.test-queue",
        celery_task_always_eager=task_always_eager,
        celery_broker_connection_retry_on_startup=False,
        celery_broker_connection_timeout_seconds=3,
        celery_result_expires_seconds=120,
    )


def fake_task(request_id: str | None) -> SimpleNamespace:
    return SimpleNamespace(request=SimpleNamespace(request_id=request_id, headers=None))


def test_celery_factory_applies_configured_urls_and_queue() -> None:
    app = create_celery_app(queue_test_settings())

    assert app.conf.broker_url == BROKER_URL
    assert app.conf.result_backend == RESULT_URL
    assert app.conf.task_default_queue == "contentos.test-queue"
    assert app.conf.broker_connection_retry_on_startup is False
    assert app.conf.broker_connection_timeout == 3


def test_celery_factory_enforces_json_only_utc_and_result_policy() -> None:
    app = create_celery_app(queue_test_settings())

    assert app.conf.task_serializer == "json"
    assert app.conf.result_serializer == "json"
    assert app.conf.accept_content == ["json"]
    assert app.conf.enable_utc is True
    assert app.conf.timezone == "UTC"
    assert app.conf.task_ignore_result is True
    assert app.conf.result_expires == 120
    assert app.conf.worker_hijack_root_logger is False


@pytest.mark.parametrize("eager", [True, False])
def test_task_always_eager_is_configurable(eager: bool) -> None:
    app = create_celery_app(queue_test_settings(task_always_eager=eager))

    assert app.conf.task_always_eager is eager


@pytest.mark.parametrize(
    "invalid_url",
    ["", "amqp://guest:guest@localhost:5672//", "http://localhost:6379/0", "localhost:6379"],
)
def test_settings_reject_non_redis_queue_urls(invalid_url: str) -> None:
    with pytest.raises(ValidationError):
        queue_test_settings(broker_url=invalid_url)
    with pytest.raises(ValidationError):
        queue_test_settings(result_url=invalid_url)


def test_redis_secret_urls_are_not_exposed_by_settings() -> None:
    settings = queue_test_settings()

    assert "broker-secret-pw" not in repr(settings)
    assert "broker-secret-pw" not in str(settings)
    assert "result-secret-pw" not in repr(settings)
    assert "result-secret-pw" not in str(settings)


def test_no_domain_tasks_are_registered_by_the_foundation() -> None:
    app = create_celery_app(queue_test_settings())

    contentos_tasks = [name for name in app.tasks if not name.startswith("celery.")]
    assert contentos_tasks == []


def test_worker_factory_builds_configured_app() -> None:
    app = create_worker_app(queue_test_settings())

    assert app.conf.task_default_queue == "contentos.test-queue"
    assert app.conf.task_serializer == "json"


def test_task_context_binds_supplied_request_id_and_clears() -> None:
    bind_task_context(sender=fake_task("task-req-1"), task_id="task-abc")

    assert get_request_id() == "task-req-1"
    assert structlog.contextvars.get_contextvars().get("task_id") == "task-abc"

    clear_task_context(sender=fake_task("task-req-1"), task_id="task-abc")

    assert get_request_id() is None
    assert "task_id" not in structlog.contextvars.get_contextvars()


def test_invalid_task_request_id_is_not_bound() -> None:
    bind_task_context(sender=fake_task("bad id with spaces"), task_id="task-invalid")

    assert get_request_id() is None
    assert structlog.contextvars.get_contextvars().get("task_id") == "task-invalid"

    clear_task_context(sender=fake_task("bad id with spaces"), task_id="task-invalid")

    assert "task_id" not in structlog.contextvars.get_contextvars()


def test_context_does_not_leak_between_tasks() -> None:
    bind_task_context(sender=fake_task("task-req-first"), task_id="task-first")
    clear_task_context(sender=fake_task("task-req-first"), task_id="task-first")

    bind_task_context(sender=fake_task(None), task_id="task-second")

    assert get_request_id() is None
    assert structlog.contextvars.get_contextvars().get("task_id") == "task-second"

    clear_task_context(sender=fake_task(None), task_id="task-second")

    assert get_request_id() is None
    assert "task_id" not in structlog.contextvars.get_contextvars()
