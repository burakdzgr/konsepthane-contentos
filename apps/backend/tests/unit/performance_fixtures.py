"""Shared seeding for the performance-loop tests (not collected).

The published work item is driven through the REAL canonical workflow
route (WorkflowService structural transitions). The publication package /
attempt rows are the ONE documented SQLite-only knob here: their upstream
artifact ids (decision, draft, brief, QA report) are placeholders because
SQLite does not enforce foreign keys in the harness and the full editorial
chain is exercised by test_publishing.py already.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from editorial_harness import TEST_OPERATOR_USERNAME
from sqlalchemy import select
from sqlalchemy.orm import Session

from contentos.auth.models import User
from contentos.performance.enums import PerformanceProvider
from contentos.performance.models import PublishedContent
from contentos.performance.service import PerformanceService
from contentos.publishing.models import PublicationAttempt, PublicationPackage
from contentos.workflow.enums import WorkflowActorOrigin, WorkflowState, WorkItemOrigin
from contentos.workflow.service import WorkflowService

NOW = datetime(2026, 9, 5, 6, 0, tzinfo=UTC)
TODAY = NOW.date()

ROUTE_TO_PUBLISHED = (
    WorkflowState.EVIDENCE_BUILDING,
    WorkflowState.SEO_RESEARCH,
    WorkflowState.BRIEFING,
    WorkflowState.DRAFTING,
    WorkflowState.EDITING,
    WorkflowState.QA_REVIEW,
    WorkflowState.AWAITING_HUMAN_REVIEW,
    WorkflowState.APPROVED,
    WorkflowState.SCHEDULED,
    WorkflowState.PUBLISHING,
    WorkflowState.PUBLISHED,
)


@dataclass(frozen=True, slots=True)
class FakeSnapshot:
    """Classifier input shaped like a snapshot row."""

    period_start: date
    period_end: date
    metrics: dict[str, Any]
    provider: PerformanceProvider = PerformanceProvider.GOOGLE_SEARCH_CONSOLE
    observed_at: datetime = field(default=NOW)


def daily_series(
    end: date,
    days: int,
    *,
    impressions: int | list[int],
    clicks: int | list[int],
    position: float | list[float],
) -> list[FakeSnapshot]:
    """`days` daily GSC points ending at `end` (oldest first)."""
    result: list[FakeSnapshot] = []
    for offset in range(days):
        index = days - 1 - offset
        day = end - timedelta(days=index)
        result.append(
            FakeSnapshot(
                period_start=day,
                period_end=day,
                metrics={
                    "impressions": _pick(impressions, offset),
                    "clicks": _pick(clicks, offset),
                    "position": _pick(position, offset),
                },
            )
        )
    return result


def _pick(value: Any, index: int) -> Any:
    return value[index] if isinstance(value, list) else value


def operator(session: Session) -> User:
    return session.execute(select(User).where(User.username == TEST_OPERATOR_USERNAME)).scalar_one()


def seed_published(
    session: Session,
    *,
    title: str = "Balon temalı doğum günü planı",
    published_at: datetime = NOW - timedelta(days=60),
    remote_ref: str = "konsepthane-pub-1",
    cluster_id: uuid.UUID | None = None,
    audience_id: uuid.UUID | None = None,
    theme_key: str | None = None,
    content_format: str | None = None,
) -> PublishedContent:
    workflow = WorkflowService(session)
    item = workflow.create_work_item(
        origin=WorkItemOrigin.OPERATOR,
        title_working_label=title,
        reason="performans testi için oluşturuldu",
        actor_origin=WorkflowActorOrigin.OPERATOR,
    )
    for state in ROUTE_TO_PUBLISHED:
        workflow.transition(
            item.id,
            state,
            actor_origin=WorkflowActorOrigin.SYSTEM,
            reason=f"test route -> {state.value}",
        )
    user = operator(session)
    package = PublicationPackage(
        work_item_id=item.id,
        version=1,
        human_decision_id=uuid.uuid4(),
        content_draft_id=uuid.uuid4(),
        content_brief_id=uuid.uuid4(),
        qa_report_id=uuid.uuid4(),
        content_hash="a" * 64,
        payload={"title_proposal": title, "body": []},
        payload_schema_version="1",
        package_hash="b" * 64,
        media_manifest={},
        assembled_by_user_id=user.id,
    )
    session.add(package)
    session.flush()
    attempt = PublicationAttempt(
        publication_package_id=package.id,
        attempt_number=1,
        idempotency_key=f"contentos-pub-{package.id}",
        status="succeeded",
        remote_publication_ref=remote_ref,
        transport_name="fake",
    )
    session.add(attempt)
    session.flush()
    content = PerformanceService(session).record_published(
        work_item_id=item.id,
        publication_package_id=package.id,
        publication_attempt_id=attempt.id,
        remote_publication_ref=remote_ref,
        published_at=published_at,
    )
    if cluster_id is not None:
        content.topic_cluster_id = cluster_id
    if audience_id is not None:
        content.audience_id = audience_id
    if theme_key is not None:
        content.theme_key = theme_key
    if content_format is not None:
        content.content_format = content_format
    session.flush()
    return content


def write_daily(
    session: Session,
    content: PublishedContent,
    points: list[FakeSnapshot],
    *,
    observed_at: datetime = NOW,
) -> None:
    service = PerformanceService(session)
    for point in points:
        service.record_snapshot(
            content.id,
            point.provider,
            period_start=point.period_start,
            period_end=point.period_end,
            metrics=point.metrics,
            observed_at=observed_at,
        )


def write_summary(
    session: Session,
    content: PublishedContent,
    *,
    start: date,
    end: date,
    top_queries: list[dict[str, Any]],
    impressions: int = 500,
    clicks: int = 40,
    position: float = 6.0,
    observed_at: datetime = NOW,
) -> None:
    PerformanceService(session).record_snapshot(
        content.id,
        PerformanceProvider.GOOGLE_SEARCH_CONSOLE,
        period_start=start,
        period_end=end,
        metrics={
            "impressions": impressions,
            "clicks": clicks,
            "ctr": clicks / impressions,
            "position": position,
            "top_queries": top_queries,
        },
        observed_at=observed_at,
    )


def rising_points(end: date = TODAY, window: int = 28) -> list[FakeSnapshot]:
    """Previous window weak, current window strong, position improving."""
    return daily_series(
        end - timedelta(days=window),
        window,
        impressions=20,
        clicks=2,
        position=9.0,
    ) + daily_series(end, window, impressions=40, clicks=5, position=5.5)


def declining_points(end: date = TODAY, window: int = 28) -> list[FakeSnapshot]:
    """Position 3.2 -> 4.5 -> 7.1 -> 11.8, impressions -34%, clicks -29%."""
    half = window // 2
    previous = daily_series(
        end - timedelta(days=window),
        window,
        impressions=30,
        clicks=7,
        position=[3.2] * half + [4.5] * (window - half),
    )
    current = daily_series(
        end,
        window,
        impressions=[20] * (window - 1) + [18],
        clicks=5,
        position=[7.1] * half + [11.8] * (window - half),
    )
    return previous + current


def weak_new_points(end: date = TODAY, days: int = 4) -> list[FakeSnapshot]:
    return daily_series(end, days, impressions=6, clicks=0, position=25.0)
