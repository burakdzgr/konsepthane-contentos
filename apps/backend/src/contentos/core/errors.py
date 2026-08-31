"""Stable API error envelope contract."""

from collections.abc import Mapping, Sequence
from http import HTTPStatus

from contentos.core.context import get_request_id

INTERNAL_ERROR_CODE = "internal_error"
VALIDATION_ERROR_CODE = "validation_error"
GENERIC_HTTP_ERROR_CODE = "http_error"

INTERNAL_ERROR_MESSAGE = "An internal server error occurred."
VALIDATION_ERROR_MESSAGE = "Request validation failed."
GENERIC_HTTP_ERROR_MESSAGE = "HTTP error."

_STATUS_ERROR_CODES: dict[int, str] = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: VALIDATION_ERROR_CODE,
    429: "rate_limited",
}


def error_code_for_status(status_code: int) -> str:
    """Map an HTTP status code to a stable generic error code."""
    return _STATUS_ERROR_CODES.get(status_code, GENERIC_HTTP_ERROR_CODE)


def safe_http_error_message(status_code: int, detail: object) -> str:
    """Keep a plain-string detail; never expose non-string detail objects."""
    if isinstance(detail, str) and detail:
        return detail
    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return GENERIC_HTTP_ERROR_MESSAGE


def sanitize_validation_errors(
    errors: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Keep only safe location/type/message fields; never echo rejected input."""
    details: list[dict[str, object]] = []
    for error in errors:
        location = error.get("loc", ())
        location_parts: list[object] = (
            [part if isinstance(part, int) else str(part) for part in location]
            if isinstance(location, list | tuple)
            else []
        )
        details.append(
            {
                "location": location_parts,
                "type": str(error.get("type", "unknown")),
                "message": str(error.get("msg", "Invalid value.")),
            }
        )
    return details


def build_error_envelope(
    code: str,
    message: str,
    details: object | None = None,
) -> dict[str, object]:
    """Build the stable error envelope bound to the current request context."""
    error: dict[str, object] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return {"error": error, "request_id": get_request_id()}
