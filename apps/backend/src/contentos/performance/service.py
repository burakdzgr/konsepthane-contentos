"""Transport-neutral performance-loop persistence and aggregation.

Writes here are the only path to the performance tables: the worker hook,
the backfill, the provider sync tasks and the classifier runs all go
through `PerformanceService`. Nothing here publishes, transitions a work
item, or talks to a provider.
"""

import hashlib
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from contentos.ideas.service import IdeaService
from contentos.opportunities.models import EditorialOpportunity
from contentos.performance.classifier import (
    Assessment,
    PerformanceClassifier,
    PerformancePolicy,
)
from contentos.performance.enums import (
    ASSESSMENT_WINDOWS,
    AssessmentStatus,
    PerformanceProvider,
)
from contentos.performance.models import (
    ContentPerformanceSnapshot,
    PerformanceAssessment,
    PublishedContent,
)
from contentos.publishing.models import PublicationAttempt, PublicationPackage
from contentos.strategy.models import TopicCluster
from contentos.strategy.service import StrategyService, normalize_phrase
from contentos.workflow.enums import WorkflowState
from contentos.workflow.models import EditorialWorkflowEvent, EditorialWorkItem

_logger = structlog.get_logger("contentos.performance")

MAX_TOP_QUERIES = 20
MAX_CANONICAL_URL_LENGTH = 1000
MAX_THEME_KEY_LENGTH = 200


class PerformanceError(Exception):
    """Base class for performance-loop domain errors."""


class PublishedContentNotFoundError(PerformanceError):
    """No published content row for the given identifier."""


class InvalidPerformanceInputError(PerformanceError):
    """A caller supplied an out-of-vocabulary or malformed value."""


def canonical_url_from_ref(remote_publication_ref: str | None) -> str | None:
    """The publication address ONLY when the remote reference is one.

    A bare Konsepthane reference (``konsepthane-pub-42``) is not a URL and
    is never turned into one by guessing a host or a path.
    """
    if remote_publication_ref is None:
        return None
    candidate = remote_publication_ref.strip()
    if not candidate.lower().startswith(("http://", "https://")):
        return None
    if len(candidate) > MAX_CANONICAL_URL_LENGTH or any(char.isspace() for char in candidate):
        return None
    return candidate


