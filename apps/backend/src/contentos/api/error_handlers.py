"""API exception handling that renders the stable error envelope."""

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from contentos.core.context import get_request_id
from contentos.core.errors import (
    INTERNAL_ERROR_CODE,
    INTERNAL_ERROR_MESSAGE,
    VALIDATION_ERROR_CODE,
    VALIDATION_ERROR_MESSAGE,
    build_error_envelope,
    error_code_for_status,
    safe_http_error_message,
    sanitize_validation_errors,
)

_error_logger = structlog.get_logger("contentos.errors")


async def handle_validation_error(_request: Request, exc: Exception) -> JSONResponse:
    """Return the stable 422 envelope for request validation failures."""
    if not isinstance(exc, RequestValidationError):  # pragma: no cover
        raise exc
    return JSONResponse(
        status_code=422,
        content=build_error_envelope(
            code=VALIDATION_ERROR_CODE,
            message=VALIDATION_ERROR_MESSAGE,
            details=sanitize_validation_errors(exc.errors()),
        ),
    )


async def handle_http_exception(_request: Request, exc: Exception) -> JSONResponse:
    """Return the stable envelope for HTTPException with its status preserved."""
    if not isinstance(exc, StarletteHTTPException):  # pragma: no cover
        raise exc
    return JSONResponse(
        status_code=exc.status_code,
        content=build_error_envelope(
            code=error_code_for_status(exc.status_code),
            message=safe_http_error_message(exc.status_code, exc.detail),
        ),
        headers=exc.headers,
    )


class UnhandledExceptionMiddleware:
    """Convert unhandled exceptions into the opaque 500 envelope."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def send_tracking_start(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, send_tracking_start)
        except Exception as exc:
            _error_logger.error(
                "unhandled_exception",
                method=scope["method"],
                path=scope["path"],
                request_id=get_request_id(),
                exc_info=exc,
            )
            if response_started:
                raise
            response = JSONResponse(
                status_code=500,
                content=build_error_envelope(
                    code=INTERNAL_ERROR_CODE,
                    message=INTERNAL_ERROR_MESSAGE,
                ),
            )
            await response(scope, receive, send)


def install_error_handling(app: FastAPI) -> None:
    """Attach envelope exception handlers and the last-resort middleware."""
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, handle_http_exception)
    app.add_middleware(UnhandledExceptionMiddleware)
