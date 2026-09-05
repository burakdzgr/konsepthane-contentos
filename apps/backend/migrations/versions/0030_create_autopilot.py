"""Create autopilot settings and events (ADR 0012).

Revision ID: 0030
Revises: 0029
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MODES = ("off", "supervised", "autonomous")
_KINDS = ("mode_changed", "action", "waiting", "skipped", "error")
_MODE_LIST = ", ".join(f"'{value}'" for value in _MODES)
_KIND_LIST = ", ".join(f"'{value}'" for value in _KINDS)


def upgrade() -> None:
    op.create_table(
        "autopilot_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column(
            "actor_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("id = 1", name="ck_autopilot_settings_singleton"),
        sa.CheckConstraint(f"mode IN ({_MODE_LIST})", name="ck_autopilot_settings_mode"),
        sa.CheckConstraint(
            "(mode = 'off') OR (actor_user_id IS NOT NULL)",
            name="ck_autopilot_settings_named_actor",
        ),
    )
    op.create_table(
        "autopilot_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "work_item_id",
            sa.Uuid(),
            sa.ForeignKey("editorial_work_items.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=True),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column(
            "detail",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=False,
        ),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(f"kind IN ({_KIND_LIST})", name="ck_autopilot_events_kind"),
        sa.CheckConstraint(f"mode IN ({_MODE_LIST})", name="ck_autopilot_events_mode"),
    )
    op.create_index(
        "ix_autopilot_events_work_item_created",
        "autopilot_events",
        ["work_item_id", "created_at"],
    )
    op.create_index("ix_autopilot_events_created", "autopilot_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_autopilot_events_created", table_name="autopilot_events")
    op.drop_index("ix_autopilot_events_work_item_created", table_name="autopilot_events")
    op.drop_table("autopilot_events")
    op.drop_table("autopilot_settings")
