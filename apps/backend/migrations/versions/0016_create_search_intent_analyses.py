"""Create search intent analyses.

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen literal vocabulary (never import app enums). KNOWN_CONFLICT is
# accepted future vocabulary; the current service refuses to record it.
_CANNIBALIZATION_STATUSES = (
    "not_checked",
    "no_known_conflict",
    "potential_conflict",
    "known_conflict",
)

_ANALYSIS_FUNCTION = "contentos_reject_search_intent_analysis_mutation"
_ANALYSIS_TRIGGER = "trg_search_intent_analyses_append_only"


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
        "search_intent_analyses",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "opportunity_id",
            sa.Uuid(),
            sa.ForeignKey("editorial_opportunities.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "idea_id",
            sa.Uuid(),
            sa.ForeignKey("ideas.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("primary_intent", sa.String(length=200), nullable=False),
        sa.Column(
            "secondary_intents",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("target_audience", sa.String(length=500), nullable=False),
        sa.Column(
            "query_concepts",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("page_purpose", sa.String(length=500), nullable=False),
        sa.Column("likely_format", sa.String(length=200), nullable=False),
        sa.Column(
            "known_signal_refs",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "missing_signals",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "cannibalization_status",
            _string_enum(
                _CANNIBALIZATION_STATUSES,
                "ck_search_intent_analyses_cannibalization",
                24,
            ),
            nullable=False,
        ),
        sa.Column(
            "cannibalization_basis",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "related_references",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("locale", sa.String(length=20), nullable=False),
        sa.Column("market", sa.String(length=2), nullable=False),
        sa.Column("engine_name", sa.String(length=100), nullable=False),
        sa.Column("engine_version", sa.String(length=50), nullable=False),
        sa.Column(
            "synthesis_attempt_id",
            sa.Uuid(),
            sa.ForeignKey("ai_generation_attempts.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "input_snapshot",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("input_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("opportunity_id", "version", name="uq_search_intent_analyses_version"),
        sa.UniqueConstraint(
            "opportunity_id",
            "engine_name",
            "engine_version",
            "input_snapshot_hash",
            name="uq_search_intent_analyses_identity",
        ),
        sa.CheckConstraint("version > 0", name="ck_search_intent_analyses_version_positive"),
        sa.CheckConstraint(
            "length(trim(primary_intent)) > 0",
            name="ck_search_intent_analyses_primary_intent_nonempty",
        ),
        sa.CheckConstraint(
            "length(trim(target_audience)) > 0",
            name="ck_search_intent_analyses_audience_nonempty",
        ),
        sa.CheckConstraint(
            "length(trim(page_purpose)) > 0",
            name="ck_search_intent_analyses_page_purpose_nonempty",
        ),
        sa.CheckConstraint(
            "length(trim(likely_format)) > 0",
            name="ck_search_intent_analyses_likely_format_nonempty",
        ),
        sa.CheckConstraint(
            "length(trim(locale)) > 0", name="ck_search_intent_analyses_locale_nonempty"
        ),
        sa.CheckConstraint(
            "length(trim(market)) = 2", name="ck_search_intent_analyses_market_length"
        ),
        sa.CheckConstraint(
            "length(trim(engine_name)) > 0",
            name="ck_search_intent_analyses_engine_name_nonempty",
        ),
        sa.CheckConstraint(
            "length(trim(engine_version)) > 0",
            name="ck_search_intent_analyses_engine_version_nonempty",
        ),
        sa.CheckConstraint(
            "length(input_snapshot_hash) = 64 AND input_snapshot_hash = lower(input_snapshot_hash)",
            name="ck_search_intent_analyses_hash_format",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(secondary_intents) = 'array'",
            name="ck_search_intent_analyses_secondary_array",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(query_concepts) = 'array'",
            name="ck_search_intent_analyses_concepts_array",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(known_signal_refs) = 'array'",
            name="ck_search_intent_analyses_signal_refs_array",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(missing_signals) = 'array'",
            name="ck_search_intent_analyses_missing_array",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(cannibalization_basis) = 'object'",
            name="ck_search_intent_analyses_basis_object",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(related_references) = 'array'",
            name="ck_search_intent_analyses_related_array",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(input_snapshot) = 'object'",
            name="ck_search_intent_analyses_snapshot_object",
        ),
    )
    op.create_index(
        "ix_search_intent_analyses_opportunity",
        "search_intent_analyses",
        ["opportunity_id", "version"],
    )
    op.create_index("ix_search_intent_analyses_idea", "search_intent_analyses", ["idea_id"])
    op.create_index(
        "ix_search_intent_analyses_synthesis_attempt",
        "search_intent_analyses",
        ["synthesis_attempt_id"],
    )

    op.execute(
        sa.text(
            f"""
            CREATE FUNCTION {_ANALYSIS_FUNCTION}()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION
                    'search_intent_analyses is append-only; % is forbidden', TG_OP
                    USING ERRCODE = '55000';
            END;
            $$
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            CREATE TRIGGER {_ANALYSIS_TRIGGER}
            BEFORE UPDATE OR DELETE ON search_intent_analyses
            FOR EACH ROW
            EXECUTE FUNCTION {_ANALYSIS_FUNCTION}()
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text(f"DROP TRIGGER {_ANALYSIS_TRIGGER} ON search_intent_analyses"))
    op.execute(sa.text(f"DROP FUNCTION {_ANALYSIS_FUNCTION}()"))
    op.drop_index(
        "ix_search_intent_analyses_synthesis_attempt", table_name="search_intent_analyses"
    )
    op.drop_index("ix_search_intent_analyses_idea", table_name="search_intent_analyses")
    op.drop_index("ix_search_intent_analyses_opportunity", table_name="search_intent_analyses")
    op.drop_table("search_intent_analyses")
