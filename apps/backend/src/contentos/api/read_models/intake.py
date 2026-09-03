"""Bounded read-only projections of intake runs and their timelines."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from contentos.api.read_models.editorial import _FrozenModel
from contentos.discovery.enums import DiscoveryLifecycleState
from contentos.discovery.models import DiscoveryItem
from contentos.intake.enums import IntakeEventKind, IntakeRunStatus, IntakeStage
from contentos.intake.models import IntakeRun, IntakeRunEvent
from contentos.intake.service import IntakeRunService
from contentos.sources.models import Source

MAX_RUN_ROWS = 25
MAX_EVENT_ROWS = 200
DEFAULT_EVENT_ROWS = 80


class IntakeEventView(_FrozenModel):
    id: int
    stage: IntakeStage
    kind: IntakeEventKind
    detail: dict[str, object]
    occurred_at: datetime


class IntakeStageView(_FrozenModel):
    key: str
    # "done" | "active" | "pending" — derived from durable run state.
    state: str
    counts: dict[str, int]


class IntakeRunView(_FrozenModel):
    id: uuid.UUID
    source_id: uuid.UUID
    source_slug: str
    source_name: str
    status: IntakeRunStatus
    discovered_new: int
    rediscovered: int
    prefilter_accepted: int
    prefilter_rejected: int
    fetch_dispatched: int
    fetched: int
    fetch_failed: int
    promotions_dispatched: int
    opportunities_created: int
    remaining_accepted: int
    remaining_discovered: int
    policy: dict[str, object]
    failure_note: str | None
    created_at: datetime
    discovery_completed_at: datetime | None
    prefilter_completed_at: datetime | None
    finished_at: datetime | None
    updated_at: datetime
    last_event_at: datetime | None


class IntakeChainView(_FrozenModel):
    """Durable downstream facts for the run's dispatched items: what the
    worker-owned fetch→normalize→duplicate chain actually produced."""

    normalized_succeeded: int
    normalized_failed: int
    duplicates_evaluated: int
    last_processed_title: str | None
    last_processed_url: str | None


class IntakeRunDetail(_FrozenModel):
    generated_at: datetime
    run: IntakeRunView
    chain: IntakeChainView
    stages: list[IntakeStageView]
    events: list[IntakeEventView]


class IntakeRunsPage(_FrozenModel):
    generated_at: datetime
    runs: list[IntakeRunView]


class IntakeEventsPage(_FrozenModel):
    generated_at: datetime
    events: list[IntakeEventView]


def _remaining_counts(session: Session, source_id: uuid.UUID) -> tuple[int, int]:
    rows: dict[DiscoveryLifecycleState, int] = {
        state: int(count)
        for state, count in session.execute(
            select(DiscoveryItem.lifecycle_state, func.count())
            .where(DiscoveryItem.source_id == source_id)
            .group_by(DiscoveryItem.lifecycle_state)
        ).all()
    }
    accepted = int(rows.get(DiscoveryLifecycleState.ACCEPTED, 0))
    discovered = int(rows.get(DiscoveryLifecycleState.DISCOVERED, 0))
    return accepted, discovered


def _run_view(session: Session, run: IntakeRun, source: Source) -> IntakeRunView:
    remaining_accepted, remaining_discovered = _remaining_counts(session, run.source_id)
    last_event_at = session.scalar(
        select(func.max(IntakeRunEvent.occurred_at)).where(IntakeRunEvent.run_id == run.id)
    )
    return IntakeRunView(
        id=run.id,
        source_id=run.source_id,
        source_slug=source.slug,
        source_name=source.name,
        status=run.status,
        discovered_new=run.discovered_new,
        rediscovered=run.rediscovered,
        prefilter_accepted=run.prefilter_accepted,
        prefilter_rejected=run.prefilter_rejected,
        fetch_dispatched=run.fetch_dispatched,
        fetched=run.fetched,
        fetch_failed=run.fetch_failed,
        promotions_dispatched=run.promotions_dispatched,
        opportunities_created=run.opportunities_created,
        remaining_accepted=remaining_accepted,
        remaining_discovered=remaining_discovered,
        policy=dict(run.policy),
        failure_note=run.failure_note,
        created_at=run.created_at,
        discovery_completed_at=run.discovery_completed_at,
        prefilter_completed_at=run.prefilter_completed_at,
        finished_at=run.finished_at,
        updated_at=run.updated_at,
        last_event_at=last_event_at,
    )


def _dispatched_item_ids(session: Session, run_id: uuid.UUID) -> list[uuid.UUID]:
    ids: list[uuid.UUID] = []
    for event in session.scalars(
        select(IntakeRunEvent).where(
            IntakeRunEvent.run_id == run_id,
            IntakeRunEvent.kind == IntakeEventKind.FETCH_ITEM_DISPATCHED,
        )
    ).all():
        raw = event.detail.get("discovery_item_id")
        try:
            ids.append(uuid.UUID(str(raw)))
        except (ValueError, TypeError):
            continue
    return ids


def _chain_view(session: Session, run_id: uuid.UUID) -> IntakeChainView:
    from contentos.duplicates.models import DuplicateDecision
    from contentos.fetching.snapshots import FetchSnapshot
    from contentos.normalization.enums import NormalizationStatus
    from contentos.normalization.models import NormalizedDocument

    item_ids = _dispatched_item_ids(session, run_id)
    if not item_ids:
        return IntakeChainView(
            normalized_succeeded=0,
            normalized_failed=0,
            duplicates_evaluated=0,
            last_processed_title=None,
            last_processed_url=None,
        )
    status_counts = {
        status: int(count)
        for status, count in session.execute(
            select(NormalizedDocument.normalization_status, func.count())
            .join(FetchSnapshot, FetchSnapshot.id == NormalizedDocument.fetch_snapshot_id)
            .where(FetchSnapshot.discovery_item_id.in_(item_ids))
            .group_by(NormalizedDocument.normalization_status)
        ).all()
    }
    document_ids = (
        select(NormalizedDocument.id)
        .join(FetchSnapshot, FetchSnapshot.id == NormalizedDocument.fetch_snapshot_id)
        .where(FetchSnapshot.discovery_item_id.in_(item_ids))
    )
    duplicates = int(
        session.scalar(
            select(func.count(func.distinct(DuplicateDecision.normalized_document_id))).where(
                DuplicateDecision.normalized_document_id.in_(document_ids)
            )
        )
        or 0
    )
    last = session.execute(
        select(NormalizedDocument.title, FetchSnapshot.final_url, FetchSnapshot.requested_url)
        .join(FetchSnapshot, FetchSnapshot.id == NormalizedDocument.fetch_snapshot_id)
        .where(
            FetchSnapshot.discovery_item_id.in_(item_ids),
            NormalizedDocument.normalization_status == NormalizationStatus.SUCCEEDED,
        )
        .order_by(NormalizedDocument.normalized_at.desc())
        .limit(1)
    ).first()
    return IntakeChainView(
        normalized_succeeded=status_counts.get(NormalizationStatus.SUCCEEDED, 0),
        normalized_failed=status_counts.get(NormalizationStatus.FAILED, 0),
        duplicates_evaluated=duplicates,
        last_processed_title=last[0] if last is not None else None,
        last_processed_url=(last[1] or last[2]) if last is not None else None,
    )


def _stages(run: IntakeRunView, chain: IntakeChainView) -> list[IntakeStageView]:
    finished = run.finished_at is not None
    discovery_done = run.discovery_completed_at is not None
    prefilter_done = run.prefilter_completed_at is not None
    fetch_done = finished or (
        prefilter_done
        and run.fetch_dispatched > 0
        and run.fetched + run.fetch_failed >= run.fetch_dispatched
        and run.remaining_accepted == 0
    )

    def state(done: bool, active: bool) -> str:
        if done:
            return "done"
        return "active" if active else "pending"

    return [
        IntakeStageView(
            key="discovery",
            state=state(discovery_done, not discovery_done),
            counts={"new": run.discovered_new, "rediscovered": run.rediscovered},
        ),
        IntakeStageView(
            key="prefilter",
            state=state(prefilter_done, discovery_done and not prefilter_done),
            counts={
                "accepted": run.prefilter_accepted,
                "rejected": run.prefilter_rejected,
                "remaining": run.remaining_discovered,
            },
        ),
        IntakeStageView(
            key="fetch",
            state=state(
                finished or (prefilter_done and fetch_done),
                prefilter_done and not finished and not fetch_done,
            ),
            counts={
                "dispatched": run.fetch_dispatched,
                "fetched": run.fetched,
                "failed": run.fetch_failed,
                "waiting_candidates": run.remaining_accepted,
            },
        ),
        IntakeStageView(
            key="normalize",
            state=state(
                finished
                or (
                    fetch_done
                    and chain.normalized_succeeded + chain.normalized_failed >= run.fetched
                ),
                run.fetch_dispatched > 0
                and not finished
                and chain.normalized_succeeded + chain.normalized_failed < run.fetched,
            ),
            counts={
                "succeeded": chain.normalized_succeeded,
                "failed": chain.normalized_failed,
            },
        ),
        IntakeStageView(
            key="duplicate",
            state=state(
                finished
                or (fetch_done and chain.duplicates_evaluated >= chain.normalized_succeeded),
                chain.normalized_succeeded > 0
                and not finished
                and chain.duplicates_evaluated < chain.normalized_succeeded,
            ),
            counts={"evaluated": chain.duplicates_evaluated},
        ),
        IntakeStageView(
            key="promote",
            state=state(
                finished,
                prefilter_done and not finished and run.promotions_dispatched > 0,
            ),
            counts={
                "dispatched": run.promotions_dispatched,
                "opportunities": run.opportunities_created,
            },
        ),
    ]


def _event_view(event: IntakeRunEvent) -> IntakeEventView:
    return IntakeEventView(
        id=event.id,
        stage=event.stage,
        kind=event.kind,
        detail=dict(event.detail),
        occurred_at=event.occurred_at,
    )


def load_runs(session: Session, *, source_id: uuid.UUID | None = None) -> IntakeRunsPage:
    query = select(IntakeRun, Source).join(Source, Source.id == IntakeRun.source_id)
    if source_id is not None:
        query = query.where(IntakeRun.source_id == source_id)
    rows = session.execute(query.order_by(IntakeRun.created_at.desc()).limit(MAX_RUN_ROWS)).all()
    return IntakeRunsPage(
        generated_at=datetime.now(UTC),
        runs=[_run_view(session, run, source) for run, source in rows],
    )


def load_run_detail(session: Session, run_id: uuid.UUID) -> IntakeRunDetail | None:
    row = session.execute(
        select(IntakeRun, Source)
        .join(Source, Source.id == IntakeRun.source_id)
        .where(IntakeRun.id == run_id)
    ).first()
    if row is None:
        return None
    run, source = row
    view = _run_view(session, run, source)
    chain = _chain_view(session, run.id)
    events = [
        _event_view(event)
        for event in IntakeRunService(session).events_for(run_id, limit=DEFAULT_EVENT_ROWS)
    ]
    return IntakeRunDetail(
        generated_at=datetime.now(UTC),
        run=view,
        chain=chain,
        stages=_stages(view, chain),
        events=events,
    )


def load_run_events(
    session: Session, run_id: uuid.UUID, *, after_id: int | None, limit: int
) -> IntakeEventsPage:
    bounded = max(1, min(limit, MAX_EVENT_ROWS))
    events = IntakeRunService(session).events_for(run_id, after_id=after_id, limit=bounded)
    return IntakeEventsPage(
        generated_at=datetime.now(UTC),
        events=[_event_view(event) for event in events],
    )
