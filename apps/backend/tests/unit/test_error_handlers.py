"""Tests for API exception handlers rendering the stable error envelope."""

import asyncio
import json

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from contentos.api.app import create_app
from contentos.core.config import Environment, LogLevel, Settings
from contentos.core.context import REQUEST_ID_HEADER


def error_test_settings() -> Settings:
    return Settings(
        environment=Environment.TEST,
        service_name="ContentOS Error Test",
        application_version="1.0.0-test",
        log_level=LogLevel.INFO,
        api_docs_enabled=False,
    )


def create_test_app() -> FastAPI:
    app = create_app(settings=error_test_settings())

    @app.get("/validated")
    async def validated(count: int) -> dict[str, int]:
        return {"count": count}

    @app.get("/explicit-conflict")
    async def explicit_conflict() -> dict[str, str]:
        raise HTTPException(status_code=409, detail="Resource version conflict.")

    @app.get("/unexpected-failure")
    async def unexpected_failure() -> dict[str, str]:
        raise RuntimeError("internal kaboom at C:\\contentos\\private\\module.py")

    return app


async def send_get(
    app: FastAPI,
    path: str,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path, headers=headers)


def test_validation_error_returns_stable_envelope() -> None:
    secret_value = "super-secret-credential"

    response = asyncio.run(send_get(create_test_app(), f"/validated?count={secret_value}"))

    body = response.json()
    assert response.status_code == 422
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["message"] == "Request validation failed."
    assert body["request_id"] == response.headers[REQUEST_ID_HEADER]

    details = body["error"]["details"]
    assert len(details) == 1
    assert details[0]["location"] == ["query", "count"]
    assert details[0]["type"] == "int_parsing"
    assert set(details[0]) == {"location", "type", "message"}
    assert secret_value not in response.text


def test_missing_route_returns_not_found_envelope() -> None:
    response = asyncio.run(send_get(create_test_app(), "/does-not-exist"))

    body = response.json()
    assert response.status_code == 404
    assert body["error"] == {"code": "not_found", "message": "Not Found"}
    assert body["request_id"] == response.headers[REQUEST_ID_HEADER]


def test_explicit_http_exception_is_preserved_safely() -> None:
    response = asyncio.run(send_get(create_test_app(), "/explicit-conflict"))

    body = response.json()
    assert response.status_code == 409
    assert body["error"] == {"code": "conflict", "message": "Resource version conflict."}
    assert body["request_id"] == response.headers[REQUEST_ID_HEADER]


def test_unexpected_exception_returns_opaque_internal_error() -> None:
    response = asyncio.run(
        send_get(
            create_test_app(),
            "/unexpected-failure",
            headers={REQUEST_ID_HEADER: "error-request-1"},
        )
    )

    body = response.json()
    assert response.status_code == 500
    assert body["error"] == {
        "code": "internal_error",
        "message": "An internal server error occurred.",
    }
    assert body["request_id"] == "error-request-1"
    assert response.headers[REQUEST_ID_HEADER] == "error-request-1"
    assert "internal kaboom" not in response.text
    assert "RuntimeError" not in response.text
    assert "Traceback" not in response.text
    assert "contentos\\private" not in response.text
    assert "module.py" not in response.text


def test_unexpected_exception_is_logged_once_with_request_id(
    capsys: pytest.CaptureFixture[str],
) -> None:
    asyncio.run(
        send_get(
            create_test_app(),
            "/unexpected-failure",
            headers={REQUEST_ID_HEADER: "error-log-1"},
        )
    )

    lines = capsys.readouterr().err.splitlines()
    events = [json.loads(line) for line in lines if line.startswith("{")]
    error_events = [event for event in events if event.get("event") == "unhandled_exception"]

    assert len(error_events) == 1
    event = error_events[0]
    assert event["request_id"] == "error-log-1"
    assert event["method"] == "GET"
    assert event["path"] == "/unexpected-failure"
    assert "RuntimeError" in event["exception"]
