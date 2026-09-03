"""The bounded autonomous intake step.

`advance_run` performs ONE bounded slice of work for a run and says
when to look again. Every decision re-derives from durable pipeline
rows (never memory), so the step is idempotent, restart-safe, and
resumable. It drives ONLY transitions the domain model already
permits, through the existing domain services and frozen queue tasks:

  discovery      -> DiscoveryService admissions via the existing strategies
  prefilter      -> DiscoveryService.accept_item / reject_item (coded reasons)
  bounded fetch  -> the frozen fetch task (fetch -> normalize -> duplicate
                    chain stays worker-owned and unchanged)
  promotion      -> the frozen promote task (which itself chains scoring)

It never commissions, rejects an opportunity, selects an idea, drafts,
approves, or publishes — those remain governed human decisions.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

import structlog
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from contentos.discovery.enums import DiscoveryLifecycleState
from contentos.discovery.models import DiscoveryItem
from contentos.discovery.service import DiscoveryService
from contentos.duplicates.models import DuplicateDecision
from contentos.fetching.models import FetchOutcome
from contentos.fetching.snapshots import FetchSnapshot
from contentos.intake.enums import IntakeEventKind, IntakeRunStatus, IntakeStage
from contentos.intake.models import IntakeRun, IntakeRunEvent
from contentos.intake.prefilter import classify_url
from contentos.intake.service import IntakePolicy, IntakeRunService
from contentos.normalization.models import NormalizedDocument
from contentos.operations.enums import PauseScope
from contentos.operations.errors import IntakePausedError
from contentos.operations.service import OperationsService
from contentos.opportunities.models import EditorialOpportunity
from contentos.opportunities.service import ELIGIBLE_OUTCOMES
from contentos.sources.models import Source

_logger = structlog.get_logger("contentos.intake.orchestrator")

# In-flight fetches older than this are re-dispatched (idempotent, the
# fetch task is state-guarded), so a lost queue message cannot stall a
# run forever.
STALLED_FETCH_REDISPATCH_SECONDS = 600

Dispatch = Callable[[str], None]


@dataclass(frozen=True)
class StepOutcome:
    action: Literal["reschedule", "waiting", "done", "halted"]
    countdown_seconds: int
    # Dispatches the caller must publish AFTER committing the session.
    fetch_dispatches: tuple[str, ...] = ()
    promote_dispatches: tuple[str, ...] = ()


def _now() -> datetime:
    return datetime.now(UTC)


def _day_start_for(session: Session) -> datetime:
    day_start = _now().replace(hour=0, minute=0, second=0, microsecond=0)
    bind = session.get_bind()
    if bind is not None and bind.dialect.name == "sqlite":
        return day_start.replace(tzinfo=None)
    return day_start


class IntakeOrchestrator:
    def __init__(self, session: Session, *, fetch_client_factory: Callable[[], Any]) -> None:
        self._session = session
        self._service = IntakeRunService(session)
        self._fetch_client_factory = fetch_client_factory

    # -- public entry ---------------------------------------------------------

    def advance(self, run_id: uuid.UUID, policy: IntakePolicy | None = None) -> StepOutcome:
        run = self._service.require_run(run_id)
        if run.status is not IntakeRunStatus.RUNNING:
            return StepOutcome("halted", 0)
        effective = policy or IntakePolicy.from_snapshot(run.policy)

        try:
            OperationsService(self._session).ensure_dispatch_allowed(PauseScope.RESEARCH)
        except IntakePausedError as error:
            self._service.record_event(
                run,
                IntakeStage.RUN,
                IntakeEventKind.OPERATIONAL_PAUSE,
                {"scope": error.scope.value},
            )
            run.status = IntakeRunStatus.PAUSED
            return StepOutcome("halted", 0)

        if run.discovery_completed_at is None:
            return self._discovery_step(run)
        if run.prefilter_completed_at is None:
            return self._prefilter_step(run, effective)
        return self._fetch_and_promote_step(run, effective)

    # -- discovery ------------------------------------------------------------

    def _discovery_step(self, run: IntakeRun) -> StepOutcome:
        from contentos.discovery.feed import FeedDiscoveryStrategy
        from contentos.discovery.sitemap import SitemapDiscoveryStrategy
        from contentos.sources.enums import DiscoveryStrategy as Strategy

        source = self._session.get(Source, run.source_id)
        assert source is not None  # FK-guaranteed
        self._service.record_event(
            run, IntakeStage.DISCOVERY, IntakeEventKind.DISCOVERY_STARTED, {"slug": source.slug}
        )
        strategy_class = (
            FeedDiscoveryStrategy
            if source.discovery_strategy is Strategy.FEED
            else SitemapDiscoveryStrategy
        )
        with self._fetch_client_factory() as fetch_client:
            result = strategy_class(self._session, fetch_client).execute(source.id)
        run.discovered_new = result.admitted_new
        run.rediscovered = result.rediscovered_existing
        run.discovery_completed_at = _now()
        self._service.record_event(
            run,
            IntakeStage.DISCOVERY,
            IntakeEventKind.DISCOVERY_COMPLETED,
            {
                "entries_seen": result.entries_seen,
                "admitted_new": result.admitted_new,
                "rediscovered": result.rediscovered_existing,
                "warnings": list(result.parse_warnings)[:10],
            },
        )
        return StepOutcome("reschedule", 0)

    # -- prefilter ------------------------------------------------------------

    def _prefilter_step(self, run: IntakeRun, policy: IntakePolicy) -> StepOutcome:
        items = list(
            self._session.scalars(
                select(DiscoveryItem)
                .where(
                    DiscoveryItem.source_id == run.source_id,
                    DiscoveryItem.lifecycle_state == DiscoveryLifecycleState.DISCOVERED,
                )
                .order_by(DiscoveryItem.discovered_at.desc())
                .limit(policy.prefilter_batch_size)
            ).all()
        )
        service = DiscoveryService(self._session)
        accepted = 0
        rejected = 0
        for item in items:
            decision = classify_url(item.canonical_url)
            if decision is None:
                service.accept_item(item.id)
                accepted += 1
            else:
                service.reject_item(
                    item.id,
                    decision.reason,
                    note=f"intake prefilter: {decision.rule}",
                )
                rejected += 1
        run.prefilter_accepted += accepted
        run.prefilter_rejected += rejected
        if items:
            self._service.record_event(
                run,
                IntakeStage.PREFILTER,
                IntakeEventKind.PREFILTER_PROGRESS,
                {
                    "batch_accepted": accepted,
                    "batch_rejected": rejected,
                    "total_accepted": run.prefilter_accepted,
                    "total_rejected": run.prefilter_rejected,
                },
            )
        if len(items) < policy.prefilter_batch_size:
            run.prefilter_completed_at = _now()
            self._service.record_event(
                run,
                IntakeStage.PREFILTER,
                IntakeEventKind.PREFILTER_COMPLETED,
                {
                    "total_accepted": run.prefilter_accepted,
                    "total_rejected": run.prefilter_rejected,
                },
            )
        return StepOutcome("reschedule", 0)

    # -- fetch + promote ------------------------------------------------------

    def _dispatched_fetch_events(self, run: IntakeRun) -> list[IntakeRunEvent]:
        return list(
            self._session.scalars(
                select(IntakeRunEvent).where(
                    IntakeRunEvent.run_id == run.id,
                    IntakeRunEvent.kind == IntakeEventKind.FETCH_ITEM_DISPATCHED,
                )
            ).all()
        )

    def _dispatched_today_for_source(self, source_id: uuid.UUID) -> int:
        since = _day_start_for(self._session)
        return int(
            self._session.scalar(
                select(func.count())
                .select_from(IntakeRunEvent)
                .join(IntakeRun, IntakeRun.id == IntakeRunEvent.run_id)
                .where(
                    IntakeRun.source_id == source_id,
                    IntakeRunEvent.kind == IntakeEventKind.FETCH_ITEM_DISPATCHED,
                    IntakeRunEvent.occurred_at >= since,
                )
            )
            or 0
        )

    def _fetch_and_promote_step(self, run: IntakeRun, policy: IntakePolicy) -> StepOutcome:
        dispatch_events = self._dispatched_fetch_events(run)
        dispatched_ids: set[uuid.UUID] = set()
        first_dispatch_at: dict[uuid.UUID, datetime] = {}
        for event in dispatch_events:
            raw = event.detail.get("discovery_item_id")
            try:
                item_id = uuid.UUID(str(raw))
            except (ValueError, TypeError):
                continue
            dispatched_ids.add(item_id)
            if item_id not in first_dispatch_at:
                first_dispatch_at[item_id] = event.occurred_at

        fetched = 0
        failed = 0
        in_flight: list[DiscoveryItem] = []
        if dispatched_ids:
            rows = self._session.scalars(
                select(DiscoveryItem).where(DiscoveryItem.id.in_(dispatched_ids))
            ).all()
            for item in rows:
                if item.lifecycle_state is DiscoveryLifecycleState.FETCHED:
                    fetched += 1
                elif item.lifecycle_state is DiscoveryLifecycleState.FETCH_FAILED:
                    failed += 1
                elif item.lifecycle_state is DiscoveryLifecycleState.ACCEPTED:
                    in_flight.append(item)
        if fetched != run.fetched or failed != run.fetch_failed:
            run.fetched = fetched
            run.fetch_failed = failed
            self._service.record_event(
                run,
                IntakeStage.FETCH,
                IntakeEventKind.FETCH_PROGRESS,
                {
                    "fetched": fetched,
                    "fetch_failed": failed,
                    "in_flight": len(in_flight),
                    "dispatched": run.fetch_dispatched,
                },
            )

        if in_flight:
            redispatches: list[str] = []
            now = _now()
            for item in in_flight:
                started = first_dispatch_at.get(item.id)
                if started is None:
                    continue
                aware = started if started.tzinfo is not None else started.replace(tzinfo=UTC)
                if (now - aware).total_seconds() >= STALLED_FETCH_REDISPATCH_SECONDS:
                    self._service.record_event(
                        run,
                        IntakeStage.FETCH,
                        IntakeEventKind.FETCH_ITEM_DISPATCHED,
                        {"discovery_item_id": str(item.id), "redispatch": True},
                    )
                    redispatches.append(str(item.id))
            return StepOutcome(
                "waiting",
                policy.step_interval_seconds,
                fetch_dispatches=tuple(redispatches),
            )

        fetch_done = False
        if run.fetch_dispatched >= policy.max_fetches_per_run:
            if not self._service.has_event(run.id, IntakeEventKind.FETCH_CAP_REACHED):
                self._service.record_event(
                    run,
                    IntakeStage.FETCH,
                    IntakeEventKind.FETCH_CAP_REACHED,
                    {"cap": policy.max_fetches_per_run},
                )
            fetch_done = True
        else:
            remaining_daily = (
                policy.daily_fetch_budget_per_source
                - self._dispatched_today_for_source(run.source_id)
            )
            if remaining_daily <= 0:
                if not self._service.has_event(run.id, IntakeEventKind.FETCH_BUDGET_EXHAUSTED):
                    self._service.record_event(
                        run,
                        IntakeStage.FETCH,
                        IntakeEventKind.FETCH_BUDGET_EXHAUSTED,
                        {"daily_budget": policy.daily_fetch_budget_per_source},
                    )
                fetch_done = True
            else:
                batch_size = min(
                    policy.fetch_batch_size,
                    policy.max_fetches_per_run - run.fetch_dispatched,
                    remaining_daily,
                )
                query = (
                    select(DiscoveryItem)
                    .where(
                        DiscoveryItem.source_id == run.source_id,
                        DiscoveryItem.lifecycle_state == DiscoveryLifecycleState.ACCEPTED,
                    )
                    .order_by(DiscoveryItem.discovered_at.desc())
                    .limit(batch_size + len(dispatched_ids))
                )
                candidates = [
                    item
                    for item in self._session.scalars(query).all()
                    if item.id not in dispatched_ids
                ][:batch_size]
                if candidates:
                    for item in candidates:
                        self._service.record_event(
                            run,
                            IntakeStage.FETCH,
                            IntakeEventKind.FETCH_ITEM_DISPATCHED,
                            {"discovery_item_id": str(item.id)},
                        )
                    run.fetch_dispatched += len(candidates)
                    self._service.record_event(
                        run,
                        IntakeStage.FETCH,
                        IntakeEventKind.FETCH_BATCH_DISPATCHED,
                        {
                            "count": len(candidates),
                            "dispatched_total": run.fetch_dispatched,
                        },
                    )
                    return StepOutcome(
                        "waiting",
                        policy.step_interval_seconds,
                        fetch_dispatches=tuple(str(item.id) for item in candidates),
                    )
                if not self._service.has_event(run.id, IntakeEventKind.FETCH_COMPLETED):
                    self._service.record_event(
                        run,
                        IntakeStage.FETCH,
                        IntakeEventKind.FETCH_COMPLETED,
                        {"fetched": run.fetched, "fetch_failed": run.fetch_failed},
                    )
                fetch_done = True

        return self._promote_step(run, policy, fetch_done=fetch_done)

    # -- promote --------------------------------------------------------------

    def _promoted_document_ids(self, run: IntakeRun) -> set[uuid.UUID]:
        ids: set[uuid.UUID] = set()
        for event in self._session.scalars(
            select(IntakeRunEvent).where(
                IntakeRunEvent.run_id == run.id,
                IntakeRunEvent.kind == IntakeEventKind.PROMOTION_DISPATCHED,
            )
        ).all():
            raw = event.detail.get("normalized_document_id")
            try:
                ids.add(uuid.UUID(str(raw)))
            except (ValueError, TypeError):
                continue
        return ids

    def _promotable_documents(
        self, run: IntakeRun, *, exclude: set[uuid.UUID], limit: int
    ) -> list[uuid.UUID]:
        """Fetched item -> successful snapshot -> normalized doc whose
        LATEST duplicate decision is promotion-eligible and that has no
        opportunity yet. "Latest" uses the research read model's exact
        ordering (evaluated_at, created_at, id descending) via a window
        function — decision ids are UUIDs, so max(id) would be wrong on
        every backend and invalid SQL on PostgreSQL."""
        ranked = (
            select(
                DuplicateDecision.normalized_document_id.label("document_id"),
                DuplicateDecision.decision.label("decision"),
                func.row_number()
                .over(
                    partition_by=DuplicateDecision.normalized_document_id,
                    order_by=(
                        DuplicateDecision.evaluated_at.desc(),
                        DuplicateDecision.created_at.desc(),
                        DuplicateDecision.id.desc(),
                    ),
                )
                .label("rn"),
            )
        ).subquery()
        eligible_documents = select(ranked.c.document_id).where(
            ranked.c.rn == 1,
            ranked.c.decision.in_(tuple(ELIGIBLE_OUTCOMES)),
        )
        query = (
            select(NormalizedDocument.id)
            .join(FetchSnapshot, FetchSnapshot.id == NormalizedDocument.fetch_snapshot_id)
            .join(DiscoveryItem, DiscoveryItem.id == FetchSnapshot.discovery_item_id)
            .outerjoin(
                EditorialOpportunity,
                EditorialOpportunity.promotion_root_document_id == NormalizedDocument.id,
            )
            .where(
                DiscoveryItem.source_id == run.source_id,
                FetchSnapshot.fetch_outcome == FetchOutcome.SUCCESS,
                NormalizedDocument.id.in_(eligible_documents),
                EditorialOpportunity.id.is_(None),
            )
            .order_by(NormalizedDocument.id)
            .limit(limit + len(exclude))
        )
        results = [doc_id for doc_id in self._session.scalars(query).all() if doc_id not in exclude]
        return results[:limit]

    def _promote_step(
        self, run: IntakeRun, policy: IntakePolicy, *, fetch_done: bool
    ) -> StepOutcome:
        promoted = self._promoted_document_ids(run)
        if promoted:
            created = int(
                self._session.scalar(
                    select(func.count())
                    .select_from(EditorialOpportunity)
                    .where(EditorialOpportunity.promotion_root_document_id.in_(promoted))
                )
                or 0
            )
            run.opportunities_created = created

        remaining_cap = policy.max_promotions_per_run - run.promotions_dispatched
        if remaining_cap <= 0:
            if not self._service.has_event(run.id, IntakeEventKind.PROMOTION_CAP_REACHED):
                self._service.record_event(
                    run,
                    IntakeStage.PROMOTE,
                    IntakeEventKind.PROMOTION_CAP_REACHED,
                    {"cap": policy.max_promotions_per_run},
                )
        else:
            candidates = self._promotable_documents(run, exclude=promoted, limit=remaining_cap)
            if candidates:
                for doc_id in candidates:
                    self._service.record_event(
                        run,
                        IntakeStage.PROMOTE,
                        IntakeEventKind.PROMOTION_DISPATCHED,
                        {"normalized_document_id": str(doc_id)},
                    )
                run.promotions_dispatched += len(candidates)
                return StepOutcome(
                    "waiting",
                    policy.step_interval_seconds,
                    promote_dispatches=tuple(str(doc_id) for doc_id in candidates),
                )

        if not fetch_done:
            return StepOutcome("waiting", policy.step_interval_seconds)

        # Fetch settled and nothing left to promote-dispatch: wait for the
        # already-dispatched promotions to materialize, then complete.
        if run.promotions_dispatched > 0 and run.opportunities_created < run.promotions_dispatched:
            pending = run.promotions_dispatched - run.opportunities_created
            promote_wait = self._session.scalars(
                select(IntakeRunEvent)
                .where(
                    IntakeRunEvent.run_id == run.id,
                    IntakeRunEvent.kind == IntakeEventKind.PROMOTION_DISPATCHED,
                )
                .order_by(IntakeRunEvent.id.desc())
                .limit(1)
            ).first()
            if promote_wait is not None:
                occurred = promote_wait.occurred_at
                aware = occurred if occurred.tzinfo is not None else occurred.replace(tzinfo=UTC)
                if (_now() - aware).total_seconds() < STALLED_FETCH_REDISPATCH_SECONDS:
                    return StepOutcome("waiting", policy.step_interval_seconds)
            _logger.warning(
                "intake_promotions_unresolved",
                run_id=str(run.id),
                pending=pending,
            )

        run.status = IntakeRunStatus.COMPLETED
        run.finished_at = _now()
        remaining_accepted = int(
            self._session.scalar(
                select(func.count())
                .select_from(DiscoveryItem)
                .where(
                    DiscoveryItem.source_id == run.source_id,
                    DiscoveryItem.lifecycle_state == DiscoveryLifecycleState.ACCEPTED,
                )
            )
            or 0
        )
        self._service.record_event(
            run,
            IntakeStage.RUN,
            IntakeEventKind.RUN_COMPLETED,
            {
                "discovered_new": run.discovered_new,
                "prefilter_accepted": run.prefilter_accepted,
                "prefilter_rejected": run.prefilter_rejected,
                "fetched": run.fetched,
                "fetch_failed": run.fetch_failed,
                "promotions_dispatched": run.promotions_dispatched,
                "opportunities_created": run.opportunities_created,
                "remaining_accepted_candidates": remaining_accepted,
            },
        )
        return StepOutcome("done", 0)
