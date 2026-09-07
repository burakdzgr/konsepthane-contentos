"""Durable daily preparation target, selected sources and quota reservations."""

import sqlalchemy as sa
from alembic import op

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("autopilot_settings", sa.Column("daily_target", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "ck_autopilot_daily_target",
        "autopilot_settings",
        "daily_target IS NULL OR daily_target BETWEEN 1 AND 50",
    )
    op.create_table(
        "autopilot_sources",
        sa.Column(
            "source_id",
            sa.Uuid(),
            sa.ForeignKey("sources.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("last_researched_on", sa.Date(), nullable=True),
    )
    op.create_table(
        "daily_preparations",
        sa.Column(
            "work_item_id",
            sa.Uuid(),
            sa.ForeignKey("editorial_work_items.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("reserved_on", sa.Date(), nullable=False),
        sa.Column("completed_on", sa.Date(), nullable=True),
    )
    op.create_index("ix_daily_preparations_completed_on", "daily_preparations", ["completed_on"])


def downgrade() -> None:
    op.drop_table("daily_preparations")
    op.drop_table("autopilot_sources")
    op.drop_constraint("ck_autopilot_daily_target", "autopilot_settings", type_="check")
    op.drop_column("autopilot_settings", "daily_target")
