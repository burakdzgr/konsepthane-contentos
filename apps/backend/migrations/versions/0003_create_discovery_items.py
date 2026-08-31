"""Create the discovery_items table.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen literal enum values; this migration must not change if the
# application enums evolve later.
_LIFECYCLE_STATES = ("discovered", "accepted", "rejected", "fetched", "fetch_failed")
_DISCOVERY_METHODS = ("manual", "feed", "sitemap", "provider", "search")
_REJECTION_REASONS = (
    "out_of_scope",
    "duplicate_url",
    "source_not_active",
    "policy",
    "invalid_url",
    "unsupported_scheme",
)


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
        "discovery_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "source_id",
            sa.Uuid(),
            sa.ForeignKey("sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("discovered_url", sa.String(length=2000), nullable=False),
        sa.Column("canonical_url", sa.String(length=2000), nullable=False),
        sa.Column("url_hash", sa.String(length=64), nullable=False),
        sa.Column("url_canonicalization_version", sa.Integer(), nullable=False),
        sa.Column(
            "discovery_method",
            _string_enum(_DISCOVERY_METHODS, "ck_discovery_items_discovery_method", 16),
            nullable=False,
        ),
        sa.Column("title_hint", sa.String(length=500), nullable=True),
        sa.Column("snippet_hint", sa.Text(), nullable=True),
        sa.Column("locale", sa.String(length=20), nullable=False),
        sa.Column("external_published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "lifecycle_state",
            _string_enum(_LIFECYCLE_STATES, "ck_discovery_items_lifecycle_state", 16),
            nullable=False,
        ),
        sa.Column(
            "rejection_reason",
            _string_enum(_REJECTION_REASONS, "ck_discovery_items_rejection_reason", 20),
            nullable=True,
        ),
        sa.Column("rejection_note", sa.Text(), nullable=True),
        sa.Column(
            "discovered_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("source_id", "url_hash", name="uq_discovery_items_source_url_hash"),
    )
    op.create_index("ix_discovery_items_lifecycle_state", "discovery_items", ["lifecycle_state"])
    op.create_index("ix_discovery_items_url_hash", "discovery_items", ["url_hash"])
    op.create_index("ix_discovery_items_discovered_at", "discovery_items", ["discovered_at"])


def downgrade() -> None:
    # Removes only objects introduced by 0003; sources (0002) and pgvector
    # (0001) are untouched.
    op.drop_index("ix_discovery_items_discovered_at", table_name="discovery_items")
    op.drop_index("ix_discovery_items_url_hash", table_name="discovery_items")
    op.drop_index("ix_discovery_items_lifecycle_state", table_name="discovery_items")
    op.drop_table("discovery_items")
