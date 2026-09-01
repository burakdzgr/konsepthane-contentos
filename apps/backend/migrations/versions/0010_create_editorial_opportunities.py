"""Create editorial opportunities and research inputs.

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen literal vocabularies (never import app enums).
_DISPOSITIONS = ("open", "commissioned", "rejected")
_ROLES = ("primary_signal", "supporting", "contradicting", "context", "update_signal")
_ACTORS = ("system", "operator")

_IMMUTABILITY_FUNCTION = "contentos_reject_opportunity_research_input_mutation"
_IMMUTABILITY_TRIGGER = "trg_opportunity_research_inputs_append_only"


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
        "editorial_opportunities",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "work_item_id",
            sa.Uuid(),
            sa.ForeignKey("editorial_work_items.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "promotion_root_document_id",
            sa.Uuid(),
            sa.ForeignKey("normalized_documents.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("topic_summary", sa.Text(), nullable=False),
        sa.Column("update_of_reference", sa.String(length=500), nullable=True),
        sa.Column(
            "disposition",
            _string_enum(_DISPOSITIONS, "ck_editorial_opportunities_disposition", 16),
            nullable=False,
        ),
        sa.Column("disposition_reason", sa.Text(), nullable=True),
        sa.Column("disposition_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "disposition_by",
            _string_enum(_ACTORS, "ck_editorial_opportunities_disposition_by", 16),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("work_item_id", name="uq_editorial_opportunities_work_item"),
        sa.UniqueConstraint(
            "promotion_root_document_id",
            name="uq_editorial_opportunities_promotion_root",
        ),
        sa.CheckConstraint(
            "length(trim(topic_summary)) > 0",
            name="ck_editorial_opportunities_topic_nonempty",
        ),
        sa.CheckConstraint(
            "(disposition = 'open' AND disposition_reason IS NULL "
            "AND disposition_at IS NULL AND disposition_by IS NULL) OR "
            "(disposition != 'open' AND disposition_reason IS NOT NULL "
            "AND length(trim(disposition_reason)) > 0 "
            "AND disposition_at IS NOT NULL AND disposition_by IS NOT NULL)",
            name="ck_editorial_opportunities_disposition_consistency",
        ),
    )
    op.create_index(
        "ix_editorial_opportunities_disposition",
        "editorial_opportunities",
        ["disposition"],
    )

    op.create_table(
        "opportunity_research_inputs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "opportunity_id",
            sa.Uuid(),
            sa.ForeignKey("editorial_opportunities.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "normalized_document_id",
            sa.Uuid(),
            sa.ForeignKey("normalized_documents.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "duplicate_decision_id",
            sa.Uuid(),
            sa.ForeignKey("duplicate_decisions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "role",
            _string_enum(_ROLES, "ck_opportunity_research_inputs_role", 16),
            nullable=False,
        ),
        sa.Column(
            "added_by",
            _string_enum(_ACTORS, "ck_opportunity_research_inputs_added_by", 16),
            nullable=False,
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "opportunity_id",
            "normalized_document_id",
            name="uq_opportunity_research_inputs_document",
        ),
    )
    op.create_index(
        "ix_opportunity_research_inputs_document",
        "opportunity_research_inputs",
        ["normalized_document_id"],
    )

    op.execute(
        sa.text(
            f"""
            CREATE FUNCTION {_IMMUTABILITY_FUNCTION}()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION
                    'opportunity_research_inputs is append-only; % is forbidden', TG_OP
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
            BEFORE UPDATE OR DELETE ON opportunity_research_inputs
            FOR EACH ROW
            EXECUTE FUNCTION {_IMMUTABILITY_FUNCTION}()
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text(f"DROP TRIGGER {_IMMUTABILITY_TRIGGER} ON opportunity_research_inputs"))
    op.execute(sa.text(f"DROP FUNCTION {_IMMUTABILITY_FUNCTION}()"))
    op.drop_index(
        "ix_opportunity_research_inputs_document", table_name="opportunity_research_inputs"
    )
    op.drop_table("opportunity_research_inputs")
    op.drop_index("ix_editorial_opportunities_disposition", table_name="editorial_opportunities")
    op.drop_table("editorial_opportunities")
