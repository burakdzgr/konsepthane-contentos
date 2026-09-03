"""Intake-run lifecycle: start, pause, resume, stop — all audited.

The service owns run rows and their append-only events; it never
touches pipeline state itself. The orchestrator (a worker task) is the
only writer of counters and stage timestamps.
"""

import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from contentos.core.config import Settings
from contentos.intake.enums import IntakeEventKind, IntakeRunStatus, IntakeStage
from contentos.intake.errors import (
    IntakeRunConflictError,
    IntakeRunNotFoundError,
    IntakeRunStateError,
    IntakeSourceNotEligibleError,
)
from contentos.intake.models import IntakeRun, IntakeRunEvent
from contentos.sources.enums import DiscoveryStrategy, SourceKind, SourceLifecycleState
from contentos.sources.models import Source

LIVE_STATUSES = (IntakeRunStatus.RUNNING, IntakeRunStatus.PAUSED)

AUTOMATED_PAIRS = frozenset(
    {
        (SourceKind.RSS_FEED, DiscoveryStrategy.FEED),
        (SourceKind.SITEMAP, DiscoveryStrategy.SITEMAP),
    }
)


@dataclass(frozen=True)
class IntakePolicy:
    """The bounded limits one run is started under (immutable snapshot)."""

    prefilter_batch_size: int
    fetch_batch_size: int
    max_fetches_per_run: int
    daily_fetch_budget_per_source: int
    max_promotions_per_run: int
    step_interval_seconds: int

    @classmethod
    def from_settings(cls, settings: Settings) -> "IntakePolicy":
        return cls(
            prefilter_batch_size=settings.intake_prefilter_batch_size,
            fetch_batch_size=settings.intake_fetch_batch_size,
            max_fetches_per_run=settings.intake_max_fetches_per_run,
            daily_fetch_budget_per_source=settings.intake_daily_fetch_budget_per_source,
            max_promotions_per_run=settings.intake_max_promotions_per_run,
            step_interval_seconds=settings.intake_step_interval_seconds,
        )

    @classmethod
    def from_snapshot(cls, snapshot: dict[str, Any]) -> "IntakePolicy":
        return cls(
            prefilter_batch_size=int(snapshot.get("prefilter_batch_size", 1000)),
            fetch_batch_size=int(snapshot.get("fetch_batch_size", 8)),
            max_fetches_per_run=int(snapshot.get("max_fetches_per_run", 40)),
            daily_fetch_budget_per_source=int(snapshot.get("daily_fetch_budget_per_source", 150)),
            max_promotions_per_run=int(snapshot.get("max_promotions_per_run", 20)),
            step_interval_seconds=int(snapshot.get("step_interval_seconds", 15)),
        )


