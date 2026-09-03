"""Add operator strategy and append-only inspiration intelligence.

Revision ID: 0029
Revises: 0028
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json() -> sa.JSON:
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "audience_strategies",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("locale", sa.String(20), nullable=False, server_default="tr-TR"),
        sa.Column("market", sa.String(2), nullable=False, server_default="TR"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("name", "locale", "market", name="uq_audience_strategies_scope"),
        sa.CheckConstraint(
            "priority >= 0 AND priority <= 100", name="ck_audience_strategies_priority"
        ),
        sa.CheckConstraint(
            "status IN ('active','paused','archived')", name="ck_audience_strategies_status"
        ),
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_audience_strategies_name_nonempty"),
    )
    op.create_index(
        "ix_audience_strategies_status_priority", "audience_strategies", ["status", "priority"]
    )
    op.create_table(
        "topic_clusters",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(200), nullable=False),
        sa.Column("locale", sa.String(20), nullable=False, server_default="tr-TR"),
        sa.Column("market", sa.String(2), nullable=False, server_default="TR"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("slug", "locale", "market", name="uq_topic_clusters_scope"),
        sa.CheckConstraint("priority >= 0 AND priority <= 100", name="ck_topic_clusters_priority"),
        sa.CheckConstraint(
            "status IN ('active','paused','archived')", name="ck_topic_clusters_status"
        ),
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_topic_clusters_name_nonempty"),
    )
    op.create_index("ix_topic_clusters_status_priority", "topic_clusters", ["status", "priority"])
    op.create_table(
        "strategic_keywords",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("phrase", sa.String(240), nullable=False),
        sa.Column("normalized_phrase", sa.String(240), nullable=False),
        sa.Column("locale", sa.String(20), nullable=False, server_default="tr-TR"),
        sa.Column("market", sa.String(2), nullable=False, server_default="TR"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column(
            "topic_cluster_id",
            sa.Uuid(),
            sa.ForeignKey("topic_clusters.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "normalized_phrase", "locale", "market", name="uq_strategic_keywords_scope"
        ),
        sa.CheckConstraint(
            "priority >= 0 AND priority <= 100", name="ck_strategic_keywords_priority"
        ),
        sa.CheckConstraint(
            "status IN ('active','paused','archived')", name="ck_strategic_keywords_status"
        ),
        sa.CheckConstraint(
            "length(trim(phrase)) > 0", name="ck_strategic_keywords_phrase_nonempty"
        ),
    )
    op.create_index(
        "ix_strategic_keywords_status_priority", "strategic_keywords", ["status", "priority"]
    )
    op.create_index("ix_strategic_keywords_cluster", "strategic_keywords", ["topic_cluster_id"])
    op.create_table(
        "inspiration_signals",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "opportunity_id",
            sa.Uuid(),
            sa.ForeignKey("editorial_opportunities.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "normalized_document_id",
            sa.Uuid(),
            sa.ForeignKey("normalized_documents.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("signal_key", sa.String(64), nullable=False),
        sa.Column("concept_key", sa.String(240), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("extraction_method", sa.String(20), nullable=False),
        sa.Column("extractor_name", sa.String(100), nullable=False),
        sa.Column("extractor_version", sa.String(100), nullable=False),
        sa.Column("source_locator", _json(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "opportunity_id",
            "normalized_document_id",
            "extractor_name",
            "extractor_version",
            "signal_key",
            name="uq_inspiration_signals_identity",
        ),
        sa.CheckConstraint(
            "length(signal_key) = 64 AND signal_key = lower(signal_key)",
            name="ck_inspiration_signals_key_format",
        ),
        sa.CheckConstraint("length(trim(title)) > 0", name="ck_inspiration_signals_title_nonempty"),
        sa.CheckConstraint(
            "extraction_method IN ('deterministic','model_assisted','operator')",
            name="ck_inspiration_signals_method",
        ),
    )
    op.create_index(
        "ix_inspiration_signals_opportunity",
        "inspiration_signals",
        ["opportunity_id", "created_at"],
    )
    op.create_index("ix_inspiration_signals_concept", "inspiration_signals", ["concept_key"])
    op.create_table(
        "inspiration_evaluations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "opportunity_id",
            sa.Uuid(),
            sa.ForeignKey("editorial_opportunities.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("engine_name", sa.String(100), nullable=False),
        sa.Column("engine_version", sa.String(100), nullable=False),
        sa.Column("inspiration_band", sa.String(16), nullable=False),
        sa.Column("search_opportunity", sa.String(16), nullable=False),
        sa.Column("trend_state", sa.String(16), nullable=False),
        sa.Column("recommendation", sa.String(20), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("factors", _json(), nullable=False),
        sa.Column("strategy_context", _json(), nullable=False),
        sa.Column("missing_signals", _json(), nullable=False),
        sa.Column("input_snapshot", _json(), nullable=False),
        sa.Column("input_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "opportunity_id",
            "engine_name",
            "engine_version",
            "input_snapshot_hash",
            name="uq_inspiration_evaluations_identity",
        ),
        sa.CheckConstraint(
            "inspiration_band IN ('high','medium','low','unknown')",
            name="ck_inspiration_evaluations_band",
        ),
        sa.CheckConstraint(
            "search_opportunity IN ('strong','moderate','weak','unknown')",
            name="ck_inspiration_evaluations_search",
        ),
        sa.CheckConstraint(
            "trend_state IN ('known','unknown')", name="ck_inspiration_evaluations_trend"
        ),
        sa.CheckConstraint(
            "recommendation IN ('produce','continue_research','eliminate','human_review')",
            name="ck_inspiration_evaluations_recommendation",
        ),
        sa.CheckConstraint(
            "length(input_snapshot_hash) = 64 AND input_snapshot_hash = lower(input_snapshot_hash)",
            name="ck_inspiration_evaluations_hash_format",
        ),
    )
    op.create_index(
        "ix_inspiration_evaluations_opportunity",
        "inspiration_evaluations",
        ["opportunity_id", "evaluated_at"],
    )
    op.create_index(
        "ix_inspiration_evaluations_recommendation", "inspiration_evaluations", ["recommendation"]
    )
    op.execute(
        sa.text(
            """
            CREATE FUNCTION contentos_reject_inspiration_mutation()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                RAISE EXCEPTION 'inspiration intelligence is append-only; % is forbidden', TG_OP
                    USING ERRCODE = '55000';
            END;
            $$
            """
        )
    )
    for trigger_name, table_name in (
        ("trg_inspiration_signals_append_only", "inspiration_signals"),
        ("trg_inspiration_evaluations_append_only", "inspiration_evaluations"),
    ):
        op.execute(
            sa.text(
                f"""
                CREATE TRIGGER {trigger_name}
                BEFORE UPDATE OR DELETE ON {table_name}
                FOR EACH ROW EXECUTE FUNCTION contentos_reject_inspiration_mutation()
                """
            )
        )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_inspiration_evaluations_append_only ON inspiration_evaluations"
    )
    op.execute("DROP TRIGGER IF EXISTS trg_inspiration_signals_append_only ON inspiration_signals")
    op.execute("DROP FUNCTION IF EXISTS contentos_reject_inspiration_mutation()")
    op.drop_index("ix_inspiration_evaluations_recommendation", table_name="inspiration_evaluations")
    op.drop_index("ix_inspiration_evaluations_opportunity", table_name="inspiration_evaluations")
    op.drop_table("inspiration_evaluations")
    op.drop_index("ix_inspiration_signals_concept", table_name="inspiration_signals")
    op.drop_index("ix_inspiration_signals_opportunity", table_name="inspiration_signals")
    op.drop_table("inspiration_signals")
    op.drop_index("ix_strategic_keywords_cluster", table_name="strategic_keywords")
    op.drop_index("ix_strategic_keywords_status_priority", table_name="strategic_keywords")
    op.drop_table("strategic_keywords")
    op.drop_index("ix_topic_clusters_status_priority", table_name="topic_clusters")
    op.drop_table("topic_clusters")
    op.drop_index("ix_audience_strategies_status_priority", table_name="audience_strategies")
    op.drop_table("audience_strategies")
