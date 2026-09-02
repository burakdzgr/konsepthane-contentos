"""Producer-only dispatch of research pipeline entry-point jobs.

The control API is a task producer, never a worker: it publishes the two
explicit entry-point jobs (`discover_source`, `fetch_discovery_item`) by their
frozen Task 16 names and lets the worker-side chain own everything after
fetch. No WorkerRuntime, no task registration, and no broker connection until
the first explicit publish.
"""

from typing import Any, Protocol

from celery import Celery

from contentos.core.config import Settings
from contentos.queue.celery import create_celery_app
from contentos.worker.editorial_tasks import (
    ANALYZE_SEARCH_INTENT_TASK,
    BUILD_EVIDENCE_PACK_TASK,
    COMPOSE_CONTENT_BRIEF_TASK,
    EVALUATE_OPPORTUNITY_TASK,
    GENERATE_EDITOR_REVIEW_TASK,
    GENERATE_IDEA_CANDIDATES_TASK,
    GENERATE_WRITER_DRAFT_TASK,
    PROMOTE_RESEARCH_TASK,
    RUN_QA_GATES_TASK,
)
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


class EditorialControlDispatcher(Protocol):
    """Seam for explicit operator-triggered editorial job publishing."""

    def enqueue_promote(
        self, normalized_document_id: str, *, request_id: str | None = None
    ) -> None: ...

    def enqueue_evaluate(self, opportunity_id: str, *, request_id: str | None = None) -> None: ...

    def enqueue_generate_ideas(
        self,
        opportunity_id: str,
        *,
        candidate_count: int,
        retry_number: int,
        request_id: str | None = None,
    ) -> None: ...

    def enqueue_build_pack(
        self,
        opportunity_id: str,
        *,
        idea_id: str,
        selections: list[dict[str, Any]],
        contradictions: list[dict[str, Any]] | None,
        request_id: str | None = None,
    ) -> None: ...

    def enqueue_analyze_intent(
        self,
        opportunity_id: str,
        *,
        idea_id: str,
        evidence_pack_id: str,
        signal_ids: list[str],
        retry_number: int,
        request_id: str | None = None,
    ) -> None: ...

    def enqueue_compose_brief(
        self,
        work_item_id: str,
        *,
        idea_id: str,
        evidence_pack_id: str,
        search_intent_analysis_id: str,
        retry_number: int,
        supersede_reason: str | None,
        request_id: str | None = None,
    ) -> None: ...

    def enqueue_generate_writer_draft(
        self,
        content_brief_id: str,
        *,
        retry_number: int,
        supersede_reason: str | None,
        request_id: str | None = None,
    ) -> None: ...

    def enqueue_generate_editor_review(
        self,
        work_item_id: str,
        *,
        retry_number: int,
        supersede_reason: str | None,
        request_id: str | None = None,
    ) -> None: ...

    def enqueue_run_qa(self, work_item_id: str, *, request_id: str | None = None) -> None: ...


class CeleryEditorialControlDispatcher:
    """Producer-only publisher of the six frozen Task 13 editorial jobs.

    Same laziness contract as the research dispatcher: no broker connection
    until the first explicit publish; no WorkerRuntime, task registration,
    or provider construction ever happens in the API process. Every payload
    is exactly the registered task's JSON-safe kwargs — UUID strings plus
    the one accepted bounded evidence-selection command shape.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._app: Celery | None = None

    def _celery(self) -> Celery:
        if self._app is None:
            self._app = create_celery_app(self._settings)
        return self._app

    def _send(self, task_name: str, kwargs: dict[str, Any], request_id: str | None) -> None:
        headers = {"request_id": request_id} if request_id else None
        self._celery().send_task(task_name, kwargs=kwargs, headers=headers)

    def enqueue_promote(
        self, normalized_document_id: str, *, request_id: str | None = None
    ) -> None:
        self._send(
            PROMOTE_RESEARCH_TASK,
            {"normalized_document_id": normalized_document_id},
            request_id,
        )

    def enqueue_evaluate(self, opportunity_id: str, *, request_id: str | None = None) -> None:
        self._send(EVALUATE_OPPORTUNITY_TASK, {"opportunity_id": opportunity_id}, request_id)

    def enqueue_generate_ideas(
        self,
        opportunity_id: str,
        *,
        candidate_count: int,
        retry_number: int,
        request_id: str | None = None,
    ) -> None:
        self._send(
            GENERATE_IDEA_CANDIDATES_TASK,
            {
                "opportunity_id": opportunity_id,
                "candidate_count": candidate_count,
                "retry_number": retry_number,
            },
            request_id,
        )

    def enqueue_build_pack(
        self,
        opportunity_id: str,
        *,
        idea_id: str,
        selections: list[dict[str, Any]],
        contradictions: list[dict[str, Any]] | None,
        request_id: str | None = None,
    ) -> None:
        self._send(
            BUILD_EVIDENCE_PACK_TASK,
            {
                "opportunity_id": opportunity_id,
                "idea_id": idea_id,
                "selections": selections,
                "contradictions": contradictions,
            },
            request_id,
        )

    def enqueue_analyze_intent(
        self,
        opportunity_id: str,
        *,
        idea_id: str,
        evidence_pack_id: str,
        signal_ids: list[str],
        retry_number: int,
        request_id: str | None = None,
    ) -> None:
        self._send(
            ANALYZE_SEARCH_INTENT_TASK,
            {
                "opportunity_id": opportunity_id,
                "idea_id": idea_id,
                "evidence_pack_id": evidence_pack_id,
                "signal_ids": signal_ids,
                "retry_number": retry_number,
            },
            request_id,
        )

    def enqueue_compose_brief(
        self,
        work_item_id: str,
        *,
        idea_id: str,
        evidence_pack_id: str,
        search_intent_analysis_id: str,
        retry_number: int,
        supersede_reason: str | None,
        request_id: str | None = None,
    ) -> None:
        self._send(
            COMPOSE_CONTENT_BRIEF_TASK,
            {
                "work_item_id": work_item_id,
                "idea_id": idea_id,
                "evidence_pack_id": evidence_pack_id,
                "search_intent_analysis_id": search_intent_analysis_id,
                "retry_number": retry_number,
                "supersede_reason": supersede_reason,
            },
            request_id,
        )

    def enqueue_generate_writer_draft(
        self,
        content_brief_id: str,
        *,
        retry_number: int,
        supersede_reason: str | None,
        request_id: str | None = None,
    ) -> None:
        self._send(
            GENERATE_WRITER_DRAFT_TASK,
            {
                "content_brief_id": content_brief_id,
                "retry_number": retry_number,
                "supersede_reason": supersede_reason,
            },
            request_id,
        )

    def enqueue_generate_editor_review(
        self,
        work_item_id: str,
        *,
        retry_number: int,
        supersede_reason: str | None,
        request_id: str | None = None,
    ) -> None:
        self._send(
            GENERATE_EDITOR_REVIEW_TASK,
            {
                "work_item_id": work_item_id,
                "retry_number": retry_number,
                "supersede_reason": supersede_reason,
            },
            request_id,
        )

    def enqueue_run_qa(self, work_item_id: str, *, request_id: str | None = None) -> None:
        self._send(RUN_QA_GATES_TASK, {"work_item_id": work_item_id}, request_id)
