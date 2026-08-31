"""Tests for the liveness and readiness health endpoints."""

import asyncio
import json

import httpx
import pytest
from fastapi import FastAPI

from contentos.api.app import create_app
from contentos.core.config import Environment, LogLevel, Settings
from contentos.core.context import REQUEST_ID_HEADER

DB_URL = "postgresql+psycopg://contentos:health-db-secret@localhost:5432/contentos_health"
REDIS_URL = "redis://:health-redis-secret@localhost:6379/0"


def health_test_settings() -> Settings:
    return Settings(
        environment=Environment.TEST,
        service_name="ContentOS Health Test",
        application_version="3.2.1",
        log_level=LogLevel.INFO,
        api_docs_enabled=False,
        database_url=DB_URL,
        redis_broker_url=REDIS_URL,
    )


class FakeResult:
    def __init__(self, row: tuple[int, ...] | None) -> None:
        self._row = row

    def first(self) -> tuple[int, ...] | None:
        return self._row


class FakeSession:
    def __init__(self, responses: list[object]) -> None:
        self._responses = responses
        self.closed = False

    def execute(self, _statement: object) -> FakeResult:
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        assert isinstance(item, FakeResult)
        return item

    def rollback(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class FakeRedis:
    def __init__(self, error: Exception | None = None) -> None:
        self._error = error
        self.closed = False

    def __enter__(self) -> "FakeRedis":
        return self

    def __exit__(self, *_args: object) -> None:
        self.closed = True

    def ping(self) -> bool:
        if self._error is not None:
            raise self._error
        return True


def healthy_db_responses() -> list[object]:
    return [FakeResult((1,)), FakeResult((1,))]


def app_with(
    db_responses: list[object] | None = None,
    redis: FakeRedis | None = None,
) -> FastAPI:
    app = create_app(settings=health_test_settings())
    responses = db_responses if db_responses is not None else healthy_db_responses()
    fake_redis = redis if redis is not None else FakeRedis()
    app.state.db_session_factory = lambda: FakeSession(responses)
    app.state.redis_client_factory = lambda: fake_redis
    return app


def fetch(app: FastAPI, path: str, headers: dict[str, str] | None = None) -> httpx.Response:
    async def run() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://health") as client:
            return await client.get(path, headers=headers)

    return asyncio.run(run())


def logged_events(captured_err: str) -> list[dict[str, object]]:
    return [json.loads(line) for line in captured_err.splitlines() if line.startswith("{")]


def test_liveness_returns_stable_identity() -> None:
    response = fetch(app_with(), "/health/live")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "ContentOS Health Test",
        "version": "3.2.1",
    }
    assert response.headers[REQUEST_ID_HEADER]


def test_liveness_does_not_depend_on_infrastructure() -> None:
    app = create_app(settings=health_test_settings())

    def broken_factory() -> object:
        raise RuntimeError("infrastructure exploded")

    app.state.db_session_factory = broken_factory
    app.state.redis_client_factory = broken_factory

    response = fetch(app, "/health/live")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_readiness_success_reports_safe_component_states(
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake_redis = FakeRedis()

    response = fetch(app_with(redis=fake_redis), "/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {"postgres": "ok", "pgvector": "ok", "redis": "ok"},
    }
    assert response.headers[REQUEST_ID_HEADER]
    assert fake_redis.closed is True
    events = logged_events(capsys.readouterr().err)
    assert not [event for event in events if event.get("event") == "readiness_check_failed"]


def test_readiness_reports_postgres_failure_without_leaking_details() -> None:
    db_error = RuntimeError(f"connection to server failed for {DB_URL}")

    response = fetch(app_with(db_responses=[db_error]), "/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {"postgres": "failed", "pgvector": "unknown", "redis": "ok"},
    }
    assert "health-db-secret" not in response.text
    assert "connection to server" not in response.text
    assert "localhost" not in response.text


def test_readiness_reports_missing_pgvector_without_sql_details() -> None:
    response = fetch(
        app_with(db_responses=[FakeResult((1,)), FakeResult(None)]),
        "/health/ready",
    )

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {"postgres": "ok", "pgvector": "failed", "redis": "ok"},
    }
    assert "pg_extension" not in response.text
    assert "SELECT" not in response.text


def test_readiness_reports_redis_failure_without_leaking_url() -> None:
    response = fetch(
        app_with(redis=FakeRedis(error=ConnectionError(REDIS_URL))),
        "/health/ready",
    )

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {"postgres": "ok", "pgvector": "ok", "redis": "failed"},
    }
    assert "health-redis-secret" not in response.text
    assert "redis://" not in response.text


def test_readiness_failure_is_logged_once_with_request_id_and_no_secrets(
    capsys: pytest.CaptureFixture[str],
) -> None:
    response = fetch(
        app_with(redis=FakeRedis(error=ConnectionError(REDIS_URL))),
        "/health/ready",
        headers={REQUEST_ID_HEADER: "health-req-1"},
    )

    assert response.headers[REQUEST_ID_HEADER] == "health-req-1"

    captured_err = capsys.readouterr().err
    failures = [
        event
        for event in logged_events(captured_err)
        if event.get("event") == "readiness_check_failed"
    ]

    assert len(failures) == 1
    assert failures[0]["component"] == "redis"
    assert failures[0]["request_id"] == "health-req-1"
    assert failures[0]["error_type"] == "ConnectionError"
    assert "health-redis-secret" not in captured_err
