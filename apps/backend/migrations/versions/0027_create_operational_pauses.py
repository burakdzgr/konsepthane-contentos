"""Create operational pause state and its append-only audit.

Revision ID: 0027
Revises: 0026
Create Date: 2026-09-03

`operational_pauses` holds the current intake state per scope (engine or
one job family); `operational_pause_events` audits every pause/resume
with the named actor and required reason. Pauses gate NEW dispatch only
at the control surface — no workflow state, queue content, or running
task is touched by these tables.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCOPES = (
    "engine",
    "research",
    "opportunity",
    "ideas",
    "evidence",
    "intent",
    "brief",
    "writer",
    "editor",
    "qa",
    "media",
    "publisher",
)
_SCOPE_LIST = ", ".join(f"'{scope}'" for scope in _SCOPES)


def upgrade() -> None:
    op.create_table(
        "operational_pauses",
        sa.Column("scope", sa.String(length=16), primary_key=True),
        sa.Column("is_paused", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "actor_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            f"scope IN ({_SCOPE_LIST})",
            name="ck_operational_pauses_scope",
        ),
        sa.CheckConstraint(
            "(NOT is_paused) OR (reason IS NOT NULL AND length(trim(reason)) > 0)",
            name="ck_operational_pauses_paused_reason",
        ),
    )
    op.create_table(
        "operational_pause_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "actor_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            f"scope IN ({_SCOPE_LIST})",
            name="ck_operational_pause_events_scope",
        ),
        sa.CheckConstraint(
            "action IN ('paused', 'resumed')",
            name="ck_operational_pause_events_action",
        ),
        sa.CheckConstraint(
            "length(trim(reason)) > 0",
            name="ck_operational_pause_events_reason_nonempty",
        ),
        sa.CheckConstraint(
            "request_id IS NULL OR length(trim(request_id)) > 0",
            name="ck_operational_pause_events_request_id_nonempty",
        ),
    )
    op.create_index(
        "ix_operational_pause_events_scope",
        "operational_pause_events",
        ["scope", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_operational_pause_events_scope", table_name="operational_pause_events")
    op.drop_table("operational_pause_events")
    op.drop_table("operational_pauses")
