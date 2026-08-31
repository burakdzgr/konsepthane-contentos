"""Create the Source Registry tables.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Enum values are frozen literals on purpose: this migration must not change
# if the application enums evolve later.
_SOURCE_KINDS = (
    "editorial_site",
    "competitor_site",
    "rss_feed",
    "sitemap",
    "manual",
    "trend_provider",
    "search_provider",
)
_LIFECYCLE_STATES = ("active", "paused", "disabled", "blocked")
_TRUST_TIERS = ("official", "expert", "reputable", "general", "reference_only")
_DISCOVERY_STRATEGIES = ("feed", "sitemap", "manual", "provider")
_ROBOTS_POLICIES = ("obey",)
_LIFECYCLE_ORIGINS = ("operator", "system")


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
        "sources",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("kind", _string_enum(_SOURCE_KINDS, "ck_sources_kind", 32), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=False),
        sa.Column("locale", sa.String(length=20), nullable=False),
        sa.Column("market", sa.String(length=2), nullable=False),
        sa.Column(
            "lifecycle_state",
            _string_enum(_LIFECYCLE_STATES, "ck_sources_lifecycle_state", 16),
            nullable=False,
        ),
        sa.Column("state_reason", sa.Text(), nullable=True),
        sa.Column("state_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "trust_tier",
            _string_enum(_TRUST_TIERS, "ck_sources_trust_tier", 20),
            nullable=False,
        ),
        sa.Column(
            "discovery_strategy",
            _string_enum(_DISCOVERY_STRATEGIES, "ck_sources_discovery_strategy", 16),
            nullable=False,
        ),
        sa.Column(
            "discovery_config",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "fetch_policy",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "robots_policy",
            _string_enum(_ROBOTS_POLICIES, "ck_sources_robots_policy", 8),
            nullable=False,
        ),
        sa.Column("terms_notes", sa.Text(), nullable=True),
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
        sa.UniqueConstraint("slug", name="uq_sources_slug"),
        sa.UniqueConstraint("kind", "base_url", name="uq_sources_kind_base_url"),
    )
    op.create_index("ix_sources_lifecycle_state", "sources", ["lifecycle_state"])
    op.create_index("ix_sources_kind", "sources", ["kind"])

    op.create_table(
        "source_lifecycle_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column(
            "source_id",
            sa.Uuid(),
            sa.ForeignKey("sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "previous_state",
            _string_enum(_LIFECYCLE_STATES, "ck_source_lifecycle_events_previous_state", 16),
            nullable=True,
        ),
        sa.Column(
            "new_state",
            _string_enum(_LIFECYCLE_STATES, "ck_source_lifecycle_events_new_state", 16),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "origin",
            _string_enum(_LIFECYCLE_ORIGINS, "ck_source_lifecycle_events_origin", 16),
            nullable=False,
        ),
        sa.Column(
            "changed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_source_lifecycle_events_source_id",
        "source_lifecycle_events",
        ["source_id", "changed_at"],
    )


def downgrade() -> None:
    # Removes only objects introduced by 0002; pgvector (0001) is untouched.
    op.drop_index("ix_source_lifecycle_events_source_id", table_name="source_lifecycle_events")
    op.drop_table("source_lifecycle_events")
    op.drop_index("ix_sources_kind", table_name="sources")
    op.drop_index("ix_sources_lifecycle_state", table_name="sources")
    op.drop_table("sources")
