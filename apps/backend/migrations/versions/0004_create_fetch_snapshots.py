"""Create immutable fetch_snapshots.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen literal enum values; this migration must not change if application
# enums evolve later.
_FETCH_OUTCOMES = (
    "success",
    "invalid_url",
    "ssrf_blocked",
    "network_error",
    "timeout",
    "too_large",
    "disallowed_mime",
    "redirect_limit_exceeded",
    "robots_disallowed",
    "robots_unavailable",
    "http_error",
)
_RETRY_CLASSIFICATIONS = ("not_applicable", "retryable", "terminal")
_ROBOTS_DECISIONS = ("allowed", "disallowed", "unavailable", "not_evaluated")

_IMMUTABILITY_FUNCTION = "contentos_reject_fetch_snapshot_mutation"
_IMMUTABILITY_TRIGGER = "trg_fetch_snapshots_append_only"


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
        "fetch_snapshots",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "discovery_item_id",
            sa.Uuid(),
            sa.ForeignKey("discovery_items.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("requested_url", sa.String(length=2000), nullable=False),
        sa.Column("final_url", sa.String(length=2000), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("content_type", sa.String(length=255), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("body_sha256", sa.String(length=64), nullable=True),
        sa.Column("body_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("raw_payload_ref", sa.String(length=2000), nullable=True),
        sa.Column(
            "selected_headers",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("duration_ms", sa.Float(), nullable=False),
        sa.Column(
            "redirect_chain",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "fetch_outcome",
            _string_enum(_FETCH_OUTCOMES, "ck_fetch_snapshots_fetch_outcome", 32),
            nullable=False,
        ),
        sa.Column(
            "retry_classification",
            _string_enum(
                _RETRY_CLASSIFICATIONS,
                "ck_fetch_snapshots_retry_classification",
                16,
            ),
            nullable=False,
        ),
        sa.Column("failure_detail", sa.Text(), nullable=True),
        sa.Column(
            "robots_decision",
            _string_enum(_ROBOTS_DECISIONS, "ck_fetch_snapshots_robots_decision", 16),
            nullable=False,
        ),
        sa.Column("retry_after_seconds", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "duration_ms >= 0",
            name="ck_fetch_snapshots_duration_nonnegative",
        ),
        sa.CheckConstraint(
            "body_size_bytes IS NULL OR body_size_bytes >= 0",
            name="ck_fetch_snapshots_body_size_nonnegative",
        ),
    )
    op.create_index(
        "ix_fetch_snapshots_discovery_fetched_at",
        "fetch_snapshots",
        ["discovery_item_id", "fetched_at"],
    )
    op.create_index(
        "ix_fetch_snapshots_fetch_outcome",
        "fetch_snapshots",
        ["fetch_outcome"],
    )
    op.execute(
        sa.text(
            f"""
            CREATE FUNCTION {_IMMUTABILITY_FUNCTION}()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION 'fetch_snapshots is append-only; % is forbidden', TG_OP
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
            BEFORE UPDATE OR DELETE ON fetch_snapshots
            FOR EACH ROW
            EXECUTE FUNCTION {_IMMUTABILITY_FUNCTION}()
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text(f"DROP TRIGGER {_IMMUTABILITY_TRIGGER} ON fetch_snapshots"))
    op.execute(sa.text(f"DROP FUNCTION {_IMMUTABILITY_FUNCTION}()"))
    op.drop_index("ix_fetch_snapshots_fetch_outcome", table_name="fetch_snapshots")
    op.drop_index(
        "ix_fetch_snapshots_discovery_fetched_at",
        table_name="fetch_snapshots",
    )
    op.drop_table("fetch_snapshots")
