"""Producer-only dispatch of research pipeline entry-point jobs.

The control API is a task producer, never a worker: it publishes the two
explicit entry-point jobs (`discover_source`, `fetch_discovery_item`) by their
frozen Task 16 names and lets the worker-side chain own everything after
fetch. No WorkerRuntime, no task registration, and no broker connection until
the first explicit publish.
"""

from typing import Protocol

from celery import Celery

from contentos.core.config import Settings
from contentos.queue.celery import create_celery_app
from contentos.worker.research_tasks import (
    DISCOVER_SOURCE_TASK,
    FETCH_DISCOVERY_ITEM_TASK,
)


class ResearchControlDispatcher(Protocol):
    """Seam for explicit operator-triggered entry-point job publishing."""

    def enqueue_discovery(self, source_id: str, *, request_id: str | None = None) -> None: ...

    def enqueue_fetch(self, discovery_item_id: str, *, request_id: str | None = None) -> None: ...


class CeleryResearchControlDispatcher:
    """Publish entry-point jobs via the existing Celery foundation.

    Lazy on purpose: creating the FastAPI app must not touch Redis, so the
    Celery producer app is built on the first explicit publish only. Task
    payloads carry a single entity UUID string; the optional ``request_id``
    header is the only header, so no URL, name, note, or payload data ever
    crosses the broker from the control surface.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._app: Celery | None = None

    def _celery(self) -> Celery:
        if self._app is None:
            self._app = create_celery_app(self._settings)
        return self._app

    def _send(self, task_name: str, entity_id: str, request_id: str | None) -> None:
        headers = {"request_id": request_id} if request_id else None
        self._celery().send_task(task_name, args=[entity_id], headers=headers)

    def enqueue_discovery(self, source_id: str, *, request_id: str | None = None) -> None:
        self._send(DISCOVER_SOURCE_TASK, source_id, request_id)

    def enqueue_fetch(self, discovery_item_id: str, *, request_id: str | None = None) -> None:
        self._send(FETCH_DISCOVERY_ITEM_TASK, discovery_item_id, request_id)
