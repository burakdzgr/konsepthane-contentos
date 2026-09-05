"""Bounded read-only projections of the performance loop.

Every value here is a durable row (published content, snapshot,
assessment, decision) projected at request time. Missing provider data is
an explicit ``None`` / ``unknown`` / ``insufficient_data`` — never a zero.
Nothing here writes, enqueues, or talks to a provider; provider credentials,
URLs, or raw responses do not exist in these rows by construction.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from contentos.auth.models import User
from contentos.performance.enums import (
    ASSESSMENT_WINDOWS,
    AssessmentStatus,
    PerformanceProvider,
    RefreshStatus,
    SuggestionKind,
    SuggestionStatus,
)
from contentos.performance.history import historical_signal_for
from contentos.performance.models import (
    ContentPerformanceSnapshot,
    PerformanceAssessment,
    PublishedContent,
    RefreshOpportunity,
    StrategySuggestion,
)
from contentos.performance.refresh import RefreshOpportunityService
from contentos.performance.service import PerformanceService, top_queries
from contentos.performance.suggestions import StrategySuggestionService
from contentos.strategy.models import AudienceStrategy, TopicCluster
from contentos.workflow.models import EditorialWorkItem

MAX_SERIES_POINTS = 120
MAX_LIST_ROWS = 100


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class ProviderFreshnessView(_FrozenModel):
    provider: PerformanceProvider
    last_observed_at: datetime | None
    # Provider state as the integration layer reports it; None = unknown here.
    state: str | None


class AssessmentView(_FrozenModel):
    id: uuid.UUID
    window_days: int
    status: AssessmentStatus
    assessed_at: datetime
    engine_name: str
    engine_version: str
    basis: dict[str, Any]


class PublishedContentRow(_FrozenModel):
    published_content_id: uuid.UUID
    work_item_id: uuid.UUID
    title_working_label: str
    current_state: str
    canonical_url: str | None
    canonical_url_missing: bool
    remote_publication_ref: str
    published_at: datetime
    age_days: int
    topic_cluster_id: uuid.UUID | None
    cluster_name: str | None
    audience_id: uuid.UUID | None
    audience_name: str | None
    theme_key: str | None
    content_format: str | None
    assessment: AssessmentView | None
    impressions: int | None
    clicks: int | None
    position: float | None
    ctr: float | None
    impressions_pct: float | None
    clicks_pct: float | None
    has_open_refresh: bool


class ClusterOverviewView(_FrozenModel):
    cluster_id: uuid.UUID | None
    cluster_name: str
    published: int
    rising: int
    stable: int
    declining: int
    volatile: int
    new: int
    insufficient: int
    unknown: int
    sufficient: bool


class OverviewTotalsView(_FrozenModel):
    published: int
    rising: int
    stable: int
    declining: int
    volatile: int
    new: int
    insufficient: int
    unknown: int


class PerformanceOverviewView(_FrozenModel):
    generated_at: datetime
    window_days: int
    totals: OverviewTotalsView
    rising: list[PublishedContentRow]
    declining: list[PublishedContentRow]
    stable: list[PublishedContentRow]
    volatile: list[PublishedContentRow]
    new: list[PublishedContentRow]
    insufficient: list[PublishedContentRow]
    clusters: list[ClusterOverviewView]
    freshness: list[ProviderFreshnessView]
    pending_refresh_decisions: int
    pending_strategy_suggestions: int
    schedule_enabled: bool


class SeriesPointView(_FrozenModel):
    period_start: date
    period_end: date
    observed_at: datetime
    metrics: dict[str, Any]


class RefreshOpportunityView(_FrozenModel):
    id: uuid.UUID
    published_content_id: uuid.UUID
    work_item_id: uuid.UUID
    title_working_label: str
    current_state: str
    status: RefreshStatus
    trigger_assessment_id: uuid.UUID
    window_days: int | None
    diagnosis: dict[str, Any]
    recommendation: str
    proposed_at: datetime
    decided_at: datetime | None
    decided_by_display_name: str | None
    decision_reason: str | None


class StrategySuggestionView(_FrozenModel):
    id: uuid.UUID
    kind: SuggestionKind
    title: str
    rationale: str
    basis: dict[str, Any]
    status: SuggestionStatus
    proposed_at: datetime
    decided_at: datetime | None
    decided_by_display_name: str | None
    decision_reason: str | None


class ContentPerformanceDetailView(_FrozenModel):
    content: PublishedContentRow
    assessments: list[AssessmentView]
    search_console_daily: list[SeriesPointView]
    search_console_summary: list[SeriesPointView]
    top_queries: list[dict[str, Any]]
    analytics: list[SeriesPointView]
    google_trends: list[SeriesPointView]
    pinterest_trends: list[SeriesPointView]
    semrush: list[SeriesPointView]
    refresh: RefreshOpportunityView | None
    refresh_history: list[RefreshOpportunityView]
    historical_signal: dict[str, Any]


def _assessment_view(row: PerformanceAssessment) -> AssessmentView:
    return AssessmentView(
        id=row.id,
        window_days=row.window_days,
        status=row.status,
        assessed_at=row.assessed_at,
        engine_name=row.engine_name,
        engine_version=row.engine_version,
        basis=dict(row.basis),
    )


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    return float(value) if isinstance(value, int | float) else None


def _int(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


class _Lookups:
    def __init__(self, session: Session) -> None:
        self.clusters = {row.id: row.name for row in session.scalars(select(TopicCluster))}
        self.audiences = {row.id: row.name for row in session.scalars(select(AudienceStrategy))}
        self.work_items = {row.id: row for row in session.scalars(select(EditorialWorkItem))}
        self.users = {row.id: row.display_name for row in session.scalars(select(User))}


def _content_row(
    content: PublishedContent,
    assessment: PerformanceAssessment | None,
    lookups: _Lookups,
    *,
    now: datetime,
    has_open_refresh: bool,
) -> PublishedContentRow:
    work_item = lookups.work_items.get(content.work_item_id)
    current = assessment.basis.get("current") if assessment is not None else None
    deltas = assessment.basis.get("deltas") if assessment is not None else None
    current_dict = current if isinstance(current, dict) else {}
    delta_dict = deltas if isinstance(deltas, dict) else {}
    return PublishedContentRow(
        published_content_id=content.id,
        work_item_id=content.work_item_id,
        title_working_label=work_item.title_working_label if work_item else "—",
        current_state=work_item.current_state.value if work_item else "unknown",
        canonical_url=content.canonical_url,
        canonical_url_missing=content.canonical_url is None,
        remote_publication_ref=content.remote_publication_ref,
        published_at=content.published_at,
        age_days=max(0, (now - content.published_at).days),
        topic_cluster_id=content.topic_cluster_id,
        cluster_name=(
            lookups.clusters.get(content.topic_cluster_id) if content.topic_cluster_id else None
        ),
        audience_id=content.audience_id,
        audience_name=lookups.audiences.get(content.audience_id) if content.audience_id else None,
        theme_key=content.theme_key,
        content_format=content.content_format,
        assessment=_assessment_view(assessment) if assessment is not None else None,
        impressions=_int(current_dict.get("impressions")),
        clicks=_int(current_dict.get("clicks")),
        position=_number(current_dict.get("position")),
        ctr=_number(current_dict.get("ctr")),
        impressions_pct=_number(delta_dict.get("impressions_pct")),
        clicks_pct=_number(delta_dict.get("clicks_pct")),
        has_open_refresh=has_open_refresh,
    )


def load_overview(
    session: Session,
    *,
    window_days: int,
    provider_states: dict[str, str | None] | None = None,
    schedule_enabled: bool,
    now: datetime | None = None,
) -> PerformanceOverviewView:
    if window_days not in ASSESSMENT_WINDOWS:
        raise ValueError("window_days must be one of 7, 28, 90")
    moment = now if now is not None else datetime.now(UTC)
    performance = PerformanceService(session)
    refresh = RefreshOpportunityService(session)
    lookups = _Lookups(session)
    latest = performance.latest_assessments_for_all(window_days)
    open_refresh = {
        row.published_content_id for row in refresh.list_opportunities(RefreshStatus.PROPOSED)
    }
    buckets: dict[str, list[PublishedContentRow]] = {
        key: [] for key in ("rising", "declining", "stable", "volatile", "new", "insufficient")
    }
    totals = dict.fromkeys(
        (
            "published",
            "rising",
            "stable",
            "declining",
            "volatile",
            "new",
            "insufficient",
            "unknown",
        ),
        0,
    )
    for content in performance.list_published():
        assessment = latest.get(content.id)
        row = _content_row(
            content,
            assessment,
            lookups,
            now=moment,
            has_open_refresh=content.id in open_refresh,
        )
        totals["published"] += 1
        is_new = moment - content.published_at <= timedelta(days=window_days)
        if is_new:
            totals["new"] += 1
            buckets["new"].append(row)
        status = assessment.status if assessment is not None else AssessmentStatus.UNKNOWN
        if status is AssessmentStatus.INSUFFICIENT_DATA:
            totals["insufficient"] += 1
            buckets["insufficient"].append(row)
        elif status is AssessmentStatus.UNKNOWN:
            totals["unknown"] += 1
            if not is_new:
                buckets["insufficient"].append(row)
        else:
            totals[status.value] += 1
            buckets[status.value].append(row)
    freshness = performance.freshness()
    states = provider_states or {}
    return PerformanceOverviewView(
        generated_at=moment,
        window_days=window_days,
        totals=OverviewTotalsView(**totals),
        rising=buckets["rising"][:MAX_LIST_ROWS],
        declining=buckets["declining"][:MAX_LIST_ROWS],
        stable=buckets["stable"][:MAX_LIST_ROWS],
        volatile=buckets["volatile"][:MAX_LIST_ROWS],
        new=buckets["new"][:MAX_LIST_ROWS],
        insufficient=buckets["insufficient"][:MAX_LIST_ROWS],
        clusters=[
            ClusterOverviewView(
                cluster_id=row.cluster_id,
                cluster_name=row.cluster_name,
                published=row.published,
                rising=row.rising,
                stable=row.stable,
                declining=row.declining,
                volatile=row.volatile,
                new=row.new,
                insufficient=row.insufficient,
                unknown=row.unknown,
                sufficient=row.sufficient,
            )
            for row in performance.cluster_overview(window_days, now=moment)
        ],
        freshness=[
            ProviderFreshnessView(
                provider=provider,
                last_observed_at=freshness.get(provider.value),
                state=states.get(provider.value),
            )
            for provider in PerformanceProvider
        ],
        pending_refresh_decisions=len(open_refresh),
        pending_strategy_suggestions=StrategySuggestionService(session).pending_count(),
        schedule_enabled=schedule_enabled,
    )


def _series(rows: list[ContentPerformanceSnapshot], *, daily: bool | None) -> list[SeriesPointView]:
    selected = [
        row for row in rows if daily is None or ((row.period_start == row.period_end) is daily)
    ]
    # Latest observation per period wins; append-only rows may repeat a period.
    latest: dict[tuple[date, date], ContentPerformanceSnapshot] = {}
    for row in selected:
        key = (row.period_start, row.period_end)
        if key not in latest or row.observed_at > latest[key].observed_at:
            latest[key] = row
    ordered = sorted(latest.values(), key=lambda row: (row.period_end, row.period_start))
    return [
        SeriesPointView(
            period_start=row.period_start,
            period_end=row.period_end,
            observed_at=row.observed_at,
            metrics=dict(row.metrics),
        )
        for row in ordered[-MAX_SERIES_POINTS:]
    ]


def refresh_view(row: RefreshOpportunity, session: Session) -> RefreshOpportunityView:
    lookups = _Lookups(session)
    return _refresh_view(row, session, lookups)


def _refresh_view(
    row: RefreshOpportunity, session: Session, lookups: _Lookups
) -> RefreshOpportunityView:
    content = session.get(PublishedContent, row.published_content_id)
    work_item = lookups.work_items.get(content.work_item_id) if content is not None else None
    assessment = session.get(PerformanceAssessment, row.trigger_assessment_id)
    return RefreshOpportunityView(
        id=row.id,
        published_content_id=row.published_content_id,
        work_item_id=content.work_item_id if content is not None else uuid.UUID(int=0),
        title_working_label=work_item.title_working_label if work_item else "—",
        current_state=work_item.current_state.value if work_item else "unknown",
        status=row.status,
        trigger_assessment_id=row.trigger_assessment_id,
        window_days=assessment.window_days if assessment is not None else None,
        diagnosis=dict(row.diagnosis),
        recommendation=row.recommendation,
        proposed_at=row.proposed_at,
        decided_at=row.decided_at,
        decided_by_display_name=(
            lookups.users.get(row.decided_by_user_id) if row.decided_by_user_id else None
        ),
        decision_reason=row.decision_reason,
    )


def list_refresh_views(
    session: Session, status: RefreshStatus | None
) -> list[RefreshOpportunityView]:
    lookups = _Lookups(session)
    rows = RefreshOpportunityService(session).list_opportunities(status)[:MAX_LIST_ROWS]
    return [_refresh_view(row, session, lookups) for row in rows]


def suggestion_view(row: StrategySuggestion, session: Session) -> StrategySuggestionView:
    users = {user.id: user.display_name for user in session.scalars(select(User))}
    return _suggestion_view(row, users)


def _suggestion_view(
    row: StrategySuggestion, users: dict[uuid.UUID, str]
) -> StrategySuggestionView:
    return StrategySuggestionView(
        id=row.id,
        kind=row.kind,
        title=row.title,
        rationale=row.rationale,
        basis=dict(row.basis),
        status=row.status,
        proposed_at=row.proposed_at,
        decided_at=row.decided_at,
        decided_by_display_name=users.get(row.decided_by_user_id)
        if row.decided_by_user_id
        else None,
        decision_reason=row.decision_reason,
    )


def list_suggestion_views(
    session: Session, status: SuggestionStatus | None
) -> list[StrategySuggestionView]:
    users = {user.id: user.display_name for user in session.scalars(select(User))}
    rows = StrategySuggestionService(session).list_suggestions(status)[:MAX_LIST_ROWS]
    return [_suggestion_view(row, users) for row in rows]


def load_content_detail(
    session: Session, work_item_id: uuid.UUID, *, now: datetime | None = None
) -> ContentPerformanceDetailView | None:
    moment = now if now is not None else datetime.now(UTC)
    performance = PerformanceService(session)
    content = performance.get_by_work_item(work_item_id)
    if content is None:
        return None
    lookups = _Lookups(session)
    refresh = RefreshOpportunityService(session)
    open_refresh = refresh.open_for(content.id)
    assessments = performance.latest_assessments(content.id)
    gsc = performance.snapshots_for(content.id, PerformanceProvider.GOOGLE_SEARCH_CONSOLE)
    history = [
        row for row in refresh.list_opportunities() if row.published_content_id == content.id
    ]
    return ContentPerformanceDetailView(
        content=_content_row(
            content,
            assessments.get(28),
            lookups,
            now=moment,
            has_open_refresh=open_refresh is not None,
        ),
        assessments=[
            _assessment_view(assessments[w]) for w in ASSESSMENT_WINDOWS if w in assessments
        ],
        search_console_daily=_series(gsc, daily=True),
        search_console_summary=_series(gsc, daily=False),
        top_queries=top_queries(gsc),
        analytics=_series(
            performance.snapshots_for(content.id, PerformanceProvider.GOOGLE_ANALYTICS), daily=None
        ),
        google_trends=_series(
            performance.snapshots_for(content.id, PerformanceProvider.GOOGLE_TRENDS), daily=None
        ),
        pinterest_trends=_series(
            performance.snapshots_for(content.id, PerformanceProvider.PINTEREST_TRENDS), daily=None
        ),
        semrush=_series(
            performance.snapshots_for(content.id, PerformanceProvider.SEMRUSH), daily=None
        ),
        refresh=_refresh_view(open_refresh, session, lookups) if open_refresh is not None else None,
        refresh_history=[_refresh_view(row, session, lookups) for row in history],
        historical_signal=historical_signal_for(
            session,
            cluster_id=content.topic_cluster_id,
            audience_id=content.audience_id,
            theme_key=content.theme_key,
            content_format=content.content_format,
        ).projection(),
    )
