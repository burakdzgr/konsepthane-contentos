"""Idea persistence models (immutable versions + append-only selection)."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
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

from contentos.core.context import REQUEST_ID_MAX_LENGTH
from contentos.db.base import Base
from contentos.db.types import JSON_DICT, JSON_LIST, string_enum
from contentos.ideas.enums import (
    ContentType,
    IdeaOrigin,
    IdeaSelectionAction,
    IdeaSelectionActor,
    OriginalityStatus,
)


class Idea(Base):
    """One IMMUTABLE idea version.

    `id` is the exact version identity downstream artifacts pin;
    `logical_idea_id` is the stable candidate identity across revisions.
    A revision is always a new row (UNIQUE (logical_idea_id, version));
    nothing ever updates or deletes an existing version.

    `working_title` is a proposed editorial direction — never a published,
    SEO, or final title. An Idea is a proposed Konsepthane-specific concept:
    never factual evidence, never a provenance root (ADR 0007), never
    publication approval (ADR 0004).

    The `generation_attempt_id` FK from the accepted design is deliberately
    absent: ai_generation_attempts does not exist yet, and no placeholder is
    created. The AI-boundary task adds the real FK and widens `origin`.
    """

    __tablename__ = "ideas"
    __table_args__ = (
        UniqueConstraint("logical_idea_id", "version", name="uq_ideas_logical_version"),
        CheckConstraint("version > 0", name="ck_ideas_version_positive"),
        CheckConstraint("length(trim(working_title)) > 0", name="ck_ideas_working_title_nonempty"),
        CheckConstraint("length(trim(angle)) > 0", name="ck_ideas_angle_nonempty"),
        CheckConstraint("length(trim(audience)) > 0", name="ck_ideas_audience_nonempty"),
        CheckConstraint(
            "length(trim(value_proposition)) > 0",
            name="ck_ideas_value_proposition_nonempty",
        ),
        CheckConstraint("length(trim(rationale)) > 0", name="ck_ideas_rationale_nonempty"),
        CheckConstraint("length(trim(locale)) > 0", name="ck_ideas_locale_nonempty"),
        CheckConstraint("length(trim(market)) = 2", name="ck_ideas_market_length"),
        Index("ix_ideas_opportunity", "opportunity_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    logical_idea_id: Mapped[uuid.UUID] = mapped_column(Uuid(), nullable=False)
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(),
        ForeignKey("editorial_opportunities.id", ondelete="RESTRICT"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer(), nullable=False)
    working_title: Mapped[str] = mapped_column(String(200), nullable=False)
    angle: Mapped[str] = mapped_column(Text(), nullable=False)
    audience: Mapped[str] = mapped_column(String(500), nullable=False)
    value_proposition: Mapped[str] = mapped_column(Text(), nullable=False)
    content_type: Mapped[ContentType] = mapped_column(
        string_enum(ContentType, "ck_ideas_content_type", 16), nullable=False
    )
    locale: Mapped[str] = mapped_column(String(20), nullable=False)
    market: Mapped[str] = mapped_column(String(2), nullable=False)
    rationale: Mapped[str] = mapped_column(Text(), nullable=False)
    exclusions: Mapped[list[str]] = mapped_column(JSON_LIST, nullable=False, default=list)
    planning_dimensions: Mapped[dict[str, Any]] = mapped_column(
        JSON_DICT, nullable=False, default=dict
    )
    originality_status: Mapped[OriginalityStatus] = mapped_column(
        string_enum(OriginalityStatus, "ck_ideas_originality_status", 16),
        nullable=False,
    )
    originality_detail: Mapped[dict[str, Any]] = mapped_column(
        JSON_DICT, nullable=False, default=dict
    )
    originality_policy_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON_DICT, nullable=False, default=dict
    )
    origin: Mapped[IdeaOrigin] = mapped_column(
        string_enum(IdeaOrigin, "ck_ideas_origin", 16), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class IdeaSelectionEvent(Base):
    """Append-only record of one explicit operator selection action.

    `idea_id` pins the EXACT idea version: revising a logical idea never
    silently retargets an existing selection. Selection is distinct from any
    later human publication approval.
    """

    __tablename__ = "idea_selection_events"
    __table_args__ = (
        CheckConstraint(
            "length(trim(reason)) > 0", name="ck_idea_selection_events_reason_nonempty"
        ),
        CheckConstraint(
            "request_id IS NULL OR length(trim(request_id)) > 0",
            name="ck_idea_selection_events_request_id_nonempty",
        ),
        Index("ix_idea_selection_events_opportunity", "opportunity_id", "id"),
    )

    # Monotonic identity so append order is the audit order (the established
    # workflow-event pattern).
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"), primary_key=True, autoincrement=True
    )
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(),
        ForeignKey("editorial_opportunities.id", ondelete="RESTRICT"),
        nullable=False,
    )
    idea_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("ideas.id", ondelete="RESTRICT"), nullable=False
    )
    action: Mapped[IdeaSelectionAction] = mapped_column(
        string_enum(IdeaSelectionAction, "ck_idea_selection_events_action", 16),
        nullable=False,
    )
    actor_origin: Mapped[IdeaSelectionActor] = mapped_column(
        string_enum(IdeaSelectionActor, "ck_idea_selection_events_actor", 16),
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(Text(), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(REQUEST_ID_MAX_LENGTH), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
