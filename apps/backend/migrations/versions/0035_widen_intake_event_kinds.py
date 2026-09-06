"""Widen intake event kinds: promotion_skipped_by_role.

Sources whose editorial role is community intent, competitor, taxonomy,
trend or search feed SIGNALS only; their pages are never promoted to
opportunities. The intake run records that decision once per run as its
own event kind so the operator sees "sinyal kaynağı, terfi yok" instead of
a misleading "promotion cap reached".

Revision ID: 0035
Revises: 0034
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0035"
down_revision: str | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KINDS_BEFORE = (
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
_KINDS_AFTER = (*_KINDS_BEFORE, "promotion_skipped_by_role")


def _values(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.drop_constraint("ck_intake_run_events_kind", "intake_run_events", type_="check")
    op.create_check_constraint(
        "ck_intake_run_events_kind",
        "intake_run_events",
        f"kind IN ({_values(_KINDS_AFTER)})",
    )


def downgrade() -> None:
    op.execute("DELETE FROM intake_run_events WHERE kind = 'promotion_skipped_by_role'")
    op.drop_constraint("ck_intake_run_events_kind", "intake_run_events", type_="check")
    op.create_check_constraint(
        "ck_intake_run_events_kind",
        "intake_run_events",
        f"kind IN ({_values(_KINDS_BEFORE)})",
    )