class IntakeRunService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def require_run(self, run_id: uuid.UUID) -> IntakeRun:
        run = self._session.get(IntakeRun, run_id)
        if run is None:
            raise IntakeRunNotFoundError(f"no intake run with id {run_id}")
        return run

    def live_run_for_source(self, source_id: uuid.UUID) -> IntakeRun | None:
        return self._session.scalars(
            select(IntakeRun)
            .where(IntakeRun.source_id == source_id, IntakeRun.status.in_(LIVE_STATUSES))
            .limit(1)
        ).first()

    def start_run(
        self,
        source_id: uuid.UUID,
        *,
        policy: IntakePolicy,
        actor_user_id: uuid.UUID | None,
        request_id: str | None = None,
    ) -> IntakeRun:
        source = self._session.get(Source, source_id)
        if source is None:
            raise IntakeSourceNotEligibleError(f"no source with id {source_id}")
        if source.lifecycle_state is not SourceLifecycleState.ACTIVE:
            raise IntakeSourceNotEligibleError(
                f"source '{source.slug}' is {source.lifecycle_state.value}, not active"
            )
        if (source.kind, source.discovery_strategy) not in AUTOMATED_PAIRS:
            raise IntakeSourceNotEligibleError(
                f"source '{source.slug}' has no automated discovery strategy"
            )
        existing = self.live_run_for_source(source_id)
        if existing is not None:
            raise IntakeRunConflictError(
                f"a live intake run already exists for source '{source.slug}'"
            )
        run = IntakeRun(
            source_id=source_id,
            status=IntakeRunStatus.RUNNING,
            started_by_user_id=actor_user_id,
            request_id=request_id,
            policy=asdict(policy),
        )
        self._session.add(run)
        self._session.flush()
        self.record_event(
            run,
            IntakeStage.RUN,
            IntakeEventKind.RUN_STARTED,
            {"source_slug": source.slug},
            actor_user_id=actor_user_id,
        )
        return run

    def pause_run(
        self, run_id: uuid.UUID, *, reason: str, actor_user_id: uuid.UUID | None
    ) -> IntakeRun:
        run = self.require_run(run_id)
        if run.status is not IntakeRunStatus.RUNNING:
            raise IntakeRunStateError(f"run is {run.status.value}; only a running run pauses")
        run.status = IntakeRunStatus.PAUSED
        self.record_event(
            run,
            IntakeStage.RUN,
            IntakeEventKind.RUN_PAUSED,
            {"reason": reason.strip()[:500]},
            actor_user_id=actor_user_id,
        )
        return run

    def resume_run(
        self, run_id: uuid.UUID, *, reason: str, actor_user_id: uuid.UUID | None
    ) -> IntakeRun:
        run = self.require_run(run_id)
        if run.status is not IntakeRunStatus.PAUSED:
            raise IntakeRunStateError(f"run is {run.status.value}; only a paused run resumes")
        run.status = IntakeRunStatus.RUNNING
        self.record_event(
            run,
            IntakeStage.RUN,
            IntakeEventKind.RUN_RESUMED,
            {"reason": reason.strip()[:500]},
            actor_user_id=actor_user_id,
        )
        return run

    def stop_run(
        self, run_id: uuid.UUID, *, reason: str, actor_user_id: uuid.UUID | None
    ) -> IntakeRun:
        """A safe terminal stop: no new intake work; running pipeline
        tasks (fetch/normalize chains already dispatched) finish."""
        run = self.require_run(run_id)
        if run.status not in LIVE_STATUSES:
            raise IntakeRunStateError(f"run is {run.status.value}; only a live run stops")
        run.status = IntakeRunStatus.STOPPED
        run.finished_at = datetime.now(UTC)
        self.record_event(
            run,
            IntakeStage.RUN,
            IntakeEventKind.RUN_STOPPED,
            {"reason": reason.strip()[:500]},
            actor_user_id=actor_user_id,
        )
        return run

    def record_event(
        self,
        run: IntakeRun,
        stage: IntakeStage,
        kind: IntakeEventKind,
        detail: dict[str, Any] | None = None,
        *,
        actor_user_id: uuid.UUID | None = None,
    ) -> IntakeRunEvent:
        event = IntakeRunEvent(
            run_id=run.id,
            stage=stage,
            kind=kind,
            detail=detail or {},
            actor_user_id=actor_user_id,
        )
        self._session.add(event)
        self._session.flush()
        return event

    def events_for(
        self, run_id: uuid.UUID, *, after_id: int | None = None, limit: int = 100
    ) -> list[IntakeRunEvent]:
        query = select(IntakeRunEvent).where(IntakeRunEvent.run_id == run_id)
        if after_id is not None:
            query = query.where(IntakeRunEvent.id > after_id).order_by(IntakeRunEvent.id.asc())
        else:
            query = query.order_by(IntakeRunEvent.id.desc())
        return list(self._session.scalars(query.limit(limit)).all())

    def has_event(self, run_id: uuid.UUID, kind: IntakeEventKind) -> bool:
        return (
            self._session.scalars(
                select(IntakeRunEvent.id)
                .where(IntakeRunEvent.run_id == run_id, IntakeRunEvent.kind == kind)
                .limit(1)
            ).first()
            is not None
        )
