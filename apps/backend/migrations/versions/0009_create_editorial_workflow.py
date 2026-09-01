"""Create the canonical editorial workflow aggregate.

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen literal vocabulary from docs/WORKFLOW.md (never import app enums).
_WORKFLOW_STATES = (
    "discovered",
    "researching",
    "normalized",
    "duplicate_check",
    "duplicate",
    "idea_scoring",
    "evidence_building",
    "seo_research",
    "briefing",
    "drafting",
    "editing",
    "qa_review",
    "awaiting_human_review",
    "approved",
    "scheduled",
    "publishing",
    "published",
    "pinterest_pending",
    "distributed",
    "measuring",
    "refresh_candidate",
    "changes_requested",
    "blocked",
    "approval_expired",
    "rejected",
    "archived",
)
_ORIGINS = ("research_intake", "operator")
_ACTOR_ORIGINS = ("operator", "system")

_IMMUTABILITY_FUNCTION = "contentos_reject_editorial_workflow_event_mutation"
_IMMUTABILITY_TRIGGER = "trg_editorial_workflow_events_append_only"


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
        "editorial_work_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("locale", sa.String(length=20), nullable=False),
        sa.Column("market", sa.String(length=2), nullable=False),
        sa.Column(
            "origin",
            _string_enum(_ORIGINS, "ck_editorial_work_items_origin", 16),
            nullable=False,
        ),
        sa.Column(
            "current_state",
            _string_enum(_WORKFLOW_STATES, "ck_editorial_work_items_current_state", 24),
            nullable=False,
        ),
        sa.Column("current_state_entered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("title_working_label", sa.String(length=200), nullable=False),
        sa.Column("blocked_reason", sa.Text(), nullable=True),
        sa.Column("rejected_reason", sa.Text(), nullable=True),
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
        sa.CheckConstraint(
            "length(trim(locale)) > 0",
            name="ck_editorial_work_items_locale_nonempty",
        ),
        sa.CheckConstraint(
            "length(trim(market)) = 2",
            name="ck_editorial_work_items_market_length",
        ),
        sa.CheckConstraint(
            "length(trim(title_working_label)) > 0",
            name="ck_editorial_work_items_label_nonempty",
        ),
        sa.CheckConstraint(
            "current_state != 'blocked' OR "
            "(blocked_reason IS NOT NULL AND length(trim(blocked_reason)) > 0)",
            name="ck_editorial_work_items_blocked_reason",
        ),
        sa.CheckConstraint(
            "current_state != 'rejected' OR "
            "(rejected_reason IS NOT NULL AND length(trim(rejected_reason)) > 0)",
            name="ck_editorial_work_items_rejected_reason",
        ),
    )
    op.create_index(
        "ix_editorial_work_items_current_state",
        "editorial_work_items",
        ["current_state"],
    )
    op.create_index(
        "ix_editorial_work_items_created_at",
        "editorial_work_items",
        ["created_at"],
    )

    op.create_table(
        "editorial_workflow_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column(
            "work_item_id",
            sa.Uuid(),
            sa.ForeignKey("editorial_work_items.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "from_state",
            _string_enum(_WORKFLOW_STATES, "ck_editorial_workflow_events_from_state", 24),
            nullable=True,
        ),
        sa.Column(
            "to_state",
            _string_enum(_WORKFLOW_STATES, "ck_editorial_workflow_events_to_state", 24),
            nullable=False,
        ),
        sa.Column(
            "actor_origin",
            _string_enum(_ACTOR_ORIGINS, "ck_editorial_workflow_events_actor_origin", 16),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "artifact_refs",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(trim(reason)) > 0",
            name="ck_editorial_workflow_events_reason_nonempty",
        ),
        sa.CheckConstraint(
            "request_id IS NULL OR length(trim(request_id)) > 0",
            name="ck_editorial_workflow_events_request_id_nonempty",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(artifact_refs) = 'object'",
            name="ck_editorial_workflow_events_artifact_refs_object",
        ),
    )
    op.create_index(
        "ix_editorial_workflow_events_work_item",
        "editorial_workflow_events",
        ["work_item_id", "id"],
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
                    'editorial_workflow_events is append-only; % is forbidden', TG_OP
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
            BEFORE UPDATE OR DELETE ON editorial_workflow_events
            FOR EACH ROW
            EXECUTE FUNCTION {_IMMUTABILITY_FUNCTION}()
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text(f"DROP TRIGGER {_IMMUTABILITY_TRIGGER} ON editorial_workflow_events"))
    op.execute(sa.text(f"DROP FUNCTION {_IMMUTABILITY_FUNCTION}()"))
    op.drop_index("ix_editorial_workflow_events_work_item", table_name="editorial_workflow_events")
    op.drop_table("editorial_workflow_events")
    op.drop_index("ix_editorial_work_items_created_at", table_name="editorial_work_items")
    op.drop_index("ix_editorial_work_items_current_state", table_name="editorial_work_items")
    op.drop_table("editorial_work_items")
