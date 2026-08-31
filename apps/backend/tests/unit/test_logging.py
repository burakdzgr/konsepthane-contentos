"""Tests for structured logging configuration and redaction."""

import json
from io import StringIO

import structlog

from contentos.core.config import Environment, LogLevel, Settings
from contentos.core.context import reset_request_id, set_request_id
from contentos.core.logging import REDACTED_VALUE, configure_logging, redact_sensitive_fields


def production_settings() -> Settings:
    return Settings(
        environment=Environment.PRODUCTION,
        service_name="ContentOS Logging Test",
        application_version="2.3.4",
        log_level=LogLevel.INFO,
        api_docs_enabled=False,
    )


def test_sensitive_fields_are_redacted_deterministically() -> None:
    secret_value = "must-not-appear"
    fields = {
        "authorization": secret_value,
        "Cookie": secret_value,
        "password_confirmation": secret_value,
        "client_secret": secret_value,
        "refresh-token": secret_value,
        "apiKey": secret_value,
        "access_key_id": secret_value,
        "safe": "visible",
        "nested": {"api_key": secret_value, "label": "kept"},
    }

    first = redact_sensitive_fields(fields)
    second = redact_sensitive_fields(fields)

    assert first == second
    assert first["safe"] == "visible"
    assert first["nested"] == {"api_key": REDACTED_VALUE, "label": "kept"}
    assert secret_value not in repr(first)


def test_json_logging_includes_application_and_request_context_without_secrets() -> None:
    output = StringIO()
    configure_logging(production_settings(), stream=output)
    token = set_request_id("log-request-123")
    secret_value = "highly-sensitive-value"

    try:
        structlog.get_logger("test").info(
            "logging_contract_checked",
            authorization=secret_value,
            safe_field="visible",
        )
    finally:
        reset_request_id(token)

    rendered = output.getvalue()
    event = json.loads(rendered)

    assert secret_value not in rendered
    assert event["authorization"] == REDACTED_VALUE
    assert event["safe_field"] == "visible"
    assert event["event"] == "logging_contract_checked"
    assert event["level"] == "info"
    assert event["service"] == "ContentOS Logging Test"
    assert event["environment"] == "production"
    assert event["application_version"] == "2.3.4"
    assert event["request_id"] == "log-request-123"
    assert "timestamp" in event


def test_reconfiguration_does_not_duplicate_log_lines() -> None:
    output = StringIO()
    settings = production_settings()
    configure_logging(settings, stream=output)
    configure_logging(settings, stream=output)

    structlog.get_logger("test").info("single_event")

    assert len(output.getvalue().splitlines()) == 1
