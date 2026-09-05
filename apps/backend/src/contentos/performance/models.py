"""Performance-loop persistence models.

`published_contents` is the durable "measurement started" fact (one per
work item). `content_performance_snapshots` and `performance_assessments`
are append-only observation/classification facts. `refresh_opportunities`
and `strategy_suggestions` carry the human-gated decisions.
"""

import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

# Registered so every FK target resolves wherever these models are used
# (acyclic: none of these import contentos.performance).
from contentos.auth import models as _auth_models  # noqa: F401
from contentos.db.base import Base
from contentos.db.types import JSON_DICT, string_enum
from contentos.opportunities import models as _opportunity_models  # noqa: F401
from contentos.performance.enums import (
    AssessmentStatus,
    PerformanceProvider,
    RefreshStatus,
    SuggestionKind,
    SuggestionStatus,
)
from contentos.publishing import models as _publishing_models  # noqa: F401
from contentos.strategy import models as _strategy_models  # noqa: F401
from contentos.workflow import models as _workflow_models  # noqa: F401


def _utcnow() -> datetime:
    return datetime.now(UTC)


class PublishedContent(Base):
    """One published work item under measurement (unique per work item)."""

    __tablename__ = "published_contents"
    __table_args__ = (
        UniqueConstraint("work_item_id", name="uq_published_contents_work_item"),
        CheckConstraint(
            "length(trim(remote_publication_ref)) > 0",
            name="ck_published_contents_ref_nonempty",
        ),
        Index("ix_published_contents_published_at", "published_at"),
        Index("ix_published_contents_cluster", "topic_cluster_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    work_item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("editorial_work_items.id", ondelete="RESTRICT"), nullable=False
    )
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("editorial_opportunities.id", ondelete="RESTRICT"), nullable=True
    )
    publication_package_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("publication_packages.id", ondelete="RESTRICT"), nullable=False
    )
    publication_attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("publication_attempts.id", ondelete="RESTRICT"), nullable=True
    )
    # NULL until the publication address is actually known; never guessed.
    canonical_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    remote_publication_ref: Mapped[str] = mapped_column(Text(), nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    topic_cluster_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("topic_clusters.id", ondelete="RESTRICT"), nullable=True
    )
    audience_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("audience_strategies.id", ondelete="RESTRICT"), nullable=True
    )
    theme_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    content_format: Mapped[str | None] = mapped_column(String(60), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )


class ContentPerformanceSnapshot(Base):
    """One provider observation for one period (append-only, never updated)."""

    __tablename__ = "content_performance_snapshots"
    __table_args__ = (
        UniqueConstraint("snapshot_hash", name="uq_content_performance_snapshots_hash"),
        CheckConstraint(
            "length(snapshot_hash) = 64 AND snapshot_hash = lower(snapshot_hash)",
            name="ck_content_performance_snapshots_hash_format",
        ),
        CheckConstraint(
            "period_start <= period_end", name="ck_content_performance_snapshots_period"
        ),
        Index(
            "ix_content_performance_snapshots_content_provider_period",
            "published_content_id",
            "provider",
            "period_end",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    published_content_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("published_contents.id", ondelete="RESTRICT"), nullable=False
    )
    provider: Mapped[PerformanceProvider] = mapped_column(
        string_enum(PerformanceProvider, "ck_content_performance_snapshots_provider", 40),
        nullable=False,
    )
    period_start: Mapped[date] = mapped_column(Date(), nullable=False)
    period_end: Mapped[date] = mapped_column(Date(), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )


class PerformanceAssessment(Base):
    """One classification of one content over one window (append-only)."""

    __tablename__ = "performance_assessments"
    __table_args__ = (
        CheckConstraint("window_days IN (7, 28, 90)", name="ck_performance_assessments_window"),
        Index(
            "ix_performance_assessments_content_window",
            "published_content_id",
            "window_days",
            "assessed_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    published_content_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("published_contents.id", ondelete="RESTRICT"), nullable=False
    )
    window_days: Mapped[int] = mapped_column(Integer(), nullable=False)
    status: Mapped[AssessmentStatus] = mapped_column(
        string_enum(AssessmentStatus, "ck_performance_assessments_status", 24), nullable=False
    )
    basis: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    engine_name: Mapped[str] = mapped_column(String(100), nullable=False)
    engine_version: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )


class RefreshOpportunity(Base):
    """A proposed content refresh awaiting a NAMED human decision."""

    __tablename__ = "refresh_opportunities"
    __table_args__ = (
        CheckConstraint(
            "length(trim(recommendation)) > 0",
            name="ck_refresh_opportunities_recommendation_nonempty",
        ),
        CheckConstraint(
            "(status = 'proposed') OR (decided_at IS NOT NULL)",
            name="ck_refresh_opportunities_decided",
        ),
        Index("ix_refresh_opportunities_content_status", "published_content_id", "status"),
        Index("ix_refresh_opportunities_status", "status", "proposed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    published_content_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("published_contents.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[RefreshStatus] = mapped_column(
        string_enum(RefreshStatus, "ck_refresh_opportunities_status", 16),
        nullable=False,
        default=RefreshStatus.PROPOSED,
    )
    trigger_assessment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("performance_assessments.id", ondelete="RESTRICT"), nullable=False
    )
    diagnosis: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    recommendation: Mapped[str] = mapped_column(Text(), nullable=False)
    proposed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    decision_reason: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )


class StrategySuggestion(Base):
    """A bounded, evidence-backed strategy suggestion awaiting a decision."""

    __tablename__ = "strategy_suggestions"
    __table_args__ = (
        UniqueConstraint("suggestion_hash", name="uq_strategy_suggestions_hash"),
        CheckConstraint(
            "length(suggestion_hash) = 64 AND suggestion_hash = lower(suggestion_hash)",
            name="ck_strategy_suggestions_hash_format",
        ),
        CheckConstraint("length(trim(title)) > 0", name="ck_strategy_suggestions_title_nonempty"),
        CheckConstraint(
            "(status = 'proposed') OR (decided_at IS NOT NULL)",
            name="ck_strategy_suggestions_decided",
        ),
        Index("ix_strategy_suggestions_status", "status", "proposed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    kind: Mapped[SuggestionKind] = mapped_column(
        string_enum(SuggestionKind, "ck_strategy_suggestions_kind", 20), nullable=False
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    rationale: Mapped[str] = mapped_column(Text(), nullable=False)
    basis: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    status: Mapped[SuggestionStatus] = mapped_column(
        string_enum(SuggestionStatus, "ck_strategy_suggestions_status", 16),
        nullable=False,
        default=SuggestionStatus.PROPOSED,
    )
    proposed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    decision_reason: Mapped[str | None] = mapped_column(Text(), nullable=True)
    suggestion_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )
