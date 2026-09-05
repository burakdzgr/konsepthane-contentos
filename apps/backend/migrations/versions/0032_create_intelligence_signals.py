"""Create intelligence_signals: ONE bounded store for role-specific signal
families (community_need, market, competition, taxonomy, ...).

Revision ID: 0032
Revises: 0031
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FAMILIES = (
    "inspiration",
    "community_need",
    "market",
    "competition",
    "taxonomy",
    "search",
    "trend",
    "visual_trend",
    "historical_performance",
)
_FAMILY_LIST = ", ".join(f"'{value}'" for value in _FAMILIES)


def upgrade() -> None:
    op.create_table(
        "intelligence_signals",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("family", sa.String(length=32), nullable=False),
        sa.Column("subject", sa.String(length=300), nullable=False),
        sa.Column("concept_key", sa.String(length=240), nullable=False),
        sa.Column("locale", sa.String(length=20), nullable=False),
        sa.Column("market", sa.String(length=2), nullable=False),
        sa.Column(
            "source_id",
            sa.Uuid(),
            sa.ForeignKey("sources.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "normalized_document_id",
            sa.Uuid(),
            sa.ForeignKey("normalized_documents.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "opportunity_id",
            sa.Uuid(),
            sa.ForeignKey("editorial_opportunities.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column(
            "value",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=False,
        ),
        sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observation_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("observation_hash", name="uq_intelligence_signals_observation_hash"),
        sa.CheckConstraint(f"family IN ({_FAMILY_LIST})", name="ck_intelligence_signals_family"),
        sa.CheckConstraint(
            "length(trim(subject)) > 0", name="ck_intelligence_signals_subject_nonempty"
        ),
        sa.CheckConstraint(
            "length(trim(concept_key)) > 0", name="ck_intelligence_signals_concept_nonempty"
        ),
        sa.CheckConstraint(
            "length(trim(provider)) > 0", name="ck_intelligence_signals_provider_nonempty"
        ),
        sa.CheckConstraint("occurrence_count >= 1", name="ck_intelligence_signals_occurrence_min"),
        sa.CheckConstraint(
            "length(observation_hash) = 64 AND observation_hash = lower(observation_hash)",
            name="ck_intelligence_signals_hash_format",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(value) = 'object'", name="ck_intelligence_signals_value_object"
        ),
    )
    op.create_index(
        "ix_intelligence_signals_family_concept",
        "intelligence_signals",
        ["family", "concept_key"],
    )
    op.create_index(
        "ix_intelligence_signals_opportunity", "intelligence_signals", ["opportunity_id"]
    )
    op.create_index(
        "ix_intelligence_signals_source_family",
        "intelligence_signals",
        ["source_id", "family"],
    )


def downgrade() -> None:
    op.drop_index("ix_intelligence_signals_source_family", table_name="intelligence_signals")
    op.drop_index("ix_intelligence_signals_opportunity", table_name="intelligence_signals")
    op.drop_index("ix_intelligence_signals_family_concept", table_name="intelligence_signals")
    op.drop_table("intelligence_signals")
