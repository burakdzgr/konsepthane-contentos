"""Bounded read-only projections for the operational control center.

Every number here is computed from durable rows (or the live broker for
the queue depth) at request time — nothing is invented, cached, or
estimated. Unavailable measurements are explicit ``None``, never zero.
Attempt errors surface ONLY as their sanitized ``error_class``; no
provider payloads, keys, URLs, or traces exist in these rows by
construction.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from contentos.ai.budget import attempts_today
from contentos.ai.enums import GenerationPurpose, GenerationStatus
from contentos.ai.models import AiGenerationAttempt
from contentos.api.read_models.editorial import _FrozenModel
from contentos.auth.models import User
from contentos.discovery.enums import DiscoveryLifecycleState
from contentos.discovery.models import DiscoveryItem
from contentos.intake.enums import IntakeRunStatus
from contentos.intake.models import IntakeRun
from contentos.media.models import MediaAsset, MediaNeedSatisfaction
from contentos.operations.enums import PauseScope
from contentos.operations.service import OperationsService
from contentos.opportunities.enums import OpportunityDisposition
from contentos.opportunities.models import EditorialOpportunity, OpportunityScore
from contentos.publishing.models import PublicationAttempt, PublicationPackage
from contentos.qa.models import QaReport
from contentos.sources.enums import SourceLifecycleState
from contentos.sources.models import Source
from contentos.workflow.enums import WorkflowState
from contentos.workflow.models import EditorialWorkflowEvent, EditorialWorkItem

_logger = structlog.get_logger("contentos.api.read_models.dashboard")

MAX_ACTIVITY_LIMIT = 100
DEFAULT_ACTIVITY_LIMIT = 50
MAX_ACTIVITY_REASON_LENGTH = 200
MAX_PUBLICATION_ROWS = 20
RECENT_ATTEMPTS_PER_AGENT = 5


def _utc_day_start() -> datetime:
    return datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


def _day_start_for(session: Session) -> datetime:
    """SQLite test databases store naive UTC; PostgreSQL stores aware."""
    day_start = _utc_day_start()
    bind = session.get_bind()
    if bind is not None and bind.dialect.name == "sqlite":
        return day_start.replace(tzinfo=None)
    return day_start


# --- views -------------------------------------------------------------------


class PauseStateView(_FrozenModel):
    scope: PauseScope
    is_paused: bool
    reason: str | None
    updated_at: datetime | None


class ResearchSummaryView(_FrozenModel):
    active_sources: int
    discovery_states: dict[str, int]


class AiSummaryView(_FrozenModel):
    attempts_today: int
    failures_today: int
    daily_budget: int | None
    remaining_budget: int | None
    # Configuration truth: without these the worker cannot run ANY AI
    # task, so the admin must say so before an operator clicks.
    provider: str
    text_provider_configured: bool
    image_provider_configured: bool


class PublishingSummaryView(_FrozenModel):
    packages_total: int
    attempts_today: dict[str, int]
    last_attempt_status: str | None
    last_attempt_error_class: str | None
    last_attempt_at: datetime | None


class MediaSummaryView(_FrozenModel):
    assets_total: int
    assets_today: int
    active_satisfactions: int


class QueueSummaryView(_FrozenModel):
    # None means the broker could not be measured, never "empty".
    depth: int | None


class AttentionSummaryView(_FrozenModel):
    # REAL human decisions only, never mechanical pipeline steps.
    production_decisions: int  # scored open opportunities awaiting yes/no
    awaiting_human_review: int
    approval_expired: int
    changes_requested: int
    # Performance loop (agent E): named decisions waiting on an operator.
    refresh_decisions: int
    strategy_suggestions: int


class DashboardSummary(_FrozenModel):
    generated_at: datetime
    work_item_states: dict[str, int]
    published_today: int
    active_intake_runs: int
    attention: AttentionSummaryView
    research: ResearchSummaryView
    ai: AiSummaryView
    publishing: PublishingSummaryView
    media: MediaSummaryView
    queue: QueueSummaryView
    pauses: list[PauseStateView]


class AttemptView(_FrozenModel):
    id: uuid.UUID
    purpose: GenerationPurpose
    status: GenerationStatus
    error_class: str | None
    provider: str
    model_name: str
    retry_number: int
    created_at: datetime


class AgentView(_FrozenModel):
    key: str
    kind: str  # "ai" | "deterministic" | "transport"
    purposes: list[GenerationPurpose]
    is_paused: bool
    pause_reason: str | None
    attempts_today: int
    failures_today: int
    last_attempt: AttemptView | None
    recent_attempts: list[AttemptView]
    # Honest extras for the non-AI agents; empty when not applicable.
    metrics: dict[str, int]


class AgentsPage(_FrozenModel):
    generated_at: datetime
    engine_paused: bool
    engine_pause_reason: str | None
    agents: list[AgentView]


class ActivityEntry(_FrozenModel):
    kind: str  # "workflow" | "publication" | "pause"
    occurred_at: datetime
    work_item_id: uuid.UUID | None
    title: str | None
    from_state: str | None
    to_state: str | None
    actor_origin: str | None
    status: str | None
    error_class: str | None
    scope: str | None
    action: str | None
    reason: str | None


class ActivityPage(_FrozenModel):
    generated_at: datetime
    entries: list[ActivityEntry]


class PublicationQueueRow(_FrozenModel):
    package_id: uuid.UUID
    work_item_id: uuid.UUID
    title_working_label: str
    work_item_state: WorkflowState
    version: int
    section_count: int
    manifest_needs: int
    created_at: datetime
    attempts_total: int
    last_attempt_status: str | None
    last_attempt_error_class: str | None
    last_attempt_at: datetime | None
    remote_publication_ref: str | None


class PublicationQueuePage(_FrozenModel):
    generated_at: datetime
    rows: list[PublicationQueueRow]


class PauseEventView(_FrozenModel):
    scope: PauseScope
    action: str
    reason: str
    actor_display_name: str | None
    occurred_at: datetime


class ControlsPage(_FrozenModel):
    generated_at: datetime
    pauses: list[PauseStateView]
    recent_events: list[PauseEventView]


# --- the logical agent map ---------------------------------------------------

# UI "agents" mapped onto the REAL execution units: AI generation
# purposes for the model-backed steps, durable domain facts for the
# deterministic and transport steps. Only capabilities that exist are
# listed — nothing here invents an autonomous process.
AGENT_DEFINITIONS: list[dict[str, Any]] = [
    {"key": "research", "kind": "deterministic", "purposes": [], "scope": PauseScope.RESEARCH},
    {
        "key": "opportunity",
        "kind": "deterministic",
        "purposes": [],
        "scope": PauseScope.OPPORTUNITY,
    },
    {
        "key": "ideas",
        "kind": "ai",
        "purposes": [GenerationPurpose.IDEA_CANDIDATES],
        "scope": PauseScope.IDEAS,
    },
    {
        "key": "evidence",
        "kind": "ai",
        "purposes": [GenerationPurpose.EVIDENCE_ORGANIZATION],
        "scope": PauseScope.EVIDENCE,
    },
    {
        "key": "intent",
        "kind": "ai",
        "purposes": [GenerationPurpose.INTENT_SYNTHESIS],
        "scope": PauseScope.INTENT,
    },
    {
        "key": "brief",
        "kind": "ai",
        "purposes": [GenerationPurpose.BRIEF_COMPOSITION],
        "scope": PauseScope.BRIEF,
    },
    {
        "key": "writer",
        "kind": "ai",
        "purposes": [GenerationPurpose.WRITER_DRAFT],
        "scope": PauseScope.WRITER,
    },
    {
        "key": "editor",
        "kind": "ai",
        "purposes": [GenerationPurpose.EDITOR_REVIEW],
        "scope": PauseScope.EDITOR,
    },
    {"key": "qa", "kind": "deterministic", "purposes": [], "scope": PauseScope.QA},
    {
        "key": "media",
        "kind": "ai",
        "purposes": [GenerationPurpose.MEDIA_IMAGE],
        "scope": PauseScope.MEDIA,
    },
    {"key": "publisher", "kind": "transport", "purposes": [], "scope": PauseScope.PUBLISHER},
]


# --- queries -----------------------------------------------------------------


def _work_item_state_counts(session: Session) -> dict[str, int]:
    counts = dict.fromkeys((state.value for state in WorkflowState), 0)
    rows = session.execute(
        select(EditorialWorkItem.current_state, func.count()).group_by(
            EditorialWorkItem.current_state
        )
    ).all()
    for state, count in rows:
        counts[state.value if hasattr(state, "value") else str(state)] = int(count)
    return counts


def _published_today(session: Session) -> int:
    since = _day_start_for(session)
    return int(
        session.scalar(
            select(func.count(func.distinct(EditorialWorkflowEvent.work_item_id))).where(
                EditorialWorkflowEvent.to_state == WorkflowState.PUBLISHED,
                EditorialWorkflowEvent.occurred_at >= since,
            )
        )
        or 0
    )


def _research_summary(session: Session) -> ResearchSummaryView:
    active_sources = int(
        session.scalar(
            select(func.count())
            .select_from(Source)
            .where(Source.lifecycle_state == SourceLifecycleState.ACTIVE)
        )
        or 0
    )
    states = dict.fromkeys((state.value for state in DiscoveryLifecycleState), 0)
    for state, count in session.execute(
        select(DiscoveryItem.lifecycle_state, func.count()).group_by(DiscoveryItem.lifecycle_state)
    ).all():
        states[state.value if hasattr(state, "value") else str(state)] = int(count)
    return ResearchSummaryView(active_sources=active_sources, discovery_states=states)


def _ai_summary(
    session: Session,
    daily_budget: int | None,
    *,
    provider: str,
    text_provider_configured: bool,
    image_provider_configured: bool,
) -> AiSummaryView:
    used = attempts_today(session)
    since = _day_start_for(session)
    failures = int(
        session.scalar(
            select(func.count())
            .select_from(AiGenerationAttempt)
            .where(
                AiGenerationAttempt.created_at >= since,
                AiGenerationAttempt.status != GenerationStatus.SUCCEEDED,
            )
        )
        or 0
    )
    remaining = None if daily_budget is None else max(daily_budget - used, 0)
    return AiSummaryView(
        attempts_today=used,
        failures_today=failures,
        daily_budget=daily_budget,
        remaining_budget=remaining,
        provider=provider,
        text_provider_configured=text_provider_configured,
        image_provider_configured=image_provider_configured,
    )


def _publishing_summary(session: Session) -> PublishingSummaryView:
    packages_total = int(session.scalar(select(func.count()).select_from(PublicationPackage)) or 0)
    since = _day_start_for(session)
    attempts: dict[str, int] = {}
    for status, count in session.execute(
        select(PublicationAttempt.status, func.count())
        .where(PublicationAttempt.created_at >= since)
        .group_by(PublicationAttempt.status)
    ).all():
        attempts[str(status)] = int(count)
    last = session.scalars(
        select(PublicationAttempt).order_by(PublicationAttempt.created_at.desc()).limit(1)
    ).first()
    return PublishingSummaryView(
        packages_total=packages_total,
        attempts_today=attempts,
        last_attempt_status=last.status if last is not None else None,
        last_attempt_error_class=last.error_class if last is not None else None,
        last_attempt_at=last.created_at if last is not None else None,
    )


def _media_summary(session: Session) -> MediaSummaryView:
    since = _day_start_for(session)
    assets_total = int(session.scalar(select(func.count()).select_from(MediaAsset)) or 0)
    assets_today = int(
        session.scalar(
            select(func.count()).select_from(MediaAsset).where(MediaAsset.created_at >= since)
        )
        or 0
    )
    active = int(
        session.scalar(
            select(func.count())
            .select_from(MediaNeedSatisfaction)
            .where(MediaNeedSatisfaction.status == "active")
        )
        or 0
    )
    return MediaSummaryView(
        assets_total=assets_total, assets_today=assets_today, active_satisfactions=active
    )


def measure_queue_depth(client_factory: Any, queue_name: str) -> int | None:
    """LLEN of the broker list; None (never zero) when unmeasurable."""
    try:
        with client_factory() as client:
            return int(client.llen(queue_name))
    except Exception as exc:
        _logger.warning(
            "dashboard_queue_depth_unavailable",
            error_type=type(exc).__name__,
        )
        return None


def _pause_views(session: Session) -> list[PauseStateView]:
    return [
        PauseStateView(
            scope=state.scope,
            is_paused=state.is_paused,
            reason=state.reason,
            updated_at=state.updated_at,
        )
        for state in OperationsService(session).states()
    ]


def _attention_summary(session: Session, states: dict[str, int]) -> AttentionSummaryView:
    production_decisions = int(
        session.scalar(
            select(func.count(func.distinct(EditorialOpportunity.id)))
            .select_from(EditorialOpportunity)
            .join(OpportunityScore, OpportunityScore.opportunity_id == EditorialOpportunity.id)
            .where(EditorialOpportunity.disposition == OpportunityDisposition.OPEN)
        )
        or 0
    )
    from contentos.performance.enums import RefreshStatus, SuggestionStatus
    from contentos.performance.models import RefreshOpportunity, StrategySuggestion

    refresh_decisions = int(
        session.scalar(
            select(func.count())
            .select_from(RefreshOpportunity)
            .where(RefreshOpportunity.status == RefreshStatus.PROPOSED)
        )
        or 0
    )
    strategy_suggestions = int(
        session.scalar(
            select(func.count())
            .select_from(StrategySuggestion)
            .where(StrategySuggestion.status == SuggestionStatus.PROPOSED)
        )
        or 0
    )
    return AttentionSummaryView(
        production_decisions=production_decisions,
        awaiting_human_review=states.get("awaiting_human_review", 0),
        approval_expired=states.get("approval_expired", 0),
        changes_requested=states.get("changes_requested", 0),
        refresh_decisions=refresh_decisions,
        strategy_suggestions=strategy_suggestions,
    )


def _active_intake_runs(session: Session) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(IntakeRun)
            .where(IntakeRun.status.in_((IntakeRunStatus.RUNNING, IntakeRunStatus.PAUSED)))
        )
        or 0
    )


def load_summary(
    session: Session,
    *,
    daily_budget: int | None,
    queue_depth: int | None,
    provider: str = "openai",
    text_provider_configured: bool = False,
    image_provider_configured: bool = False,
) -> DashboardSummary:
    states = _work_item_state_counts(session)
    return DashboardSummary(
        generated_at=datetime.now(UTC),
        work_item_states=states,
        published_today=_published_today(session),
        active_intake_runs=_active_intake_runs(session),
        attention=_attention_summary(session, states),
        research=_research_summary(session),
        ai=_ai_summary(
            session,
            daily_budget,
            provider=provider,
            text_provider_configured=text_provider_configured,
            image_provider_configured=image_provider_configured,
        ),
        publishing=_publishing_summary(session),
        media=_media_summary(session),
        queue=QueueSummaryView(depth=queue_depth),
        pauses=_pause_views(session),
    )


def _attempt_view(row: AiGenerationAttempt) -> AttemptView:
    return AttemptView(
        id=row.id,
        purpose=row.purpose,
        status=row.status,
        error_class=row.error_class,
        provider=row.provider,
        model_name=row.model_name,
        retry_number=row.retry_number,
        created_at=row.created_at,
    )


def _agent_metrics(session: Session, key: str) -> dict[str, int]:
    """Durable facts for the non-AI agents; {} where not applicable."""
    if key == "research":
        states = _research_summary(session).discovery_states
        return {
            "discovered": states.get("discovered", 0),
            "accepted": states.get("accepted", 0),
            "fetched": states.get("fetched", 0),
            "fetch_failed": states.get("fetch_failed", 0),
        }
    if key == "opportunity":
        metrics: dict[str, int] = {}
        for disposition, count in session.execute(
            select(EditorialOpportunity.disposition, func.count()).group_by(
                EditorialOpportunity.disposition
            )
        ).all():
            value = (
                disposition.value
                if isinstance(disposition, OpportunityDisposition)
                else str(disposition)
            )
            metrics[value] = int(count)
        return metrics
    if key == "qa":
        since = _day_start_for(session)
        reports_today = int(
            session.scalar(
                select(func.count()).select_from(QaReport).where(QaReport.created_at >= since)
            )
            or 0
        )
        return {"reports_today": reports_today}
    if key == "publisher":
        summary = _publishing_summary(session)
        return {f"attempts_{status}": count for status, count in summary.attempts_today.items()}
    return {}


def load_agents(session: Session) -> AgentsPage:
    since = _day_start_for(session)
    operations = OperationsService(session)
    engine = operations.state_for(PauseScope.ENGINE)
    pause_by_scope = {state.scope: state for state in operations.states()}

    # One grouped query for today's attempt counts across all purposes.
    counts: dict[GenerationPurpose, dict[str, int]] = {}
    for purpose, status, count in session.execute(
        select(AiGenerationAttempt.purpose, AiGenerationAttempt.status, func.count())
        .where(AiGenerationAttempt.created_at >= since)
        .group_by(AiGenerationAttempt.purpose, AiGenerationAttempt.status)
    ).all():
        bucket = counts.setdefault(purpose, {"total": 0, "failed": 0})
        bucket["total"] += int(count)
        if status != GenerationStatus.SUCCEEDED:
            bucket["failed"] += int(count)

    agents: list[AgentView] = []
    for definition in AGENT_DEFINITIONS:
        purposes: list[GenerationPurpose] = definition["purposes"]
        pause = pause_by_scope[definition["scope"]]
        attempts_today_count = sum(counts.get(purpose, {}).get("total", 0) for purpose in purposes)
        failures_today = sum(counts.get(purpose, {}).get("failed", 0) for purpose in purposes)
        recent: list[AttemptView] = []
        if purposes:
            rows = session.scalars(
                select(AiGenerationAttempt)
                .where(AiGenerationAttempt.purpose.in_(purposes))
                .order_by(AiGenerationAttempt.created_at.desc())
                .limit(RECENT_ATTEMPTS_PER_AGENT)
            ).all()
            recent = [_attempt_view(row) for row in rows]
        agents.append(
            AgentView(
                key=definition["key"],
                kind=definition["kind"],
                purposes=purposes,
                is_paused=pause.is_paused,
                pause_reason=pause.reason,
                attempts_today=attempts_today_count,
                failures_today=failures_today,
                last_attempt=recent[0] if recent else None,
                recent_attempts=recent,
                metrics=_agent_metrics(session, definition["key"]),
            )
        )
    return AgentsPage(
        generated_at=datetime.now(UTC),
        engine_paused=engine.is_paused,
        engine_pause_reason=engine.reason,
        agents=agents,
    )


def _bounded_reason(reason: str | None) -> str | None:
    if reason is None:
        return None
    if len(reason) <= MAX_ACTIVITY_REASON_LENGTH:
        return reason
    return reason[: MAX_ACTIVITY_REASON_LENGTH - 1] + "…"


def load_activity(session: Session, *, limit: int = DEFAULT_ACTIVITY_LIMIT) -> ActivityPage:
    bounded = max(1, min(limit, MAX_ACTIVITY_LIMIT))
    entries: list[ActivityEntry] = []

    workflow_rows = session.execute(
        select(EditorialWorkflowEvent, EditorialWorkItem.title_working_label)
        .join(EditorialWorkItem, EditorialWorkItem.id == EditorialWorkflowEvent.work_item_id)
        .order_by(EditorialWorkflowEvent.id.desc())
        .limit(bounded)
    ).all()
    for event, title in workflow_rows:
        entries.append(
            ActivityEntry(
                kind="workflow",
                occurred_at=event.occurred_at,
                work_item_id=event.work_item_id,
                title=title,
                from_state=event.from_state.value if event.from_state is not None else None,
                to_state=event.to_state.value,
                actor_origin=event.actor_origin.value,
                status=None,
                error_class=None,
                scope=None,
                action=None,
                reason=_bounded_reason(event.reason),
            )
        )

    attempt_rows = session.execute(
        select(
            PublicationAttempt,
            PublicationPackage.work_item_id,
            EditorialWorkItem.title_working_label,
        )
        .join(
            PublicationPackage,
            PublicationPackage.id == PublicationAttempt.publication_package_id,
        )
        .join(EditorialWorkItem, EditorialWorkItem.id == PublicationPackage.work_item_id)
        .order_by(PublicationAttempt.created_at.desc())
        .limit(bounded)
    ).all()
    for attempt, work_item_id, title in attempt_rows:
        entries.append(
            ActivityEntry(
                kind="publication",
                occurred_at=attempt.created_at,
                work_item_id=work_item_id,
                title=title,
                from_state=None,
                to_state=None,
                actor_origin=None,
                status=attempt.status,
                error_class=attempt.error_class,
                scope=None,
                action=None,
                reason=None,
            )
        )

    for event in OperationsService(session).recent_events(limit=bounded):
        entries.append(
            ActivityEntry(
                kind="pause",
                occurred_at=event.occurred_at,
                work_item_id=None,
                title=None,
                from_state=None,
                to_state=None,
                actor_origin=None,
                status=None,
                error_class=None,
                scope=event.scope.value,
                action=event.action.value,
                reason=_bounded_reason(event.reason),
            )
        )

    entries.sort(key=lambda entry: entry.occurred_at, reverse=True)
    return ActivityPage(generated_at=datetime.now(UTC), entries=entries[:bounded])


def load_publication_queue(session: Session) -> PublicationQueuePage:
    packages = session.execute(
        select(PublicationPackage, EditorialWorkItem)
        .join(EditorialWorkItem, EditorialWorkItem.id == PublicationPackage.work_item_id)
        .order_by(PublicationPackage.created_at.desc())
        .limit(MAX_PUBLICATION_ROWS)
    ).all()
    rows: list[PublicationQueueRow] = []
    for package, work_item in packages:
        attempts = session.scalars(
            select(PublicationAttempt)
            .where(PublicationAttempt.publication_package_id == package.id)
            .order_by(PublicationAttempt.attempt_number.desc())
        ).all()
        last = attempts[0] if attempts else None
        body = package.payload.get("body") or {}
        sections = body.get("sections") if isinstance(body, dict) else None
        manifest = package.media_manifest or {}
        rows.append(
            PublicationQueueRow(
                package_id=package.id,
                work_item_id=work_item.id,
                title_working_label=work_item.title_working_label,
                work_item_state=work_item.current_state,
                version=package.version,
                section_count=len(sections) if isinstance(sections, list) else 0,
                manifest_needs=len(manifest.get("needs", {}) or {}),
                created_at=package.created_at,
                attempts_total=len(attempts),
                last_attempt_status=last.status if last is not None else None,
                last_attempt_error_class=last.error_class if last is not None else None,
                last_attempt_at=last.created_at if last is not None else None,
                remote_publication_ref=last.remote_publication_ref if last is not None else None,
            )
        )
    return PublicationQueuePage(generated_at=datetime.now(UTC), rows=rows)


def load_controls(session: Session) -> ControlsPage:
    events = OperationsService(session).recent_events(limit=20)
    actor_ids = {event.actor_user_id for event in events if event.actor_user_id is not None}
    names: dict[uuid.UUID, str] = {}
    if actor_ids:
        for user in session.scalars(select(User).where(User.id.in_(actor_ids))).all():
            names[user.id] = user.display_name
    return ControlsPage(
        generated_at=datetime.now(UTC),
        pauses=_pause_views(session),
        recent_events=[
            PauseEventView(
                scope=event.scope,
                action=event.action.value,
                reason=event.reason,
                actor_display_name=(
                    names.get(event.actor_user_id) if event.actor_user_id is not None else None
                ),
                occurred_at=event.occurred_at,
            )
            for event in events
        ],
    )