def snapshot_hash(
    published_content_id: uuid.UUID,
    provider: PerformanceProvider,
    period_start: date,
    period_end: date,
    observed_at: datetime,
) -> str:
    """Idempotency identity: one observation per content/provider/period/day."""
    material = "|".join(
        (
            str(published_content_id),
            provider.value,
            period_start.isoformat(),
            period_end.isoformat(),
            observed_at.astimezone(UTC).date().isoformat(),
        )
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class StrategyDerivation:
    topic_cluster_id: uuid.UUID | None
    audience_id: uuid.UUID | None
    theme_key: str | None
    content_format: str | None


@dataclass(frozen=True, slots=True)
class ClusterOverview:
    """Per-cluster counts for one window; ``sufficient`` is False when no
    publication in the cluster has real metrics yet."""

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

    @property
    def sufficient(self) -> bool:
        return (self.rising + self.stable + self.declining + self.volatile) > 0


class PerformanceService:
    def __init__(
        self, session: Session, *, classifier: PerformanceClassifier | None = None
    ) -> None:
        self._session = session
        self._classifier = classifier if classifier is not None else PerformanceClassifier()

    # --- published contents ------------------------------------------------

    def list_published(self) -> list[PublishedContent]:
        return list(
            self._session.scalars(
                select(PublishedContent).order_by(
                    PublishedContent.published_at.desc(), PublishedContent.id
                )
            )
        )

    def get(self, published_content_id: uuid.UUID) -> PublishedContent | None:
        return self._session.get(PublishedContent, published_content_id)

    def get_by_work_item(self, work_item_id: uuid.UUID) -> PublishedContent | None:
        return self._session.scalar(
            select(PublishedContent).where(PublishedContent.work_item_id == work_item_id)
        )

    def record_published(
        self,
        *,
        work_item_id: uuid.UUID,
        publication_package_id: uuid.UUID,
        publication_attempt_id: uuid.UUID | None,
        remote_publication_ref: str,
        published_at: datetime,
        opportunity_id: uuid.UUID | None = None,
    ) -> PublishedContent:
        """Start measurement for a work item (idempotent per work item)."""
        existing = self.get_by_work_item(work_item_id)
        if existing is not None:
            return existing
        cleaned_ref = remote_publication_ref.strip()
        if not cleaned_ref:
            raise InvalidPerformanceInputError("remote_publication_ref must not be empty")
        work_item = self._session.get(EditorialWorkItem, work_item_id)
        if work_item is None:
            raise InvalidPerformanceInputError("no such editorial work item")
        if opportunity_id is None:
            opportunity_id = self._session.scalar(
                select(EditorialOpportunity.id).where(
                    EditorialOpportunity.work_item_id == work_item_id
                )
            )
        derived = self.derive_strategy(work_item, opportunity_id)
        row = PublishedContent(
            work_item_id=work_item_id,
            opportunity_id=opportunity_id,
            publication_package_id=publication_package_id,
            publication_attempt_id=publication_attempt_id,
            canonical_url=canonical_url_from_ref(cleaned_ref),
            remote_publication_ref=cleaned_ref,
            published_at=published_at,
            topic_cluster_id=derived.topic_cluster_id,
            audience_id=derived.audience_id,
            theme_key=derived.theme_key,
            content_format=derived.content_format,
        )
        self._session.add(row)
        self._session.flush()
        return row

    def derive_strategy(
        self, work_item: EditorialWorkItem, opportunity_id: uuid.UUID | None
    ) -> StrategyDerivation:
        """Bounded strategy context from durable facts; absent stays None."""
        theme_key: str | None = None
        content_format: str | None = None
        text_parts = [work_item.title_working_label]
        if opportunity_id is not None:
            idea = IdeaService(self._session).get_effective_selection(opportunity_id)
            if idea is not None:
                content_format = idea.content_type.value
                text_parts.extend((idea.working_title, idea.audience))
                theme = idea.planning_dimensions.get("theme")
                if isinstance(theme, str) and theme.strip():
                    theme_key = normalize_phrase(theme)[:MAX_THEME_KEY_LENGTH] or None
                    text_parts.append(theme)
        context = StrategyService(self._session).context_for_text(
            " ".join(text_parts), locale=work_item.locale, market=work_item.market
        )
        return StrategyDerivation(
            topic_cluster_id=context.clusters[0].id if context.clusters else None,
            audience_id=context.audiences[0].id if context.audiences else None,
            theme_key=theme_key,
            content_format=content_format,
        )

    @classmethod
    def backfill_published(cls, session: Session) -> int:
        """Register every successful publication that has no measurement row."""
        service = cls(session)
        rows = session.execute(
            select(PublicationAttempt, PublicationPackage)
            .join(
                PublicationPackage,
                PublicationPackage.id == PublicationAttempt.publication_package_id,
            )
            .where(PublicationAttempt.status == "succeeded")
            .order_by(PublicationAttempt.created_at)
        ).all()
        created = 0
        for attempt, package in rows:
            if service.get_by_work_item(package.work_item_id) is not None:
                continue
            if attempt.remote_publication_ref is None:
                continue
            published_event = session.scalar(
                select(EditorialWorkflowEvent)
                .where(
                    EditorialWorkflowEvent.work_item_id == package.work_item_id,
                    EditorialWorkflowEvent.to_state == WorkflowState.PUBLISHED,
                )
                .order_by(EditorialWorkflowEvent.id.desc())
                .limit(1)
            )
            published_at = (
                published_event.occurred_at if published_event is not None else attempt.created_at
            )
            service.record_published(
                work_item_id=package.work_item_id,
                publication_package_id=package.id,
                publication_attempt_id=attempt.id,
                remote_publication_ref=attempt.remote_publication_ref,
                published_at=published_at,
            )
            created += 1
        return created

    # --- snapshots -----------------------------------------------------------

    def record_snapshot(
        self,
        published_content_id: uuid.UUID,
        provider: PerformanceProvider,
        *,
        period_start: date,
        period_end: date,
        metrics: Mapping[str, Any],
        observed_at: datetime,
    ) -> tuple[ContentPerformanceSnapshot, bool]:
        """Append one observation; an identical identity converges (no update)."""
        if not isinstance(provider, PerformanceProvider):
            raise InvalidPerformanceInputError("provider must be a PerformanceProvider value")
        if period_start > period_end:
            raise InvalidPerformanceInputError("period_start must not be after period_end")
        digest = snapshot_hash(
            published_content_id, provider, period_start, period_end, observed_at
        )
        existing = self._session.scalar(
            select(ContentPerformanceSnapshot).where(
                ContentPerformanceSnapshot.snapshot_hash == digest
            )
        )
        if existing is not None:
            return existing, False
        row = ContentPerformanceSnapshot(
            published_content_id=published_content_id,
            provider=provider,
            period_start=period_start,
            period_end=period_end,
            observed_at=observed_at,
            metrics=_bounded_metrics(metrics),
            snapshot_hash=digest,
        )
        self._session.add(row)
        self._session.flush()
        return row, True

    def snapshots_for(
        self, published_content_id: uuid.UUID, provider: PerformanceProvider | None = None
    ) -> list[ContentPerformanceSnapshot]:
        statement = select(ContentPerformanceSnapshot).where(
            ContentPerformanceSnapshot.published_content_id == published_content_id
        )
        if provider is not None:
            statement = statement.where(ContentPerformanceSnapshot.provider == provider)
        statement = statement.order_by(
            ContentPerformanceSnapshot.period_end,
            ContentPerformanceSnapshot.period_start,
            ContentPerformanceSnapshot.observed_at,
        )
        return list(self._session.scalars(statement))

    def latest_summary_snapshots(
        self, published_content_id: uuid.UUID, provider: PerformanceProvider, limit: int = 2
    ) -> list[ContentPerformanceSnapshot]:
        """Multi-day (summary) snapshots, newest first."""
        rows = [
            row
            for row in self.snapshots_for(published_content_id, provider)
            if row.period_start != row.period_end
        ]
        rows.sort(key=lambda row: (row.period_end, row.observed_at), reverse=True)
        return rows[:limit]

    def freshness(self) -> dict[str, datetime | None]:
        """Latest observation per provider; None means never observed."""
        result: dict[str, datetime | None] = {
            provider.value: None for provider in PerformanceProvider
        }
        for row in self._session.execute(
            select(
                ContentPerformanceSnapshot.provider,
                ContentPerformanceSnapshot.observed_at,
            )
        ):
            provider_value = (
                row[0].value if isinstance(row[0], PerformanceProvider) else str(row[0])
            )
            observed = row[1] if row[1].tzinfo is not None else row[1].replace(tzinfo=UTC)
            current = result.get(provider_value)
            if current is None or observed > current:
                result[provider_value] = observed
        return result

    # --- assessments -----------------------------------------------------------

    def assess_content(
        self, content: PublishedContent, *, now: datetime, policy: PerformancePolicy
    ) -> list[PerformanceAssessment]:
        """Classify every window; append a row only when the verdict or its
        basis changed (append-only table, no churn on identical days)."""
        snapshots = self.snapshots_for(content.id, PerformanceProvider.GOOGLE_SEARCH_CONSOLE)
        written: list[PerformanceAssessment] = []
        for window_days in ASSESSMENT_WINDOWS:
            assessment = self._classifier.assess(snapshots, window_days, now, policy)
            latest = self.latest_assessment(content.id, window_days)
            if (
                latest is not None
                and latest.status is assessment.status
                and latest.basis == assessment.basis
            ):
                continue
            written.append(self._append_assessment(content.id, assessment, now))
        return written

    def assess_all(
        self, *, now: datetime, policy: PerformancePolicy
    ) -> list[PerformanceAssessment]:
        written: list[PerformanceAssessment] = []
        for content in self.list_published():
            written.extend(self.assess_content(content, now=now, policy=policy))
        return written

    def _append_assessment(
        self, published_content_id: uuid.UUID, assessment: Assessment, now: datetime
    ) -> PerformanceAssessment:
        row = PerformanceAssessment(
            published_content_id=published_content_id,
            window_days=assessment.window_days,
            status=assessment.status,
            basis=dict(assessment.basis),
            assessed_at=now,
            engine_name=assessment.engine_name,
            engine_version=assessment.engine_version,
        )
        self._session.add(row)
        self._session.flush()
        return row

    def latest_assessment(
        self, published_content_id: uuid.UUID, window_days: int
    ) -> PerformanceAssessment | None:
        return self._session.scalar(
            select(PerformanceAssessment)
            .where(
                PerformanceAssessment.published_content_id == published_content_id,
                PerformanceAssessment.window_days == window_days,
            )
            .order_by(PerformanceAssessment.assessed_at.desc(), PerformanceAssessment.id.desc())
            .limit(1)
        )

    def latest_assessments(
        self, published_content_id: uuid.UUID
    ) -> dict[int, PerformanceAssessment]:
        result: dict[int, PerformanceAssessment] = {}
        for window_days in ASSESSMENT_WINDOWS:
            latest = self.latest_assessment(published_content_id, window_days)
            if latest is not None:
                result[window_days] = latest
        return result

    def latest_assessments_for_all(
        self, window_days: int
    ) -> dict[uuid.UUID, PerformanceAssessment]:
        """One query for the newest assessment per content for one window."""
        rows = self._session.scalars(
            select(PerformanceAssessment)
            .where(PerformanceAssessment.window_days == window_days)
            .order_by(PerformanceAssessment.assessed_at.desc(), PerformanceAssessment.id.desc())
        )
        latest: dict[uuid.UUID, PerformanceAssessment] = {}
        for row in rows:
            latest.setdefault(row.published_content_id, row)
        return latest

    # --- aggregates --------------------------------------------------------------

    def cluster_overview(
        self, window_days: int, *, now: datetime | None = None
    ) -> list[ClusterOverview]:
        moment = now if now is not None else datetime.now(UTC)
        latest = self.latest_assessments_for_all(window_days)
        clusters = {row.id: row.name for row in self._session.scalars(select(TopicCluster))}
        buckets: dict[uuid.UUID | None, dict[str, int]] = {}
        for content in self.list_published():
            bucket = buckets.setdefault(
                content.topic_cluster_id,
                {
                    key: 0
                    for key in (
                        "published",
                        "rising",
                        "stable",
                        "declining",
                        "volatile",
                        "new",
                        "insufficient",
                        "unknown",
                    )
                },
            )
            bucket["published"] += 1
            if moment - content.published_at <= timedelta(days=window_days):
                bucket["new"] += 1
            assessment = latest.get(content.id)
            status = assessment.status if assessment is not None else AssessmentStatus.UNKNOWN
            key = "insufficient" if status is AssessmentStatus.INSUFFICIENT_DATA else status.value
            bucket[key] += 1
        overview = [
            ClusterOverview(
                cluster_id=cluster_id,
                cluster_name=clusters.get(cluster_id, "Küme atanmadı")
                if cluster_id
                else "Küme atanmadı",
                **counts,
            )
            for cluster_id, counts in buckets.items()
        ]
        overview.sort(key=lambda row: (row.cluster_id is None, -row.published, row.cluster_name))
        return overview


def record_publication_fail_safe(
    session: Session,
    *,
    work_item_id: uuid.UUID,
    publication_package_id: uuid.UUID,
    publication_attempt_id: uuid.UUID | None,
    remote_publication_ref: str | None,
    published_at: datetime | None = None,
) -> None:
    """Worker hook: start measurement after a successful publication.

    Deliberately tiny and fail-safe — publication already succeeded and
    its history is durable; a measurement bookkeeping failure is logged
    and rolled back, never raised into the publish task.
    """
    if remote_publication_ref is None:
        return
    try:
        PerformanceService(session).record_published(
            work_item_id=work_item_id,
            publication_package_id=publication_package_id,
            publication_attempt_id=publication_attempt_id,
            remote_publication_ref=remote_publication_ref,
            published_at=published_at if published_at is not None else datetime.now(UTC),
        )
        session.commit()
    except Exception as error:  # noqa: BLE001 - bookkeeping must never fail the publish
        session.rollback()
        _logger.warning(
            "published_content_record_failed",
            work_item_id=str(work_item_id),
            error_type=type(error).__name__,
        )


def _bounded_metrics(metrics: Mapping[str, Any]) -> dict[str, Any]:
    """Keep the metrics JSON bounded: top query lists are capped."""
    result = dict(metrics)
    queries = result.get("top_queries")
    if isinstance(queries, list):
        result["top_queries"] = [entry for entry in queries if isinstance(entry, dict)][
            :MAX_TOP_QUERIES
        ]
    return result


def top_queries(snapshots: Iterable[ContentPerformanceSnapshot]) -> list[dict[str, Any]]:
    """The top query list of the newest summary snapshot (bounded)."""
    newest: ContentPerformanceSnapshot | None = None
    for snapshot in snapshots:
        queries = snapshot.metrics.get("top_queries")
        if not isinstance(queries, list) or not queries:
            continue
        if newest is None or (snapshot.period_end, snapshot.observed_at) > (
            newest.period_end,
            newest.observed_at,
        ):
            newest = snapshot
    if newest is None:
        return []
    return [entry for entry in newest.metrics["top_queries"] if isinstance(entry, dict)][
        :MAX_TOP_QUERIES
    ]
