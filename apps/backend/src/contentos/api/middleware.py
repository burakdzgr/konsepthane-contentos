"""HTTP middleware for request context and safe access logging."""

from time import perf_counter

import structlog
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from contentos.core.context import (
    REQUEST_ID_HEADER,
    reset_request_id,
    resolve_request_id,
    set_request_id,
)

_access_logger = structlog.get_logger("contentos.access")


class RequestContextMiddleware:
    """Bind, return, and log a safe request ID for each HTTP request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        inbound_request_id = Headers(scope=scope).get(REQUEST_ID_HEADER)
        request_id = resolve_request_id(inbound_request_id)
        context_token = set_request_id(request_id)
        started_at = perf_counter()
        status_code = 500

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                response_headers = MutableHeaders(scope=message)
                response_headers[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            duration_ms = round((perf_counter() - started_at) * 1000, 3)
            try:
                _access_logger.info(
                    "http_request_completed",
                    method=scope["method"],
                    path=scope["path"],
                    status_code=status_code,
                    duration_ms=duration_ms,
                    request_id=request_id,
                )
            finally:
                reset_request_id(context_token)
