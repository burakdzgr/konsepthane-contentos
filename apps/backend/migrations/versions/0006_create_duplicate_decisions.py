"""Create immutable duplicate_decisions.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DECISIONS = ("unique", "related", "update_existing", "duplicate", "reject")
_IMMUTABILITY_FUNCTION = "contentos_reject_duplicate_decision_mutation"
_IMMUTABILITY_TRIGGER = "trg_duplicate_decisions_append_only"


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
        "duplicate_decisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "normalized_document_id",
            sa.Uuid(),
            sa.ForeignKey("normalized_documents.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("engine_name", sa.String(length=100), nullable=False),
        sa.Column("engine_version", sa.String(length=100), nullable=False),
        sa.Column(
            "decision",
            _string_enum(_DECISIONS, "ck_duplicate_decisions_decision", 16),
            nullable=False,
        ),
        sa.Column(
            "signals",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "thresholds",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "matches",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "rationale_codes",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "normalized_document_id",
            "engine_name",
            "engine_version",
            name="uq_duplicate_decisions_document_engine",
        ),
        sa.CheckConstraint(
            "length(trim(engine_name)) > 0",
            name="ck_duplicate_decisions_engine_name_nonempty",
        ),
        sa.CheckConstraint(
            "length(trim(engine_version)) > 0",
            name="ck_duplicate_decisions_engine_version_nonempty",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(signals) = 'object'",
            name="ck_duplicate_decisions_signals_object",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(thresholds) = 'object'",
            name="ck_duplicate_decisions_thresholds_object",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(matches) = 'array'",
            name="ck_duplicate_decisions_matches_array",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(rationale_codes) = 'array'",
            name="ck_duplicate_decisions_rationale_array",
        ),
    )
    op.create_index(
        "ix_duplicate_decisions_decision",
        "duplicate_decisions",
        ["decision"],
    )
    op.create_index(
        "ix_duplicate_decisions_evaluated_at",
        "duplicate_decisions",
        ["evaluated_at"],
    )
    op.execute(
        sa.text(
            f"""
            CREATE FUNCTION {_IMMUTABILITY_FUNCTION}()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION 'duplicate_decisions is append-only; % is forbidden', TG_OP
                    USING ERRCODE = '55000';
            END;
            $$
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            CREATE TRIGGER {_IMMUTABILITY_TRIGGER}
            BEFORE UPDATE OR DELETE ON duplicate_decisions
            FOR EACH ROW
            EXECUTE FUNCTION {_IMMUTABILITY_FUNCTION}()
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text(f"DROP TRIGGER {_IMMUTABILITY_TRIGGER} ON duplicate_decisions"))
    op.execute(sa.text(f"DROP FUNCTION {_IMMUTABILITY_FUNCTION}()"))
    op.drop_index("ix_duplicate_decisions_evaluated_at", table_name="duplicate_decisions")
    op.drop_index("ix_duplicate_decisions_decision", table_name="duplicate_decisions")
    op.drop_table("duplicate_decisions")
