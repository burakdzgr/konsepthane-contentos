"""Tests for the stable API error envelope contract."""

from contentos.core.context import reset_request_id, set_request_id
from contentos.core.errors import (
    GENERIC_HTTP_ERROR_CODE,
    GENERIC_HTTP_ERROR_MESSAGE,
    build_error_envelope,
    error_code_for_status,
    safe_http_error_message,
    sanitize_validation_errors,
)


def test_status_codes_map_to_stable_error_codes() -> None:
    assert error_code_for_status(400) == "bad_request"
    assert error_code_for_status(401) == "unauthorized"
    assert error_code_for_status(403) == "forbidden"
    assert error_code_for_status(404) == "not_found"
    assert error_code_for_status(405) == "method_not_allowed"
    assert error_code_for_status(409) == "conflict"
    assert error_code_for_status(422) == "validation_error"
    assert error_code_for_status(429) == "rate_limited"
    assert error_code_for_status(418) == GENERIC_HTTP_ERROR_CODE


def test_http_error_message_never_exposes_detail_objects() -> None:
    assert safe_http_error_message(404, "Not Found") == "Not Found"
    assert safe_http_error_message(404, {"internal": "state"}) == "Not Found"
    assert safe_http_error_message(404, None) == "Not Found"
    assert safe_http_error_message(404, "") == "Not Found"
    assert safe_http_error_message(999, None) == GENERIC_HTTP_ERROR_MESSAGE


def test_validation_details_exclude_rejected_input() -> None:
    raw_errors: list[dict[str, object]] = [
        {
            "loc": ("query", "count"),
            "type": "int_parsing",
            "msg": "Input should be a valid integer",
            "input": "super-secret-token",
            "ctx": {"error": ValueError("internal parser state")},
        }
    ]

    details = sanitize_validation_errors(raw_errors)

    assert details == [
        {
            "location": ["query", "count"],
            "type": "int_parsing",
            "message": "Input should be a valid integer",
        }
    ]
    assert "super-secret-token" not in repr(details)


def test_envelope_includes_bound_request_id() -> None:
    token = set_request_id("envelope-request-1")
    try:
        envelope = build_error_envelope(code="not_found", message="Not Found")
    finally:
        reset_request_id(token)

    assert envelope == {
        "error": {"code": "not_found", "message": "Not Found"},
        "request_id": "envelope-request-1",
    }


def test_envelope_request_id_is_null_without_context() -> None:
    envelope = build_error_envelope(code="internal_error", message="failed", details=["d"])

    assert envelope["request_id"] is None
    assert envelope["error"] == {
        "code": "internal_error",
        "message": "failed",
        "details": ["d"],
    }
