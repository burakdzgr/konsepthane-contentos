"""Create append-only opportunity scores and components.

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen literal vocabularies (never import app enums).
_BANDS = ("strong", "moderate", "weak", "ineligible")
_ELIGIBILITIES = ("commissionable", "not_commissionable", "needs_operator_review")
_AVAILABILITIES = ("known", "unknown", "not_applicable")
_COMPONENTS = (
    "recency",
    "audience_fit",
    "evidence_availability",
    "source_diversity",
    "source_trust",
    "competition",
    "search_demand",
    "editorial_value",
    "seasonality",
    "duplicate_overlap_risk",
    "policy_risk",
    "production_cost_estimate",
)

_SCORE_FUNCTION = "contentos_reject_opportunity_score_mutation"
_SCORE_TRIGGER = "trg_opportunity_scores_append_only"
_COMPONENT_FUNCTION = "contentos_reject_opportunity_score_component_mutation"
_COMPONENT_TRIGGER = "trg_opportunity_score_components_append_only"


def _string_enum(values: tuple[str, ...], constraint_name: str, length: int) -> sa.Enum:
    return sa.Enum(
        *values,
        name=constraint_name,
        native_enum=False,
        create_constraint=True,
        length=length,
    )


def upgrade() -> None:
    op.create_table(
        "opportunity_scores",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "opportunity_id",
            sa.Uuid(),
            sa.ForeignKey("editorial_opportunities.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("engine_name", sa.String(length=100), nullable=False),
        sa.Column("engine_version", sa.String(length=100), nullable=False),
        sa.Column(
            "overall_band",
            _string_enum(_BANDS, "ck_opportunity_scores_overall_band", 16),
            nullable=False,
        ),
        sa.Column("overall_value", sa.Float(), nullable=True),
        sa.Column(
            "eligibility",
            _string_enum(_ELIGIBILITIES, "ck_opportunity_scores_eligibility", 24),
            nullable=False,
        ),
        sa.Column(
            "weights_snapshot",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "threshold_snapshot",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "missing_signals",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "risk_flags",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "input_snapshot",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("input_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "opportunity_id",
            "engine_name",
            "engine_version",
            "input_snapshot_hash",
            name="uq_opportunity_scores_identity",
        ),
        sa.CheckConstraint(
            "length(trim(engine_name)) > 0",
            name="ck_opportunity_scores_engine_name_nonempty",
        ),
        sa.CheckConstraint(
            "length(trim(engine_version)) > 0",
            name="ck_opportunity_scores_engine_version_nonempty",
        ),
        sa.CheckConstraint(
            "length(input_snapshot_hash) = 64 AND input_snapshot_hash = lower(input_snapshot_hash)",
            name="ck_opportunity_scores_hash_format",
        ),
        sa.CheckConstraint(
            "overall_value IS NULL OR (overall_value >= 0 AND overall_value <= 1)",
            name="ck_opportunity_scores_value_range",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(weights_snapshot) = 'object'",
            name="ck_opportunity_scores_weights_object",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(threshold_snapshot) = 'object'",
            name="ck_opportunity_scores_thresholds_object",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(input_snapshot) = 'object'",
            name="ck_opportunity_scores_snapshot_object",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(missing_signals) = 'array'",
            name="ck_opportunity_scores_missing_array",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(risk_flags) = 'array'",
            name="ck_opportunity_scores_risk_array",
        ),
    )
    op.create_index(
        "ix_opportunity_scores_opportunity",
        "opportunity_scores",
        ["opportunity_id", "evaluated_at"],
    )

    op.create_table(
        "opportunity_score_components",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "score_id",
            sa.Uuid(),
            sa.ForeignKey("opportunity_scores.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "component",
            _string_enum(_COMPONENTS, "ck_opportunity_score_components_component", 32),
            nullable=False,
        ),
        sa.Column(
            "availability",
            _string_enum(_AVAILABILITIES, "ck_opportunity_score_components_availability", 16),
            nullable=False,
        ),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("provider", sa.String(length=100), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "provenance_ref",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "score_id",
            "component",
            name="uq_opportunity_score_components_component",
        ),
        sa.CheckConstraint(
            "(availability = 'known' AND value IS NOT NULL) OR "
            "(availability != 'known' AND value IS NULL)",
            name="ck_opportunity_score_components_value_presence",
        ),
        sa.CheckConstraint(
            "value IS NULL OR (value >= 0 AND value <= 1)",
            name="ck_opportunity_score_components_value_range",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_opportunity_score_components_confidence_range",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(provenance_ref) = 'object'",
            name="ck_opportunity_score_components_provenance_object",
        ),
    )
    op.create_index(
        "ix_opportunity_score_components_score",
        "opportunity_score_components",
        ["score_id"],
    )

    for function_name, trigger_name, table_name in (
        (_SCORE_FUNCTION, _SCORE_TRIGGER, "opportunity_scores"),
        (_COMPONENT_FUNCTION, _COMPONENT_TRIGGER, "opportunity_score_components"),
    ):
        op.execute(
            sa.text(
                f"""
                CREATE FUNCTION {function_name}()
                RETURNS trigger
                LANGUAGE plpgsql
                AS $$
                BEGIN
                    RAISE EXCEPTION
                        '{table_name} is append-only; % is forbidden', TG_OP
                        USING ERRCODE = '55000';
                END;
                $$
                """
            )
        )
        op.execute(
            sa.text(
                f"""
                CREATE TRIGGER {trigger_name}
                BEFORE UPDATE OR DELETE ON {table_name}
                FOR EACH ROW
                EXECUTE FUNCTION {function_name}()
                """
            )
        )


def downgrade() -> None:
    op.execute(sa.text(f"DROP TRIGGER {_COMPONENT_TRIGGER} ON opportunity_score_components"))
    op.execute(sa.text(f"DROP FUNCTION {_COMPONENT_FUNCTION}()"))
    op.execute(sa.text(f"DROP TRIGGER {_SCORE_TRIGGER} ON opportunity_scores"))
    op.execute(sa.text(f"DROP FUNCTION {_SCORE_FUNCTION}()"))
    op.drop_index(
        "ix_opportunity_score_components_score", table_name="opportunity_score_components"
    )
    op.drop_table("opportunity_score_components")
    op.drop_index("ix_opportunity_scores_opportunity", table_name="opportunity_scores")
    op.drop_table("opportunity_scores")
