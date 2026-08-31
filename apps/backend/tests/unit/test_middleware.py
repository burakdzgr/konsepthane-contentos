"""Tests for HTTP request context middleware."""

import asyncio
import json
from typing import cast

import httpx
import pytest
from fastapi import FastAPI
from starlette.types import Message, Receive, Scope, Send

from contentos.api.app import create_app
from contentos.api.middleware import RequestContextMiddleware
from contentos.core.config import Environment, LogLevel, Settings
from contentos.core.context import (
    REQUEST_ID_HEADER,
    REQUEST_ID_MAX_LENGTH,
    get_request_id,
    is_valid_request_id,
)


def middleware_test_settings() -> Settings:
    return Settings(
        environment=Environment.TEST,
        service_name="ContentOS Middleware Test",
        application_version="1.0.0-test",
        log_level=LogLevel.INFO,
        api_docs_enabled=False,
    )


def create_test_app() -> FastAPI:
    app = create_app(settings=middleware_test_settings())

    @app.get("/context-probe")
    async def context_probe() -> dict[str, str | None]:
        await asyncio.sleep(0)
        return {"request_id": get_request_id()}

    return app


async def send_test_request(
    app: FastAPI,
    *,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/context-probe", headers=headers)


def test_request_id_is_generated_returned_and_cleared() -> None:
    response = asyncio.run(send_test_request(create_test_app()))

    request_id = response.headers[REQUEST_ID_HEADER]
    assert is_valid_request_id(request_id)
    assert response.json() == {"request_id": request_id}
    assert get_request_id() is None


def test_valid_inbound_request_id_is_preserved() -> None:
    request_id = "caller.request-123:child"

    response = asyncio.run(
        send_test_request(
            create_test_app(),
            headers={REQUEST_ID_HEADER: request_id},
        )
    )

    assert response.headers[REQUEST_ID_HEADER] == request_id
    assert response.json() == {"request_id": request_id}


@pytest.mark.parametrize(
    "invalid_request_id",
    ["contains spaces", "x" * (REQUEST_ID_MAX_LENGTH + 1), "contains/slash"],
)
def test_invalid_inbound_request_id_is_replaced(invalid_request_id: str) -> None:
    response = asyncio.run(
        send_test_request(
            create_test_app(),
            headers={REQUEST_ID_HEADER: invalid_request_id},
        )
    )

    replacement = response.headers[REQUEST_ID_HEADER]
    assert replacement != invalid_request_id
    assert is_valid_request_id(replacement)
    assert response.json() == {"request_id": replacement}


def test_concurrent_requests_keep_isolated_context() -> None:
    app = create_test_app()

    async def run_requests() -> list[httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            first, second = await asyncio.gather(
                client.get("/context-probe", headers={REQUEST_ID_HEADER: "request-one"}),
                client.get("/context-probe", headers={REQUEST_ID_HEADER: "request-two"}),
            )
        return [first, second]

    responses = asyncio.run(run_requests())

    assert responses[0].json() == {"request_id": "request-one"}
    assert responses[1].json() == {"request_id": "request-two"}
    assert get_request_id() is None


def test_request_context_is_cleared_when_application_raises() -> None:
    async def failing_app(_scope: Scope, _receive: Receive, _send: Send) -> None:
        assert get_request_id() == "failing-request"
        raise RuntimeError("expected test failure")

    middleware = RequestContextMiddleware(failing_app)
    scope = cast(
        Scope,
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/failure",
            "raw_path": b"/failure",
            "query_string": b"",
            "root_path": "",
            "headers": [(b"x-request-id", b"failing-request")],
            "client": ("127.0.0.1", 1),
            "server": ("test", 80),
        },
    )

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(_message: Message) -> None:
        return None

    async def invoke() -> None:
        with pytest.raises(RuntimeError, match="expected test failure"):
            await middleware(scope, receive, send)
        assert get_request_id() is None

    asyncio.run(invoke())


def test_factory_installs_safe_access_logging(capsys: pytest.CaptureFixture[str]) -> None:
    response = asyncio.run(
        send_test_request(
            create_test_app(),
            headers={REQUEST_ID_HEADER: "access-log-id"},
        )
    )

    captured_lines = capsys.readouterr().err.splitlines()
    events = [json.loads(line) for line in captured_lines if line.startswith("{")]
    access_event = next(event for event in events if event.get("event") == "http_request_completed")

    assert access_event["method"] == "GET"
    assert access_event["path"] == "/context-probe"
    assert access_event["status_code"] == response.status_code
    assert access_event["request_id"] == "access-log-id"
    assert isinstance(access_event["duration_ms"], float)
