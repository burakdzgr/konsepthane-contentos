"""Create intake runs and their append-only event feed.

Revision ID: 0028
Revises: 0027
Create Date: 2026-09-03

`intake_runs` is the durable operator-visible record of one bounded
autonomous intake orchestration over a source; `intake_run_events` is
its append-only timeline. Counters are conveniences — the research
pipeline rows stay authoritative for every domain fact.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUSES = ("running", "paused", "completed", "stopped", "failed")
_STAGES = ("run", "discovery", "prefilter", "fetch", "promote")
_KINDS = (
    "run_started",
    "run_paused",
    "run_resumed",
    "run_stopped",
    "run_completed",
    "run_failed",
    "discovery_started",
    "discovery_completed",
    "discovery_retrying",
    "prefilter_progress",
    "prefilter_completed",
    "fetch_batch_dispatched",
    "fetch_item_dispatched",
    "fetch_progress",
    "fetch_budget_exhausted",
    "fetch_cap_reached",
    "fetch_completed",
    "promotion_dispatched",
    "promotion_cap_reached",
    "operational_pause",
    "step_error",
)


def _values(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.create_table(
        "intake_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "source_id",
            sa.Uuid(),
            sa.ForeignKey("sources.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "started_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column(
            "policy", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False
        ),
        sa.Column("discovered_new", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rediscovered", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("prefilter_accepted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("prefilter_rejected", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fetch_dispatched", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fetched", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fetch_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("promotions_dispatched", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("opportunities_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("discovery_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("prefilter_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_note", sa.Text(), nullable=True),
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
            f"status IN ({_values(_STATUSES)})",
            name="ck_intake_runs_status",
        ),
        sa.CheckConstraint(
            "failure_note IS NULL OR length(trim(failure_note)) > 0",
            name="ck_intake_runs_failure_note_nonempty",
        ),
    )
    op.create_index("ix_intake_runs_source", "intake_runs", ["source_id", "created_at"])
    op.create_index(
        "uq_intake_runs_live_per_source",
        "intake_runs",
        ["source_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('running', 'paused')"),
    )
    op.create_table(
        "intake_run_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("intake_runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("stage", sa.String(length=16), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column(
            "detail", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False
        ),
        sa.Column(
            "actor_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            f"stage IN ({_values(_STAGES)})",
            name="ck_intake_run_events_stage",
        ),
        sa.CheckConstraint(
            f"kind IN ({_values(_KINDS)})",
            name="ck_intake_run_events_kind",
        ),
    )
    op.create_index("ix_intake_run_events_run", "intake_run_events", ["run_id", "id"])


def downgrade() -> None:
    op.drop_index("ix_intake_run_events_run", table_name="intake_run_events")
    op.drop_table("intake_run_events")
    op.drop_index("uq_intake_runs_live_per_source", table_name="intake_runs")
    op.drop_index("ix_intake_runs_source", table_name="intake_runs")
    op.drop_table("intake_runs")
