"""Request-scoped correlation context."""

import re
from contextvars import ContextVar, Token
from typing import TypeGuard
from uuid import uuid4

REQUEST_ID_HEADER = "X-Request-ID"
REQUEST_ID_MAX_LENGTH = 128

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_request_id: ContextVar[str | None] = ContextVar("contentos_request_id", default=None)


def is_valid_request_id(value: str | None) -> TypeGuard[str]:
    """Return whether an inbound request ID is a bounded safe ASCII value."""
    return (
        value is not None
        and 1 <= len(value) <= REQUEST_ID_MAX_LENGTH
        and _REQUEST_ID_PATTERN.fullmatch(value) is not None
    )


def resolve_request_id(value: str | None) -> str:
    """Preserve a valid inbound request ID or create a fresh one."""
    return value if is_valid_request_id(value) else uuid4().hex


def set_request_id(request_id: str) -> Token[str | None]:
    """Bind a request ID to the current execution context."""
    return _request_id.set(request_id)


def get_request_id() -> str | None:
    """Return the request ID bound to the current execution context, if any."""
    return _request_id.get()


def reset_request_id(token: Token[str | None]) -> None:
    """Restore the request context represented by a ContextVar token."""
    _request_id.reset(token)
