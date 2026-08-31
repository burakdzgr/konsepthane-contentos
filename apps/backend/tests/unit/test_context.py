"""Tests for request-scoped correlation context."""

from contentos.core.context import (
    REQUEST_ID_MAX_LENGTH,
    get_request_id,
    is_valid_request_id,
    reset_request_id,
    resolve_request_id,
    set_request_id,
)


def test_request_id_validation_is_conservative() -> None:
    assert is_valid_request_id("request-123.example:child")
    assert not is_valid_request_id(None)
    assert not is_valid_request_id("")
    assert not is_valid_request_id("contains spaces")
    assert not is_valid_request_id("contains\ncontrol")
    assert not is_valid_request_id("x" * (REQUEST_ID_MAX_LENGTH + 1))


def test_invalid_request_id_is_replaced() -> None:
    generated = resolve_request_id("unsafe request id")

    assert generated != "unsafe request id"
    assert is_valid_request_id(generated)


def test_request_context_can_be_bound_and_reset() -> None:
    token = set_request_id("request-123")

    assert get_request_id() == "request-123"

    reset_request_id(token)
    assert get_request_id() is None
