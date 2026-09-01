"""Evidence-pack persistence models (references, never content)."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
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

# Registered so the ideas / ai_generation_attempts FK targets always
# resolve wherever the pack models are used (both imports are acyclic:
# neither module imports evidence_packs).
from contentos.ai import models as _ai_models  # noqa: F401
from contentos.db.base import Base
from contentos.db.types import JSON_DICT, JSON_LIST, string_enum
from contentos.evidence_packs.enums import (
    ContradictionResolutionStatus,
    ContradictionResolver,
    ContradictionSeverity,
    EvidenceItemRole,
    EvidencePackSufficiency,
)
from contentos.ideas import models as _idea_models  # noqa: F401


def _utc_now() -> datetime:
    return datetime.now(UTC)


class EvidencePack(Base):
    """One immutable versioned assembly of ResearchEvidence references.

    Reproducibility contract: the stored `sufficiency` + `sufficiency_detail`
    ARE the authoritative gate meaning of this exact pack version, forever.
    Nothing recomputes it later — resolving a contradiction never changes an
    existing version's meaning; an explicit reassembly produces a NEW version
    with its own immutable sufficiency.

    `assembly_input_hash` covers the WHOLE semantic assembly identity:
    selections (evidence, role, cluster), assembler identity, the exact
    policy snapshot, canonical contradiction state, and the pinned idea
    version (nullable). Display notes and handling recommendations are
    formally cosmetic/advisory and excluded.

    `idea_id` optionally pins the EXACT idea version a pack was (re)built
    for; packs may exist before/without any idea, so it stays nullable
    forever. `organization_attempt_id` is staged schema support for the
    accepted AI organization link: the deterministic assembly service
    always writes NULL today (no AI organization engine exists), and a
    future dedicated engine will introduce the semantic integration and
    bump the assembly snapshot schema at that time — a deterministic pack
    is never claimed as AI-organized.
    """

    __tablename__ = "evidence_packs"
    __table_args__ = (
        UniqueConstraint("opportunity_id", "version", name="uq_evidence_packs_version"),
        UniqueConstraint(
            "opportunity_id",
            "assembler_name",
            "assembler_version",
            "assembly_input_hash",
            name="uq_evidence_packs_identity",
        ),
        CheckConstraint("version > 0", name="ck_evidence_packs_version_positive"),
        CheckConstraint(
            "length(trim(assembler_name)) > 0",
            name="ck_evidence_packs_assembler_name_nonempty",
        ),
        CheckConstraint(
            "length(trim(assembler_version)) > 0",
            name="ck_evidence_packs_assembler_version_nonempty",
        ),
        CheckConstraint(
            "length(assembly_input_hash) = 64 AND assembly_input_hash = lower(assembly_input_hash)",
            name="ck_evidence_packs_hash_format",
        ),
        Index("ix_evidence_packs_opportunity", "opportunity_id", "version"),
        Index("ix_evidence_packs_idea", "idea_id"),
        Index("ix_evidence_packs_organization_attempt", "organization_attempt_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(),
        ForeignKey("editorial_opportunities.id", ondelete="RESTRICT"),
        nullable=False,
    )
    idea_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(),
        ForeignKey("ideas.id", ondelete="RESTRICT"),
        nullable=True,
    )
    organization_attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(),
        ForeignKey("ai_generation_attempts.id", ondelete="RESTRICT"),
        nullable=True,
    )
    version: Mapped[int] = mapped_column(Integer(), nullable=False)
    assembler_name: Mapped[str] = mapped_column(String(100), nullable=False)
    assembler_version: Mapped[str] = mapped_column(String(100), nullable=False)
    sufficiency: Mapped[EvidencePackSufficiency] = mapped_column(
        string_enum(EvidencePackSufficiency, "ck_evidence_packs_sufficiency", 16),
        nullable=False,
    )
    sufficiency_detail: Mapped[dict[str, Any]] = mapped_column(
        JSON_DICT, nullable=False, default=dict
    )
    source_diversity: Mapped[dict[str, Any]] = mapped_column(
        JSON_DICT, nullable=False, default=dict
    )
    staleness_notes: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON_LIST, nullable=False, default=list
    )
    locale_limitations: Mapped[dict[str, Any]] = mapped_column(
        JSON_DICT, nullable=False, default=dict
    )
    licensing_cautions: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON_LIST, nullable=False, default=list
    )
    policy_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    assembly_input_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON_DICT, nullable=False, default=dict
    )
    assembly_input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class EvidencePackItem(Base):
    """One referenced ResearchEvidence unit inside one pack.

    `display_note` is bounded optional synthesis text and never a substitute:
    the mandatory `research_evidence_id` on the same row is the provenance.
    There is no evidence_text field, by design.
    """

    __tablename__ = "evidence_pack_items"
    __table_args__ = (
        UniqueConstraint("pack_id", "research_evidence_id", name="uq_evidence_pack_items_evidence"),
        CheckConstraint(
            "length(trim(claim_cluster)) > 0",
            name="ck_evidence_pack_items_cluster_nonempty",
        ),
        Index("ix_evidence_pack_items_pack", "pack_id"),
        Index("ix_evidence_pack_items_evidence", "research_evidence_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    pack_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("evidence_packs.id", ondelete="RESTRICT"), nullable=False
    )
    research_evidence_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("research_evidence.id", ondelete="RESTRICT"), nullable=False
    )
    role: Mapped[EvidenceItemRole] = mapped_column(
        string_enum(EvidenceItemRole, "ck_evidence_pack_items_role", 16),
        nullable=False,
    )
    claim_cluster: Mapped[str] = mapped_column(String(100), nullable=False)
    display_note: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class EvidenceContradiction(Base):
    """One recorded disagreement between evidence sets inside a pack.

    Core fields are immutable; ONLY the resolution dimension may change,
    through the service, with a mandatory audited reason (enforced at
    PostgreSQL level by a guarded trigger).
    """

    __tablename__ = "evidence_contradictions"
    __table_args__ = (
        CheckConstraint(
            "length(trim(claim_key)) > 0",
            name="ck_evidence_contradictions_claim_key_nonempty",
        ),
        CheckConstraint(
            "length(trim(nature)) > 0",
            name="ck_evidence_contradictions_nature_nonempty",
        ),
        CheckConstraint(
            "(resolution_status = 'unresolved' AND resolved_at IS NULL "
            "AND resolved_by IS NULL AND resolution_reason IS NULL) OR "
            "(resolution_status != 'unresolved' AND resolved_at IS NOT NULL "
            "AND resolved_by IS NOT NULL AND resolution_reason IS NOT NULL "
            "AND length(trim(resolution_reason)) > 0)",
            name="ck_evidence_contradictions_resolution_consistency",
        ),
        Index("ix_evidence_contradictions_pack", "pack_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    pack_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("evidence_packs.id", ondelete="RESTRICT"), nullable=False
    )
    claim_key: Mapped[str] = mapped_column(String(100), nullable=False)
    evidence_side_a: Mapped[list[str]] = mapped_column(JSON_LIST, nullable=False)
    evidence_side_b: Mapped[list[str]] = mapped_column(JSON_LIST, nullable=False)
    nature: Mapped[str] = mapped_column(Text(), nullable=False)
    severity: Mapped[ContradictionSeverity] = mapped_column(
        string_enum(ContradictionSeverity, "ck_evidence_contradictions_severity", 16),
        nullable=False,
    )
    resolution_status: Mapped[ContradictionResolutionStatus] = mapped_column(
        string_enum(
            ContradictionResolutionStatus,
            "ck_evidence_contradictions_resolution_status",
            32,
        ),
        nullable=False,
        default=ContradictionResolutionStatus.UNRESOLVED,
    )
    handling_recommendation: Mapped[str | None] = mapped_column(Text(), nullable=True)
    resolution_reason: Mapped[str | None] = mapped_column(Text(), nullable=True)
    resolved_by: Mapped[ContradictionResolver | None] = mapped_column(
        string_enum(ContradictionResolver, "ck_evidence_contradictions_resolved_by", 16),
        nullable=True,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
