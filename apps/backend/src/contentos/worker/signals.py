"""Celery signal hooks binding task and correlation context to worker logs."""

from collections.abc import Mapping
from contextvars import Token
from typing import Any

import structlog
from celery import signals

from contentos.core.context import is_valid_request_id, reset_request_id, set_request_id

REQUEST_ID_TASK_HEADER = "request_id"

_request_id_tokens: dict[str, Token[str | None]] = {}
_structlog_tokens: dict[str, Mapping[str, Token[Any]]] = {}


def _request_id_from(sender: object) -> str | None:
    request = getattr(sender, "request", None)
    candidate = getattr(request, REQUEST_ID_TASK_HEADER, None)
    if candidate is None:
        headers = getattr(request, "headers", None)
        if isinstance(headers, dict):
            candidate = headers.get(REQUEST_ID_TASK_HEADER)
    return candidate if is_valid_request_id(candidate) else None


def bind_task_context(sender: object = None, task_id: str | None = None, **_: object) -> None:
    """Bind the task ID, and a supplied valid correlation ID, to log context."""
    if task_id is None:
        return
    request_id = _request_id_from(sender)
    if request_id is not None:
        _request_id_tokens[task_id] = set_request_id(request_id)
    _structlog_tokens[task_id] = structlog.contextvars.bind_contextvars(task_id=task_id)


def clear_task_context(sender: object = None, task_id: str | None = None, **_: object) -> None:
    """Restore the context bound for this task so nothing leaks to the next one."""
    if task_id is None:
        return
    request_id_token = _request_id_tokens.pop(task_id, None)
    if request_id_token is not None:
        reset_request_id(request_id_token)
    structlog_tokens = _structlog_tokens.pop(task_id, None)
    if structlog_tokens is not None:
        structlog.contextvars.reset_contextvars(**structlog_tokens)


def install_worker_signal_handlers() -> None:
    """Connect task context binding to Celery task signals; safe to call twice."""
    signals.task_prerun.connect(bind_task_context, dispatch_uid="contentos-bind-task-context")
    signals.task_postrun.connect(clear_task_context, dispatch_uid="contentos-clear-task-context")
