"""Research missions: the research-driven idea engine's durable state.

Adds the mission, its inspiration signals and idea candidates; links an
EditorialOpportunity back to the candidate that produced it; widens the
generation-purpose and work-item-origin vocabularies for the mission calls.

Revision ID: 0039
Revises: 0038
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0039"
down_revision: str | None = "0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_PURPOSES = (
    "idea_candidates",
    "intent_synthesis",
    "brief_composition",
    "evidence_organization",
    "writer_draft",
    "editor_review",
    "media_image",
    "evidence_extraction",
)
_NEW_PURPOSES = (*_OLD_PURPOSES, "mission_planning", "web_research", "idea_synthesis")
_PURPOSE_CONSTRAINT = "ck_ai_generation_attempts_purpose"

_OLD_ORIGINS = ("research_intake", "operator")
_NEW_ORIGINS = (*_OLD_ORIGINS, "research_mission")
_ORIGIN_CONSTRAINT = "ck_editorial_work_items_origin"


def _in(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({quoted})"


def _timestamps() -> list[sa.Column[Any]]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "research_missions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("topic", sa.String(300), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("audience", sa.String(300), nullable=False),
        sa.Column("seed_keyword", sa.String(240), nullable=True),
        sa.Column(
            "topic_cluster_id",
            sa.Uuid(),
            sa.ForeignKey("topic_clusters.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("locale", sa.String(20), nullable=False),
        sa.Column("market", sa.String(2), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("stage", sa.String(20), nullable=False),
        sa.Column("plan", sa.JSON(), nullable=False),
        sa.Column("query_plan", sa.JSON(), nullable=False),
        sa.Column("keyword_plan", sa.JSON(), nullable=False),
        sa.Column("surface_summary", sa.JSON(), nullable=False),
        sa.Column("elimination_summary", sa.JSON(), nullable=False),
        sa.Column("result_summary", sa.JSON(), nullable=False),
        sa.Column("progress_log", sa.JSON(), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        *_timestamps(),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("length(trim(topic)) > 0", name="ck_research_missions_topic"),
        sa.CheckConstraint(
            _in(
                "status",
                (
                    "draft",
                    "queued",
                    "running",
                    "grounding",
                    "completed",
                    "needs_more_research",
                    "failed",
                ),
            ),
            name="ck_research_missions_status",
        ),
        sa.CheckConstraint(
            _in(
                "stage",
                (
                    "planning",
                    "keywords",
                    "searching",
                    "extracting",
                    "clustering",
                    "evaluating",
                    "grounding",
                    "promoting",
                    "completed",
                ),
            ),
            name="ck_research_missions_stage",
        ),
    )
    op.create_index(
        "ix_research_missions_status_created", "research_missions", ["status", "created_at"]
    )

    op.create_table(
        "mission_signals",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "mission_id",
            sa.Uuid(),
            sa.ForeignKey("research_missions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_id", sa.Uuid(), sa.ForeignKey("sources.id", ondelete="RESTRICT"), nullable=True
        ),
        sa.Column(
            "discovery_item_id",
            sa.Uuid(),
            sa.ForeignKey("discovery_items.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "normalized_document_id",
            sa.Uuid(),
            sa.ForeignKey("normalized_documents.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("surface_kind", sa.String(24), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("snippet", sa.Text(), nullable=True),
        sa.Column("reference_url", sa.String(2000), nullable=True),
        sa.Column("query", sa.String(300), nullable=True),
        sa.Column("signal_role", sa.String(40), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            _in(
                "surface_kind",
                (
                    "registered_source",
                    "open_web",
                    "visual_inspiration",
                    "community_need",
                    "trend_market",
                ),
            ),
            name="ck_mission_signals_surface",
        ),
    )
    op.create_index(
        "ix_mission_signals_mission_surface", "mission_signals", ["mission_id", "surface_kind"]
    )

    op.create_table(
        "mission_idea_candidates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "mission_id",
            sa.Uuid(),
            sa.ForeignKey("research_missions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("angle", sa.Text(), nullable=False),
        sa.Column("candidate_kind", sa.String(16), nullable=False),
        sa.Column("cluster_key", sa.String(240), nullable=False),
        sa.Column("primitives", sa.JSON(), nullable=False),
        sa.Column("implementation_steps", sa.JSON(), nullable=False),
        sa.Column("factual_claims_needed", sa.JSON(), nullable=False),
        sa.Column("signal_ids", sa.JSON(), nullable=False),
        sa.Column("is_cliche", sa.Boolean(), nullable=False),
        sa.Column("cliche_reason", sa.Text(), nullable=True),
        sa.Column("idea_quality", sa.Integer(), nullable=False),
        sa.Column("quality_factors", sa.JSON(), nullable=False),
        sa.Column("idea_confidence", sa.String(16), nullable=False),
        sa.Column("factual_evidence_confidence", sa.String(16), nullable=False),
        sa.Column("recommendation", sa.String(24), nullable=False),
        sa.Column(
            "merged_into_id",
            sa.Uuid(),
            sa.ForeignKey("mission_idea_candidates.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "opportunity_id",
            sa.Uuid(),
            sa.ForeignKey("editorial_opportunities.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("rationale", sa.Text(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "idea_quality >= 0 AND idea_quality <= 100", name="ck_mission_ideas_quality"
        ),
        sa.CheckConstraint(
            _in("candidate_kind", ("extracted", "synthesized")), name="ck_mission_ideas_kind"
        ),
        sa.CheckConstraint(
            _in("idea_confidence", ("high", "medium", "low")), name="ck_mission_ideas_confidence"
        ),
        sa.CheckConstraint(
            _in("factual_evidence_confidence", ("unknown", "not_required", "pending")),
            name="ck_mission_ideas_factual",
        ),
        sa.CheckConstraint(
            _in("recommendation", ("promote", "continue_research", "eliminate", "merged")),
            name="ck_mission_ideas_recommendation",
        ),
    )
    op.create_index(
        "ix_mission_ideas_mission_quality",
        "mission_idea_candidates",
        ["mission_id", "idea_quality"],
    )

    op.add_column(
        "editorial_opportunities",
        sa.Column(
            "mission_candidate_id",
            sa.Uuid(),
            sa.ForeignKey(
                "mission_idea_candidates.id",
                ondelete="SET NULL",
                name="fk_editorial_opportunities_mission_candidate",
            ),
            nullable=True,
        ),
    )

    op.drop_constraint(_PURPOSE_CONSTRAINT, "ai_generation_attempts", type_="check")
    op.create_check_constraint(
        _PURPOSE_CONSTRAINT, "ai_generation_attempts", _in("purpose", _NEW_PURPOSES)
    )
    op.drop_constraint(_ORIGIN_CONSTRAINT, "editorial_work_items", type_="check")
    op.create_check_constraint(
        _ORIGIN_CONSTRAINT, "editorial_work_items", _in("origin", _NEW_ORIGINS)
    )


def downgrade() -> None:
    bind = op.get_bind()
    widened = bind.execute(
        sa.text(
            "SELECT count(*) FROM ai_generation_attempts WHERE purpose IN "
            "('mission_planning', 'web_research', 'idea_synthesis')"
        )
    ).scalar_one()
    origins = bind.execute(
        sa.text("SELECT count(*) FROM editorial_work_items WHERE origin = 'research_mission'")
    ).scalar_one()
    if widened or origins:
        raise RuntimeError("cannot downgrade 0039: mission attempts or mission work items exist")
    op.drop_constraint(_ORIGIN_CONSTRAINT, "editorial_work_items", type_="check")
    op.create_check_constraint(
        _ORIGIN_CONSTRAINT, "editorial_work_items", _in("origin", _OLD_ORIGINS)
    )
    op.drop_constraint(_PURPOSE_CONSTRAINT, "ai_generation_attempts", type_="check")
    op.create_check_constraint(
        _PURPOSE_CONSTRAINT, "ai_generation_attempts", _in("purpose", _OLD_PURPOSES)
    )
    op.drop_constraint(
        "fk_editorial_opportunities_mission_candidate",
        "editorial_opportunities",
        type_="foreignkey",
    )
    op.drop_column("editorial_opportunities", "mission_candidate_id")
    op.drop_index("ix_mission_ideas_mission_quality", table_name="mission_idea_candidates")
    op.drop_table("mission_idea_candidates")
    op.drop_index("ix_mission_signals_mission_surface", table_name="mission_signals")
    op.drop_table("mission_signals")
    op.drop_index("ix_research_missions_status_created", table_name="research_missions")
    op.drop_table("research_missions")
