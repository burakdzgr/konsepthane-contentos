"""Structured logging configuration and safe processors."""

import logging
from collections.abc import Mapping
from typing import TextIO, cast

import structlog
from structlog.typing import EventDict, Processor, WrappedLogger

from contentos.core.config import Environment, Settings
from contentos.core.context import get_request_id

REDACTED_VALUE = "[REDACTED]"

_SENSITIVE_KEY_MARKERS = (
    "authorization",
    "cookie",
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "access_key",
    "accesskey",
)


def _is_sensitive_key(key: str) -> bool:
    normalized_key = key.casefold().replace("-", "_")
    return any(marker in normalized_key for marker in _SENSITIVE_KEY_MARKERS)


def redact_sensitive_fields(values: Mapping[str, object]) -> dict[str, object]:
    """Redact sensitive mapping keys without inspecting arbitrary object internals."""
    redacted: dict[str, object] = {}

    for key, value in values.items():
        if _is_sensitive_key(key):
            redacted[key] = REDACTED_VALUE
        elif isinstance(value, Mapping):
            redacted[key] = redact_sensitive_fields(cast(Mapping[str, object], value))
        else:
            redacted[key] = value

    return redacted


def redact_sensitive_keys(
    _logger: WrappedLogger,
    _method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """Structlog processor that redacts sensitive dictionary fields."""
    return cast(EventDict, redact_sensitive_fields(event_dict))


def add_request_context(
    _logger: WrappedLogger,
    _method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """Attach the active request ID when a request context exists."""
    request_id = get_request_id()
    if request_id is not None:
        event_dict.setdefault("request_id", request_id)
    return event_dict


def _application_context_processor(settings: Settings) -> Processor:
    service = settings.service_name
    environment = settings.environment.value
    application_version = settings.application_version

    def add_application_context(
        _logger: WrappedLogger,
        _method_name: str,
        event_dict: EventDict,
    ) -> EventDict:
        event_dict.setdefault("service", service)
        event_dict.setdefault("environment", environment)
        event_dict.setdefault("application_version", application_version)
        return event_dict

    return add_application_context


def configure_logging(settings: Settings, *, stream: TextIO | None = None) -> None:
    """Configure structlog and the standard library logging pipeline."""
    level = getattr(logging, settings.log_level.value)
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _application_context_processor(settings),
        add_request_context,
        structlog.processors.format_exc_info,
        redact_sensitive_keys,
    ]
    renderer: Processor
    if settings.environment is Environment.LOCAL:
        renderer = structlog.dev.ConsoleRenderer(colors=False)
    else:
        renderer = structlog.processors.JSONRenderer(sort_keys=True)

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )
    handler = logging.StreamHandler(stream)
    handler.setFormatter(formatter)
    handler.setLevel(level)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(level)

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )
