"""Durable research missions: goal, plan, signals, idea candidates.

Signals are inspiration provenance ("where did this idea impulse come
from"), never ResearchEvidence: nothing here can back a factual claim. A
candidate that becomes an EditorialOpportunity keeps its row; the
opportunity points back at it (``mission_candidate_id``) so the production
chain knows the item is idea-led.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from contentos.db.base import Base
from contentos.db.types import JSON_DICT, JSON_LIST, string_enum
from contentos.missions.enums import (
    CandidateKind,
    CandidateRecommendation,
    FactualEvidenceConfidence,
    IdeaConfidence,
    MissionStage,
    MissionStatus,
    SurfaceKind,
)


class ResearchMission(Base):
    __tablename__ = "research_missions"
    __table_args__ = (
        CheckConstraint("length(trim(topic)) > 0", name="ck_research_missions_topic"),
        Index("ix_research_missions_status_created", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    topic: Mapped[str] = mapped_column(String(300), nullable=False)
    goal: Mapped[str] = mapped_column(Text(), nullable=False)
    audience: Mapped[str] = mapped_column(String(300), nullable=False)
    seed_keyword: Mapped[str | None] = mapped_column(String(240), nullable=True)
    topic_cluster_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("topic_clusters.id", ondelete="RESTRICT"), nullable=True
    )
    locale: Mapped[str] = mapped_column(String(20), nullable=False, default="tr-TR")
    market: Mapped[str] = mapped_column(String(2), nullable=False, default="TR")
    status: Mapped[MissionStatus] = mapped_column(
        string_enum(MissionStatus, "ck_research_missions_status", 24), nullable=False
    )
    stage: Mapped[MissionStage] = mapped_column(
        string_enum(MissionStage, "ck_research_missions_stage", 20), nullable=False
    )
    # Model-planned intent and queries (mission-plan/1 projection).
    plan: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, default=dict, nullable=False)
    query_plan: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON_LIST, default=list, nullable=False
    )
    # Expanded keywords with demand/trend annotations (UNKNOWN when no provider).
    keyword_plan: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON_LIST, default=list, nullable=False
    )
    surface_summary: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, default=dict, nullable=False)
    elimination_summary: Mapped[dict[str, Any]] = mapped_column(
        JSON_DICT, default=dict, nullable=False
    )
    result_summary: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, default=dict, nullable=False)
    # Operator-visible progress: [{stage, status, note, at}].
    progress_log: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON_LIST, default=list, nullable=False
    )
    failure_reason: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class MissionSignal(Base):
    __tablename__ = "mission_signals"
    __table_args__ = (Index("ix_mission_signals_mission_surface", "mission_id", "surface_kind"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    mission_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("research_missions.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("sources.id", ondelete="RESTRICT"), nullable=True
    )
    discovery_item_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("discovery_items.id", ondelete="RESTRICT"), nullable=True
    )
    normalized_document_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("normalized_documents.id", ondelete="RESTRICT"), nullable=True
    )
    surface_kind: Mapped[SurfaceKind] = mapped_column(
        string_enum(SurfaceKind, "ck_mission_signals_surface", 24), nullable=False
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    snippet: Mapped[str | None] = mapped_column(Text(), nullable=True)
    reference_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    query: Mapped[str | None] = mapped_column(String(300), nullable=True)
    signal_role: Mapped[str] = mapped_column(String(40), nullable=False)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class MissionIdeaCandidate(Base):
    __tablename__ = "mission_idea_candidates"
    __table_args__ = (
        CheckConstraint(
            "idea_quality >= 0 AND idea_quality <= 100", name="ck_mission_ideas_quality"
        ),
        Index("ix_mission_ideas_mission_quality", "mission_id", "idea_quality"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    mission_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("research_missions.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    angle: Mapped[str] = mapped_column(Text(), nullable=False)
    candidate_kind: Mapped[CandidateKind] = mapped_column(
        string_enum(CandidateKind, "ck_mission_ideas_kind", 16), nullable=False
    )
    cluster_key: Mapped[str] = mapped_column(String(240), nullable=False)
    # Idea primitives ("mechanics") this candidate combines: [{key, label}].
    primitives: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON_LIST, default=list, nullable=False
    )
    implementation_steps: Mapped[list[str]] = mapped_column(JSON_LIST, default=list, nullable=False)
    # Statements the Writer would need evidence for (kept OUT of the idea).
    factual_claims_needed: Mapped[list[str]] = mapped_column(
        JSON_LIST, default=list, nullable=False
    )
    signal_ids: Mapped[list[str]] = mapped_column(JSON_LIST, default=list, nullable=False)
    is_cliche: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=False)
    cliche_reason: Mapped[str | None] = mapped_column(Text(), nullable=True)
    idea_quality: Mapped[int] = mapped_column(Integer(), nullable=False)
    quality_factors: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, default=dict, nullable=False)
    idea_confidence: Mapped[IdeaConfidence] = mapped_column(
        string_enum(IdeaConfidence, "ck_mission_ideas_confidence", 16), nullable=False
    )
    factual_evidence_confidence: Mapped[FactualEvidenceConfidence] = mapped_column(
        string_enum(FactualEvidenceConfidence, "ck_mission_ideas_factual", 16),
        nullable=False,
        default=FactualEvidenceConfidence.UNKNOWN,
    )
    recommendation: Mapped[CandidateRecommendation] = mapped_column(
        string_enum(CandidateRecommendation, "ck_mission_ideas_recommendation", 24),
        nullable=False,
    )
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("mission_idea_candidates.id", ondelete="SET NULL"), nullable=True
    )
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(),
        ForeignKey(
            "editorial_opportunities.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_mission_idea_candidates_opportunity",
        ),
        nullable=True,
    )
    rationale: Mapped[str] = mapped_column(Text(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
