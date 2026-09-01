"""Idempotent Celery orchestration of the Phase 2 research pipeline.

PostgreSQL is authoritative; Celery is transport/execution only, and queue
progress never becomes domain state. The Phase 2 delivery contract is:

    at-least-once execution + PostgreSQL idempotency + commit-before-enqueue.

DB commit and broker publish are NOT one atomic transaction (no outbox in
Phase 2). If publishing the next stage fails after a successful commit, the
current task performs a bounded DISPATCH retry; on rerun it detects the
already-durable output and only reschedules the next stage — domain work is
never redone and durable rows are never duplicated.

The discovery admission boundary is preserved: `discover_source` leaves new
candidates in DISCOVERED and never accepts or fetches them. The automatic
chain starts at an ACCEPTED DiscoveryItem:

    ACCEPTED -> fetch -> normalize -> evaluate_duplicate -> extract_evidence
"""

import math
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Protocol

import structlog
from celery import Celery
from sqlalchemy.orm import Session

from contentos.core.context import is_valid_request_id
from contentos.discovery.enums import DiscoveryLifecycleState
from contentos.discovery.feed import FeedDiscoveryStrategy, FeedFetchRetryableError
from contentos.discovery.repository import DiscoveryItemRepository
from contentos.discovery.service import DiscoveryItemNotFoundError, DiscoveryService
from contentos.discovery.sitemap import SitemapDiscoveryStrategy, SitemapFetchRetryableError
from contentos.duplicates.enums import DuplicateDecisionOutcome
from contentos.duplicates.service import DuplicateDecisionService
from contentos.fetching.models import FetchOutcome, RetryClassification
from contentos.fetching.snapshot_repository import FetchSnapshotRepository
from contentos.fetching.snapshot_service import FetchSnapshotService
from contentos.normalization.enums import NormalizationStatus
from contentos.normalization.pipeline import NormalizationPipeline
from contentos.research.extractor import DeterministicEvidenceExtractor
from contentos.sources.enums import DiscoveryStrategy, SourceKind, SourceLifecycleState
from contentos.sources.repository import SourceRepository
from contentos.sources.service import SourceNotFoundError
from contentos.worker.runtime import WorkerRuntime

_logger = structlog.get_logger("contentos.worker.research")

DISCOVER_SOURCE_TASK = "contentos.research.discover_source"
FETCH_DISCOVERY_ITEM_TASK = "contentos.research.fetch_discovery_item"
NORMALIZE_FETCH_TASK = "contentos.research.normalize_fetch"
EVALUATE_DUPLICATE_TASK = "contentos.research.evaluate_duplicate"
EXTRACT_RESEARCH_EVIDENCE_TASK = "contentos.research.extract_research_evidence"

RESEARCH_TASK_NAMES = (
    DISCOVER_SOURCE_TASK,
    FETCH_DISCOVERY_ITEM_TASK,
    NORMALIZE_FETCH_TASK,
    EVALUATE_DUPLICATE_TASK,
    EXTRACT_RESEARCH_EVIDENCE_TASK,
)

# MAX_RETRIES means the initial attempt plus up to MAX_RETRIES retries.
MAX_RETRIES = 3
BASE_RETRY_SECONDS = 30.0
MAX_RETRY_SECONDS = 600.0

EVIDENCE_ELIGIBLE_OUTCOMES = frozenset(
    {
        DuplicateDecisionOutcome.UNIQUE,
        DuplicateDecisionOutcome.RELATED,
        DuplicateDecisionOutcome.UPDATE_EXISTING,
    }
)

_FETCH_RETRY_REASON = "automatic retry of a retryable fetch failure"


class InvalidPipelineInputError(Exception):
    """A task received an identity argument that is not a valid UUID string."""


class PipelineDispatcher(Protocol):
    """Post-commit enqueueing seam for the next pipeline stage."""

    def enqueue(self, task_name: str, entity_id: str, *, request_id: str | None = None) -> None: ...


class CeleryPipelineDispatcher:
    """Enqueue registered pipeline tasks; eager-mode compatible via apply_async."""

    def __init__(self, app: Celery) -> None:
        self._app = app

    def enqueue(self, task_name: str, entity_id: str, *, request_id: str | None = None) -> None:
        headers = {"request_id": request_id} if request_id else None
        self._app.tasks[task_name].apply_async(args=[entity_id], headers=headers)


def _parse_uuid(value: object) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        raise InvalidPipelineInputError("task argument is not a valid UUID") from None


def _retry_countdown(retries: int, retry_after_seconds: float | None = None) -> float:
    """Deterministic bounded exponential backoff; Retry-After clamped, no jitter."""
    countdown = min(BASE_RETRY_SECONDS * (2.0**retries), MAX_RETRY_SECONDS)
    if (
        retry_after_seconds is not None
        and math.isfinite(retry_after_seconds)
        and retry_after_seconds >= 0
    ):
        countdown = min(max(countdown, float(retry_after_seconds)), MAX_RETRY_SECONDS)
    return countdown


