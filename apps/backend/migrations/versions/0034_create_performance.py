"""Create the performance loop tables (published contents, snapshots,
assessments, refresh opportunities, strategy suggestions).

Revision ID: 0034
Revises: 0033
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0034"
down_revision: str | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PROVIDERS = (
    "google_search_console",
    "google_analytics",
    "semrush",
    "google_trends",
    "pinterest_trends",
)
_ASSESSMENT_STATUSES = (
    "insufficient_data",
    "rising",
    "stable",
    "declining",
    "volatile",
    "unknown",
)
_REFRESH_STATUSES = ("proposed", "approved", "dismissed", "superseded")
_SUGGESTION_KINDS = ("cluster_focus", "keyword_add", "audience_focus", "theme_focus")
_SUGGESTION_STATUSES = ("proposed", "accepted", "ignored")


def _in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


_JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _timestamp(name: str, *, nullable: bool = False, default_now: bool = False) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        nullable=nullable,
        server_default=sa.func.now() if default_now else None,
    )


def upgrade() -> None:
    op.create_table(
        "published_contents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "work_item_id",
            sa.Uuid(),
            sa.ForeignKey("editorial_work_items.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "opportunity_id",
            sa.Uuid(),
            sa.ForeignKey("editorial_opportunities.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "publication_package_id",
            sa.Uuid(),
            sa.ForeignKey("publication_packages.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "publication_attempt_id",
            sa.Uuid(),
            sa.ForeignKey("publication_attempts.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("canonical_url", sa.String(length=1000), nullable=True),
        sa.Column("remote_publication_ref", sa.Text(), nullable=False),
        _timestamp("published_at"),
        sa.Column(
            "topic_cluster_id",
            sa.Uuid(),
            sa.ForeignKey("topic_clusters.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "audience_id",
            sa.Uuid(),
            sa.ForeignKey("audience_strategies.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("theme_key", sa.String(length=200), nullable=True),
        sa.Column("content_format", sa.String(length=60), nullable=True),
        _timestamp("created_at", default_now=True),
        sa.UniqueConstraint("work_item_id", name="uq_published_contents_work_item"),
        sa.CheckConstraint(
            "length(trim(remote_publication_ref)) > 0",
            name="ck_published_contents_ref_nonempty",
        ),
    )
    op.create_index("ix_published_contents_published_at", "published_contents", ["published_at"])
    op.create_index("ix_published_contents_cluster", "published_contents", ["topic_cluster_id"])

    op.create_table(
        "content_performance_snapshots",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "published_content_id",
            sa.Uuid(),
            sa.ForeignKey("published_contents.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        _timestamp("observed_at"),
        sa.Column("metrics", _JSON, nullable=False),
        sa.Column("snapshot_hash", sa.String(length=64), nullable=False),
        _timestamp("created_at", default_now=True),
        sa.UniqueConstraint("snapshot_hash", name="uq_content_performance_snapshots_hash"),
        sa.CheckConstraint(
            f"provider IN ({_in_list(_PROVIDERS)})",
            name="ck_content_performance_snapshots_provider",
        ),
        sa.CheckConstraint(
            "length(snapshot_hash) = 64 AND snapshot_hash = lower(snapshot_hash)",
            name="ck_content_performance_snapshots_hash_format",
        ),
        sa.CheckConstraint(
            "period_start <= period_end", name="ck_content_performance_snapshots_period"
        ),
    )
    op.create_index(
        "ix_content_performance_snapshots_content_provider_period",
        "content_performance_snapshots",
        ["published_content_id", "provider", "period_end"],
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION contentos_reject_snapshot_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'content_performance_snapshots rows are append-only';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_content_performance_snapshots_append_only
        BEFORE UPDATE OR DELETE ON content_performance_snapshots
        FOR EACH ROW EXECUTE FUNCTION contentos_reject_snapshot_mutation();
        """
    )

    op.create_table(
        "performance_assessments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "published_content_id",
            sa.Uuid(),
            sa.ForeignKey("published_contents.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("window_days", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("basis", _JSON, nullable=False),
        _timestamp("assessed_at"),
        sa.Column("engine_name", sa.String(length=100), nullable=False),
        sa.Column("engine_version", sa.String(length=50), nullable=False),
        _timestamp("created_at", default_now=True),
        sa.CheckConstraint("window_days IN (7, 28, 90)", name="ck_performance_assessments_window"),
        sa.CheckConstraint(
            f"status IN ({_in_list(_ASSESSMENT_STATUSES)})",
            name="ck_performance_assessments_status",
        ),
    )
    op.create_index(
        "ix_performance_assessments_content_window",
        "performance_assessments",
        ["published_content_id", "window_days", "assessed_at"],
    )
    op.execute(
        """
        CREATE TRIGGER trg_performance_assessments_append_only
        BEFORE UPDATE OR DELETE ON performance_assessments
        FOR EACH ROW EXECUTE FUNCTION contentos_reject_snapshot_mutation();
        """
    )

    op.create_table(
        "refresh_opportunities",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "published_content_id",
            sa.Uuid(),
            sa.ForeignKey("published_contents.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "trigger_assessment_id",
            sa.Uuid(),
            sa.ForeignKey("performance_assessments.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("diagnosis", _JSON, nullable=False),
        sa.Column("recommendation", sa.Text(), nullable=False),
        _timestamp("proposed_at"),
        _timestamp("decided_at", nullable=True),
        sa.Column(
            "decided_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        _timestamp("created_at", default_now=True),
        sa.CheckConstraint(
            f"status IN ({_in_list(_REFRESH_STATUSES)})",
            name="ck_refresh_opportunities_status",
        ),
        sa.CheckConstraint(
            "length(trim(recommendation)) > 0",
            name="ck_refresh_opportunities_recommendation_nonempty",
        ),
        sa.CheckConstraint(
            "(status = 'proposed') OR (decided_at IS NOT NULL)",
            name="ck_refresh_opportunities_decided",
        ),
    )
    op.create_index(
        "ix_refresh_opportunities_content_status",
        "refresh_opportunities",
        ["published_content_id", "status"],
    )
    op.create_index(
        "ix_refresh_opportunities_status", "refresh_opportunities", ["status", "proposed_at"]
    )
    # One OPEN proposal per published content (enforced in the service too).
    op.create_index(
        "uq_refresh_opportunities_open",
        "refresh_opportunities",
        ["published_content_id"],
        unique=True,
        postgresql_where=sa.text("status = 'proposed'"),
    )

    op.create_table(
        "strategy_suggestions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("basis", _JSON, nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        _timestamp("proposed_at"),
        _timestamp("decided_at", nullable=True),
        sa.Column(
            "decided_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("suggestion_hash", sa.String(length=64), nullable=False),
        _timestamp("created_at", default_now=True),
        sa.UniqueConstraint("suggestion_hash", name="uq_strategy_suggestions_hash"),
        sa.CheckConstraint(
            f"kind IN ({_in_list(_SUGGESTION_KINDS)})", name="ck_strategy_suggestions_kind"
        ),
        sa.CheckConstraint(
            f"status IN ({_in_list(_SUGGESTION_STATUSES)})",
            name="ck_strategy_suggestions_status",
        ),
        sa.CheckConstraint(
            "length(suggestion_hash) = 64 AND suggestion_hash = lower(suggestion_hash)",
            name="ck_strategy_suggestions_hash_format",
        ),
        sa.CheckConstraint(
            "length(trim(title)) > 0", name="ck_strategy_suggestions_title_nonempty"
        ),
        sa.CheckConstraint(
            "(status = 'proposed') OR (decided_at IS NOT NULL)",
            name="ck_strategy_suggestions_decided",
        ),
    )
    op.create_index(
        "ix_strategy_suggestions_status", "strategy_suggestions", ["status", "proposed_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_strategy_suggestions_status", table_name="strategy_suggestions")
    op.drop_table("strategy_suggestions")
    op.drop_index("uq_refresh_opportunities_open", table_name="refresh_opportunities")
    op.drop_index("ix_refresh_opportunities_status", table_name="refresh_opportunities")
    op.drop_index("ix_refresh_opportunities_content_status", table_name="refresh_opportunities")
    op.drop_table("refresh_opportunities")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_performance_assessments_append_only ON performance_assessments"
    )
    op.drop_index("ix_performance_assessments_content_window", table_name="performance_assessments")
    op.drop_table("performance_assessments")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_content_performance_snapshots_append_only "
        "ON content_performance_snapshots"
    )
    op.drop_index(
        "ix_content_performance_snapshots_content_provider_period",
        table_name="content_performance_snapshots",
    )
    op.drop_table("content_performance_snapshots")
    op.execute("DROP FUNCTION IF EXISTS contentos_reject_snapshot_mutation()")
    op.drop_index("ix_published_contents_cluster", table_name="published_contents")
    op.drop_index("ix_published_contents_published_at", table_name="published_contents")
    op.drop_table("published_contents")
