"""Create external-integration status, request log and response cache.

Revision ID: 0033
Revises: 0032
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATES = (
    "healthy",
    "not_configured",
    "access_required",
    "rate_limited",
    "degraded",
    "error",
)
_STATE_LIST = ", ".join(f"'{value}'" for value in _STATES)


def upgrade() -> None:
    op.create_table(
        "integration_status",
        sa.Column("provider", sa.String(length=40), primary_key=True),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False, server_default=""),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_class", sa.String(length=64), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(f"state IN ({_STATE_LIST})", name="ck_integration_status_state"),
        sa.CheckConstraint(
            "length(trim(provider)) > 0",
            name="ck_integration_status_provider_nonempty",
        ),
    )
    op.create_table(
        "provider_request_log",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "request_count >= 0",
            name="ck_provider_request_log_count_nonnegative",
        ),
    )
    op.create_index(
        "uq_provider_request_log_day",
        "provider_request_log",
        ["provider", "day"],
        unique=True,
    )
    op.create_table(
        "provider_cache",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("cache_key", sa.String(length=64), nullable=False),
        sa.Column(
            "payload",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=False,
        ),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(cache_key) = 64 AND cache_key = lower(cache_key)",
            name="ck_provider_cache_key_format",
        ),
    )
    op.create_index(
        "uq_provider_cache_key",
        "provider_cache",
        ["provider", "cache_key"],
        unique=True,
    )
    op.create_index("ix_provider_cache_expires", "provider_cache", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_provider_cache_expires", table_name="provider_cache")
    op.drop_index("uq_provider_cache_key", table_name="provider_cache")
    op.drop_table("provider_cache")
    op.drop_index("uq_provider_request_log_day", table_name="provider_request_log")
    op.drop_table("provider_request_log")
    op.drop_table("integration_status")
