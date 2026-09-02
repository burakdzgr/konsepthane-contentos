"""Create human decisions; add the named actor to workflow events.

Revision ID: 0022
Revises: 0021
Create Date: 2026-09-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen literal vocabulary (never import app enums).
_DECISIONS = ("approved", "changes_requested", "rejected", "approval_revoked")

_DECISION_FUNCTION = "contentos_reject_human_decision_mutation"
_DECISION_TRIGGER = "trg_human_decisions_append_only"


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
        "human_decisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "work_item_id",
            sa.Uuid(),
            sa.ForeignKey("editorial_work_items.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "reviewer_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "decision",
            _string_enum(_DECISIONS, "ck_human_decisions_decision", 24),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "qa_report_id",
            sa.Uuid(),
            sa.ForeignKey("qa_reports.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "content_draft_id",
            sa.Uuid(),
            sa.ForeignKey("content_drafts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "editorial_review_id",
            sa.Uuid(),
            sa.ForeignKey("editorial_reviews.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "revokes_decision_id",
            sa.Uuid(),
            sa.ForeignKey("human_decisions.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("length(trim(reason)) > 0", name="ck_human_decisions_reason_nonempty"),
        sa.CheckConstraint(
            "length(content_hash) = 64 AND content_hash = lower(content_hash)",
            name="ck_human_decisions_hash_format",
        ),
        sa.CheckConstraint(
            "(decision = 'approval_revoked') = (revokes_decision_id IS NOT NULL)",
            name="ck_human_decisions_revocation_reference",
        ),
        sa.CheckConstraint(
            "request_id IS NULL OR length(trim(request_id)) > 0",
            name="ck_human_decisions_request_id_nonempty",
        ),
    )
    op.create_index(
        "ix_human_decisions_work_item", "human_decisions", ["work_item_id", "created_at"]
    )
    op.create_index("ix_human_decisions_reviewer", "human_decisions", ["reviewer_user_id"])

    op.execute(
        sa.text(
            f"""
            CREATE FUNCTION {_DECISION_FUNCTION}()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION
                    'human_decisions is append-only; % is forbidden', TG_OP
                    USING ERRCODE = '55000';
            END;
            $$
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            CREATE TRIGGER {_DECISION_TRIGGER}
            BEFORE UPDATE OR DELETE ON human_decisions
            FOR EACH ROW
            EXECUTE FUNCTION {_DECISION_FUNCTION}()
            """
        )
    )

    # Additive: the named authenticated actor behind a workflow transition.
    # Historical rows stay NULL (honest UNKNOWN).
    op.add_column(
        "editorial_workflow_events",
        sa.Column(
            "actor_user_id",
            sa.Uuid(),
            sa.ForeignKey(
                "users.id",
                ondelete="RESTRICT",
                name="fk_editorial_workflow_events_actor_user",
            ),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_editorial_workflow_events_actor_user",
        "editorial_workflow_events",
        ["actor_user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_editorial_workflow_events_actor_user", table_name="editorial_workflow_events")
    op.drop_column("editorial_workflow_events", "actor_user_id")
    op.execute(sa.text(f"DROP TRIGGER {_DECISION_TRIGGER} ON human_decisions"))
    op.execute(sa.text(f"DROP FUNCTION {_DECISION_FUNCTION}()"))
    op.drop_index("ix_human_decisions_reviewer", table_name="human_decisions")
    op.drop_index("ix_human_decisions_work_item", table_name="human_decisions")
    op.drop_table("human_decisions")