def _current_request_id(task: Any) -> str | None:
    candidate = getattr(task.request, "request_id", None)
    if candidate is None:
        headers = getattr(task.request, "headers", None)
        if isinstance(headers, dict):
            candidate = headers.get("request_id")
    return candidate if is_valid_request_id(candidate) else None


def register_research_pipeline_tasks(
    app: Celery,
    runtime: WorkerRuntime,
    *,
    dispatcher: PipelineDispatcher | None = None,
) -> None:
    """Explicitly register the five research pipeline tasks on ``app``.

    Registration only defines tasks: no database, broker, or network activity
    happens here. Tasks use late acknowledgement with worker-loss requeue so
    at-least-once delivery is absorbed by the durable domain constraints.
    """
    pipeline_dispatcher: PipelineDispatcher = dispatcher or CeleryPipelineDispatcher(app)

    @contextmanager
    def task_session() -> Iterator[Session]:
        session = runtime.create_session()
        try:
            yield session
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()

    def dispatch_next(task: Any, task_name: str, entity_id: str) -> str:
        """Enqueue after commit; transport failure triggers a DISPATCH retry."""
        try:
            pipeline_dispatcher.enqueue(task_name, entity_id, request_id=_current_request_id(task))
        except Exception as error:
            _logger.warning(
                "pipeline_dispatch_failed",
                task=str(task.name),
                next_task=task_name,
                entity_id=entity_id,
                error_type=type(error).__name__,
                retries=int(task.request.retries),
            )
            raise task.retry(countdown=_retry_countdown(task.request.retries)) from None
        return task_name

    def discover_source(self: Any, source_id: str) -> dict[str, Any]:
        parsed_id = _parse_uuid(source_id)
        with task_session() as session:
            source = SourceRepository(session).get_by_id(parsed_id)
            if source is None:
                raise SourceNotFoundError(f"no source with id {parsed_id}")
            if source.lifecycle_state is not SourceLifecycleState.ACTIVE:
                return _summary(self, "skipped", source_id=source_id, reason="source_not_active")
            if source.kind is SourceKind.MANUAL or (
                source.discovery_strategy is DiscoveryStrategy.MANUAL
            ):
                return _summary(self, "skipped", source_id=source_id, reason="manual_source")
            if (
                source.kind is SourceKind.RSS_FEED
                and source.discovery_strategy is DiscoveryStrategy.FEED
            ):
                strategy_class: type[FeedDiscoveryStrategy] | type[SitemapDiscoveryStrategy] = (
                    FeedDiscoveryStrategy
                )
            elif (
                source.kind is SourceKind.SITEMAP
                and source.discovery_strategy is DiscoveryStrategy.SITEMAP
            ):
                strategy_class = SitemapDiscoveryStrategy
            else:
                return _summary(self, "skipped", source_id=source_id, reason="unsupported_strategy")

            try:
                with runtime.create_fetch_client() as fetch_client:
                    result = strategy_class(session, fetch_client).execute(parsed_id)
            except (FeedFetchRetryableError, SitemapFetchRetryableError) as error:
                raise self.retry(
                    countdown=_retry_countdown(self.request.retries, error.retry_after_seconds),
                    exc=error,
                ) from None
            session.commit()
            # New candidates deliberately remain DISCOVERED; admission is a
            # durable decision outside this pipeline. No downstream dispatch.
            return _summary(
                self,
                "completed",
                source_id=source_id,
                entries_seen=result.entries_seen,
                admitted_new=result.admitted_new,
                rediscovered_existing=result.rediscovered_existing,
            )

    def fetch_discovery_item(self: Any, discovery_item_id: str) -> dict[str, Any]:
        parsed_id = _parse_uuid(discovery_item_id)
        with task_session() as session:
            item = DiscoveryItemRepository(session).get_by_id(parsed_id)
            if item is None:
                raise DiscoveryItemNotFoundError(f"no discovery item with id {parsed_id}")

            if item.lifecycle_state is DiscoveryLifecycleState.FETCHED:
                snapshot = FetchSnapshotRepository(
                    session
                ).get_latest_successful_for_discovery_item(parsed_id)
                if snapshot is None:
                    return _summary(
                        self,
                        "terminal",
                        discovery_item_id=discovery_item_id,
                        reason="fetched_without_successful_snapshot",
                    )
                next_task = dispatch_next(self, NORMALIZE_FETCH_TASK, str(snapshot.id))
                return _summary(
                    self,
                    "reused",
                    discovery_item_id=discovery_item_id,
                    fetch_snapshot_id=str(snapshot.id),
                    next_task=next_task,
                )
            if item.lifecycle_state is DiscoveryLifecycleState.FETCH_FAILED:
                return _summary(
                    self, "terminal", discovery_item_id=discovery_item_id, reason="fetch_failed"
                )
            if item.lifecycle_state is not DiscoveryLifecycleState.ACCEPTED:
                return _summary(
                    self,
                    "skipped",
                    discovery_item_id=discovery_item_id,
                    reason=f"item_{item.lifecycle_state.value}",
                )

            source = SourceRepository(session).get_by_id(item.source_id)
            if source is None or source.lifecycle_state is not SourceLifecycleState.ACTIVE:
                return _summary(
                    self,
                    "skipped",
                    discovery_item_id=discovery_item_id,
                    reason="source_not_active",
                )

            with runtime.create_fetch_client() as fetch_client:
                result = fetch_client.fetch(item.canonical_url)

            snapshot_service = FetchSnapshotService(session)
            if result.outcome is FetchOutcome.SUCCESS and result.body is not None:
                stored = runtime.create_payload_store(session).put(result.body)
                snapshot = snapshot_service.record_fetch_result(
                    parsed_id, result, raw_payload_ref=stored.ref.value
                )
                session.commit()
                next_task = dispatch_next(self, NORMALIZE_FETCH_TASK, str(snapshot.id))
                return _summary(
                    self,
                    "completed",
                    discovery_item_id=discovery_item_id,
                    fetch_snapshot_id=str(snapshot.id),
                    next_task=next_task,
                )

            snapshot_service.record_fetch_result(parsed_id, result)
            if result.retry is RetryClassification.RETRYABLE and self.request.retries < MAX_RETRIES:
                DiscoveryService(session).requeue_fetch(parsed_id, reason=_FETCH_RETRY_REASON)
                session.commit()
                raise self.retry(
                    countdown=_retry_countdown(self.request.retries, result.retry_after_seconds)
                )
            session.commit()
            return _summary(
                self,
                "terminal",
                discovery_item_id=discovery_item_id,
                outcome=result.outcome.value,
            )

    def normalize_fetch(self: Any, fetch_snapshot_id: str) -> dict[str, Any]:
        parsed_id = _parse_uuid(fetch_snapshot_id)
        with task_session() as session:
            pipeline = NormalizationPipeline(
                session,
                runtime.create_payload_store(session),
                max_payload_bytes=runtime.settings.fetch_max_body_bytes,
            )
            document = pipeline.normalize_snapshot(parsed_id)
            session.commit()
            if document.normalization_status is NormalizationStatus.SUCCEEDED:
                next_task = dispatch_next(self, EVALUATE_DUPLICATE_TASK, str(document.id))
                return _summary(
                    self,
                    "completed",
                    fetch_snapshot_id=fetch_snapshot_id,
                    normalized_document_id=str(document.id),
                    next_task=next_task,
                )
            return _summary(
                self,
                "completed",
                fetch_snapshot_id=fetch_snapshot_id,
                normalized_document_id=str(document.id),
                result="normalization_failed",
            )

    def evaluate_duplicate(self: Any, normalized_document_id: str) -> dict[str, Any]:
        parsed_id = _parse_uuid(normalized_document_id)
        with task_session() as session:
            decision = DuplicateDecisionService(session).evaluate_and_record(parsed_id)
            session.commit()
            if decision.decision in EVIDENCE_ELIGIBLE_OUTCOMES:
                next_task = dispatch_next(
                    self, EXTRACT_RESEARCH_EVIDENCE_TASK, normalized_document_id
                )
                return _summary(
                    self,
                    "completed",
                    normalized_document_id=normalized_document_id,
                    decision=decision.decision.value,
                    next_task=next_task,
                )
            return _summary(
                self,
                "completed",
                normalized_document_id=normalized_document_id,
                decision=decision.decision.value,
            )

    def extract_research_evidence(self: Any, normalized_document_id: str) -> dict[str, Any]:
        parsed_id = _parse_uuid(normalized_document_id)
        with task_session() as session:
            result = DeterministicEvidenceExtractor(session).extract_and_record(parsed_id)
            session.commit()
            return _summary(
                self,
                "completed",
                normalized_document_id=normalized_document_id,
                evidence_created=len(result.created),
                evidence_existing=len(result.existing),
                evidence_skipped=result.skipped_invalid,
            )

    common_options: dict[str, Any] = {
        "bind": True,
        # shared=False keeps each registration owned by exactly this app:
        # Celery's shared-task finalize replay would otherwise rebind task
        # names across apps to stale runtime/dispatcher closures.
        "shared": False,
        "acks_late": True,
        "reject_on_worker_lost": True,
        "max_retries": MAX_RETRIES,
    }
    app.task(name=DISCOVER_SOURCE_TASK, **common_options)(discover_source)
    app.task(name=FETCH_DISCOVERY_ITEM_TASK, **common_options)(fetch_discovery_item)
    app.task(name=NORMALIZE_FETCH_TASK, **common_options)(normalize_fetch)
    app.task(name=EVALUATE_DUPLICATE_TASK, **common_options)(evaluate_duplicate)
    app.task(name=EXTRACT_RESEARCH_EVIDENCE_TASK, **common_options)(extract_research_evidence)


def _summary(task: Any, status: str, **fields: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"status": status, "next_task": None}
    payload.update(fields)
    _logger.info(
        "research_task_completed",
        task=str(task.name),
        retries=int(task.request.retries),
        **payload,
    )
    return payload
