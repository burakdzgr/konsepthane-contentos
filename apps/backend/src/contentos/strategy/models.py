"""Deliberately small operator-managed strategy models."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from contentos.db.base import Base
from contentos.db.types import string_enum
from contentos.strategy.enums import StrategyStatus


class AudienceStrategy(Base):
    __tablename__ = "audience_strategies"
    __table_args__ = (
        UniqueConstraint("name", "locale", "market", name="uq_audience_strategies_scope"),
        CheckConstraint(
            "priority >= 0 AND priority <= 100", name="ck_audience_strategies_priority"
        ),
        CheckConstraint("length(trim(name)) > 0", name="ck_audience_strategies_name_nonempty"),
        Index("ix_audience_strategies_status_priority", "status", "priority"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    locale: Mapped[str] = mapped_column(String(20), nullable=False, default="tr-TR")
    market: Mapped[str] = mapped_column(String(2), nullable=False, default="TR")
    priority: Mapped[int] = mapped_column(nullable=False, default=50)
    status: Mapped[StrategyStatus] = mapped_column(
        string_enum(StrategyStatus, "ck_audience_strategies_status", 16), nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class TopicCluster(Base):
    __tablename__ = "topic_clusters"
    __table_args__ = (
        UniqueConstraint("slug", "locale", "market", name="uq_topic_clusters_scope"),
        CheckConstraint("priority >= 0 AND priority <= 100", name="ck_topic_clusters_priority"),
        CheckConstraint("length(trim(name)) > 0", name="ck_topic_clusters_name_nonempty"),
        Index("ix_topic_clusters_status_priority", "status", "priority"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), nullable=False)
    locale: Mapped[str] = mapped_column(String(20), nullable=False, default="tr-TR")
    market: Mapped[str] = mapped_column(String(2), nullable=False, default="TR")
    priority: Mapped[int] = mapped_column(nullable=False, default=50)
    status: Mapped[StrategyStatus] = mapped_column(
        string_enum(StrategyStatus, "ck_topic_clusters_status", 16), nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class StrategicKeyword(Base):
    __tablename__ = "strategic_keywords"
    __table_args__ = (
        UniqueConstraint(
            "normalized_phrase", "locale", "market", name="uq_strategic_keywords_scope"
        ),
        CheckConstraint("priority >= 0 AND priority <= 100", name="ck_strategic_keywords_priority"),
        CheckConstraint("length(trim(phrase)) > 0", name="ck_strategic_keywords_phrase_nonempty"),
        Index("ix_strategic_keywords_status_priority", "status", "priority"),
        Index("ix_strategic_keywords_cluster", "topic_cluster_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    phrase: Mapped[str] = mapped_column(String(240), nullable=False)
    normalized_phrase: Mapped[str] = mapped_column(String(240), nullable=False)
    locale: Mapped[str] = mapped_column(String(20), nullable=False, default="tr-TR")
    market: Mapped[str] = mapped_column(String(2), nullable=False, default="TR")
    priority: Mapped[int] = mapped_column(nullable=False, default=50)
    status: Mapped[StrategyStatus] = mapped_column(
        string_enum(StrategyStatus, "ck_strategic_keywords_status", 16), nullable=False
    )
    topic_cluster_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("topic_clusters.id", ondelete="RESTRICT"), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
