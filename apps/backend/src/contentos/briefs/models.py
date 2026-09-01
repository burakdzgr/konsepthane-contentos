"""ContentBrief persistence models (the writing CONTRACT, never the article)."""

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
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

# Registered so every FK target resolves wherever these models are used
# (acyclic: none of these import contentos.briefs).
from contentos.ai import models as _ai_models  # noqa: F401
from contentos.briefs.enums import BriefActorOrigin, BriefClaimKind, BriefStatus
from contentos.core.context import REQUEST_ID_MAX_LENGTH
from contentos.db.base import Base
from contentos.db.types import JSON_DICT, JSON_LIST, string_enum
from contentos.evidence_packs import models as _pack_models  # noqa: F401
from contentos.ideas import models as _idea_models  # noqa: F401
from contentos.search_intent import models as _intent_models  # noqa: F401


class ContentBrief(Base):
    """One IMMUTABLE brief content version — the future Writer's whole contract.

    Pins EXACT upstream versions (Idea.id, EvidencePack.id,
    SearchIntentAnalysis.id — never logical/latest identities) so the brief
    stays reconstructable forever. After creation every content field is
    immutable; ONLY `status` may change through the guarded service surface
    (DB trigger enforces status-only, forward-only updates).

    No article body, prose, or final headline lives here.
    `ACCEPTED_FOR_DRAFTING` is an editorial decision, never publication
    approval (ADR 0004 untouched).
    """

    __tablename__ = "content_briefs"
    __table_args__ = (
        UniqueConstraint("work_item_id", "version", name="uq_content_briefs_version"),
        UniqueConstraint(
            "work_item_id",
            "idea_id",
            "evidence_pack_id",
            "search_intent_analysis_id",
            "engine_name",
            "engine_version",
            name="uq_content_briefs_identity",
        ),
        CheckConstraint("version > 0", name="ck_content_briefs_version_positive"),
        CheckConstraint("length(trim(locale)) > 0", name="ck_content_briefs_locale_nonempty"),
        CheckConstraint("length(trim(market)) = 2", name="ck_content_briefs_market_length"),
        CheckConstraint(
            "length(trim(target_audience)) > 0",
            name="ck_content_briefs_audience_nonempty",
        ),
        CheckConstraint(
            "length(trim(intent_summary)) > 0",
            name="ck_content_briefs_intent_summary_nonempty",
        ),
        CheckConstraint(
            "length(trim(original_angle)) > 0",
            name="ck_content_briefs_angle_nonempty",
        ),
        CheckConstraint(
            "length(trim(content_objective)) > 0",
            name="ck_content_briefs_objective_nonempty",
        ),
        CheckConstraint(
            "length(trim(engine_name)) > 0",
            name="ck_content_briefs_engine_name_nonempty",
        ),
        CheckConstraint(
            "length(trim(engine_version)) > 0",
            name="ck_content_briefs_engine_version_nonempty",
        ),
        CheckConstraint(
            "length(content_hash) = 64 AND content_hash = lower(content_hash)",
            name="ck_content_briefs_hash_format",
        ),
        Index("ix_content_briefs_work_item", "work_item_id", "version"),
        Index("ix_content_briefs_idea", "idea_id"),
        Index("ix_content_briefs_pack", "evidence_pack_id"),
        Index("ix_content_briefs_intent", "search_intent_analysis_id"),
        Index("ix_content_briefs_composition_attempt", "composition_attempt_id"),
        # At most one non-superseded (active) brief per work item.
        Index(
            "uq_content_briefs_active",
            "work_item_id",
            unique=True,
            postgresql_where=text("status != 'superseded'"),
            sqlite_where=text("status != 'superseded'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    work_item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(),
        ForeignKey("editorial_work_items.id", ondelete="RESTRICT"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer(), nullable=False)
    idea_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("ideas.id", ondelete="RESTRICT"), nullable=False
    )
    evidence_pack_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("evidence_packs.id", ondelete="RESTRICT"), nullable=False
    )
    search_intent_analysis_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(),
        ForeignKey("search_intent_analyses.id", ondelete="RESTRICT"),
        nullable=False,
    )
    locale: Mapped[str] = mapped_column(String(20), nullable=False)
    market: Mapped[str] = mapped_column(String(2), nullable=False)
    target_audience: Mapped[str] = mapped_column(String(500), nullable=False)
    intent_summary: Mapped[str] = mapped_column(Text(), nullable=False)
    original_angle: Mapped[str] = mapped_column(Text(), nullable=False)
    title_guidance: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    content_objective: Mapped[str] = mapped_column(Text(), nullable=False)
    required_sections: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON_LIST, nullable=False, default=list
    )
    optional_sections: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON_LIST, nullable=False, default=list
    )
    practical_requirements: Mapped[dict[str, Any]] = mapped_column(
        JSON_DICT, nullable=False, default=dict
    )
    exclusions: Mapped[list[str]] = mapped_column(JSON_LIST, nullable=False, default=list)
    uncertainty_notes: Mapped[list[str]] = mapped_column(JSON_LIST, nullable=False, default=list)
    internal_link_needs: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON_LIST, nullable=False, default=list
    )
    media_needs: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON_LIST, nullable=False, default=list
    )
    faq_questions: Mapped[list[str]] = mapped_column(JSON_LIST, nullable=False, default=list)
    acceptance_criteria: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON_LIST, nullable=False, default=list
    )
    structure_guard_result: Mapped[dict[str, Any]] = mapped_column(
        JSON_DICT, nullable=False, default=dict
    )
    structure_policy_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON_DICT, nullable=False, default=dict
    )
    status: Mapped[BriefStatus] = mapped_column(
        string_enum(BriefStatus, "ck_content_briefs_status", 24),
        nullable=False,
        default=BriefStatus.DRAFT,
    )
    composition_attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(),
        ForeignKey("ai_generation_attempts.id", ondelete="RESTRICT"),
        nullable=True,
    )
    engine_name: Mapped[str] = mapped_column(String(100), nullable=False)
    engine_version: Mapped[str] = mapped_column(String(50), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BriefClaim(Base):
    """One claim contract inside one brief version (append-only)."""

    __tablename__ = "brief_claims"
    __table_args__ = (
        UniqueConstraint("brief_id", "claim_key", name="uq_brief_claims_key"),
        CheckConstraint("length(trim(claim_key)) > 0", name="ck_brief_claims_key_nonempty"),
        CheckConstraint("length(trim(claim_text)) > 0", name="ck_brief_claims_text_nonempty"),
        Index("ix_brief_claims_brief", "brief_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    brief_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("content_briefs.id", ondelete="RESTRICT"), nullable=False
    )
    claim_key: Mapped[str] = mapped_column(String(100), nullable=False)
    claim_text: Mapped[str] = mapped_column(Text(), nullable=False)
    claim_kind: Mapped[BriefClaimKind] = mapped_column(
        string_enum(BriefClaimKind, "ck_brief_claims_kind", 24), nullable=False
    )
    handling: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BriefClaimEvidence(Base):
    """One exact claim -> ResearchEvidence link (append-only, no text copies)."""

    __tablename__ = "brief_claim_evidence"
    __table_args__ = (
        UniqueConstraint("claim_id", "research_evidence_id", name="uq_brief_claim_evidence_link"),
        Index("ix_brief_claim_evidence_claim", "claim_id"),
        Index("ix_brief_claim_evidence_evidence", "research_evidence_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    claim_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("brief_claims.id", ondelete="RESTRICT"), nullable=False
    )
    research_evidence_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("research_evidence.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BriefStatusEvent(Base):
    """Append-only audit of one brief status mutation."""

    __tablename__ = "brief_status_events"
    __table_args__ = (
        CheckConstraint("length(trim(reason)) > 0", name="ck_brief_status_events_reason_nonempty"),
        CheckConstraint(
            "request_id IS NULL OR length(trim(request_id)) > 0",
            name="ck_brief_status_events_request_id_nonempty",
        ),
        Index("ix_brief_status_events_brief", "brief_id", "id"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"), primary_key=True, autoincrement=True
    )
    brief_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("content_briefs.id", ondelete="RESTRICT"), nullable=False
    )
    from_status: Mapped[BriefStatus] = mapped_column(
        string_enum(BriefStatus, "ck_brief_status_events_from", 24), nullable=False
    )
    to_status: Mapped[BriefStatus] = mapped_column(
        string_enum(BriefStatus, "ck_brief_status_events_to", 24), nullable=False
    )
    actor_origin: Mapped[BriefActorOrigin] = mapped_column(
        string_enum(BriefActorOrigin, "ck_brief_status_events_actor", 16), nullable=False
    )
    reason: Mapped[str] = mapped_column(Text(), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(REQUEST_ID_MAX_LENGTH), nullable=True)
    replacement_brief_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("content_briefs.id", ondelete="RESTRICT"), nullable=True
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
