"""Create content drafts, claim usages, status audit; add writer purpose.

Revision ID: 0018
Revises: 0017
Create Date: 2026-09-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen literal vocabularies (never import app enums).
_ORIGINS = ("writer_engine", "operator")
_STATUSES = ("active", "superseded")
_ACTORS = ("operator", "system")

_OLD_PURPOSES = (
    "idea_candidates",
    "intent_synthesis",
    "brief_composition",
    "evidence_organization",
)
_NEW_PURPOSES = (*_OLD_PURPOSES, "writer_draft")
_PURPOSE_CONSTRAINT = "ck_ai_generation_attempts_purpose"

_DRAFT_FUNCTION = "contentos_guard_content_draft_mutation"
_DRAFT_TRIGGER = "trg_content_drafts_guarded"
_USAGE_FUNCTION = "contentos_reject_draft_claim_usage_mutation"
_USAGE_TRIGGER = "trg_draft_claim_usages_append_only"
_EVENT_FUNCTION = "contentos_reject_draft_status_event_mutation"
_EVENT_TRIGGER = "trg_draft_status_events_append_only"


def _string_enum(values: tuple[str, ...], constraint_name: str, length: int) -> sa.Enum:
    return sa.Enum(
        *values,
        name=constraint_name,
        native_enum=False,
        create_constraint=True,
        length=length,
    )


def _purpose_in(values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"purpose IN ({quoted})"


def upgrade() -> None:
    # Widen the attempt purpose vocabulary with the Writer purpose.
    op.drop_constraint(_PURPOSE_CONSTRAINT, "ai_generation_attempts", type_="check")
    op.create_check_constraint(
        _PURPOSE_CONSTRAINT, "ai_generation_attempts", _purpose_in(_NEW_PURPOSES)
    )

    op.create_table(
        "content_drafts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "work_item_id",
            sa.Uuid(),
            sa.ForeignKey("editorial_work_items.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "content_brief_id",
            sa.Uuid(),
            sa.ForeignKey("content_briefs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("locale", sa.String(length=20), nullable=False),
        sa.Column("market", sa.String(length=2), nullable=False),
        sa.Column(
            "origin",
            _string_enum(_ORIGINS, "ck_content_drafts_origin", 16),
            nullable=False,
        ),
        sa.Column(
            "generation_attempt_id",
            sa.Uuid(),
            sa.ForeignKey("ai_generation_attempts.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("manual_input_hash", sa.String(length=64), nullable=True),
        sa.Column("engine_name", sa.String(length=100), nullable=False),
        sa.Column("engine_version", sa.String(length=50), nullable=False),
        sa.Column("title_proposal", sa.Text(), nullable=True),
        sa.Column("body", postgresql.JSONB(), nullable=False),
        sa.Column("body_schema_version", sa.String(length=50), nullable=False),
        sa.Column(
            "uncertainty_coverage",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "validation_policy_snapshot",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "originality_policy_snapshot",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "originality_result",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "status",
            _string_enum(_STATUSES, "ck_content_drafts_status", 16),
            nullable=False,
        ),
        sa.Column(
            "superseded_by_draft_id",
            sa.Uuid(),
            sa.ForeignKey("content_drafts.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("work_item_id", "version", name="uq_content_drafts_version"),
        sa.UniqueConstraint("generation_attempt_id", name="uq_content_drafts_attempt"),
        sa.CheckConstraint("version > 0", name="ck_content_drafts_version_positive"),
        sa.CheckConstraint(
            "(origin = 'operator') = (generation_attempt_id IS NULL)",
            name="ck_content_drafts_operator_attempt",
        ),
        sa.CheckConstraint(
            "(origin = 'operator') = (manual_input_hash IS NOT NULL)",
            name="ck_content_drafts_manual_hash_origin",
        ),
        sa.CheckConstraint("length(trim(locale)) > 0", name="ck_content_drafts_locale_nonempty"),
        sa.CheckConstraint("length(trim(market)) = 2", name="ck_content_drafts_market_length"),
        sa.CheckConstraint(
            "length(trim(engine_name)) > 0", name="ck_content_drafts_engine_name_nonempty"
        ),
        sa.CheckConstraint(
            "length(trim(engine_version)) > 0",
            name="ck_content_drafts_engine_version_nonempty",
        ),
        sa.CheckConstraint(
            "length(content_hash) = 64 AND content_hash = lower(content_hash)",
            name="ck_content_drafts_hash_format",
        ),
        sa.CheckConstraint(
            "manual_input_hash IS NULL OR "
            "(length(manual_input_hash) = 64 AND manual_input_hash = lower(manual_input_hash))",
            name="ck_content_drafts_manual_hash_format",
        ),
        sa.CheckConstraint("jsonb_typeof(body) = 'object'", name="ck_content_drafts_body_object"),
        sa.CheckConstraint(
            "jsonb_typeof(uncertainty_coverage) = 'object'",
            name="ck_content_drafts_coverage_object",
        ),
    )
    op.create_index("ix_content_drafts_work_item", "content_drafts", ["work_item_id", "version"])
    op.create_index("ix_content_drafts_brief", "content_drafts", ["content_brief_id"])
    op.create_index(
        "uq_content_drafts_active",
        "content_drafts",
        ["work_item_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "uq_content_drafts_manual_identity",
        "content_drafts",
        ["work_item_id", "manual_input_hash"],
        unique=True,
        postgresql_where=sa.text("origin = 'operator'"),
    )

    op.create_table(
        "draft_claim_usages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "draft_id",
            sa.Uuid(),
            sa.ForeignKey("content_drafts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "brief_claim_id",
            sa.Uuid(),
            sa.ForeignKey("brief_claims.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("section_key", sa.String(length=50), nullable=False),
        sa.Column("block_id", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "draft_id", "brief_claim_id", "block_id", name="uq_draft_claim_usages_anchor"
        ),
        sa.CheckConstraint(
            "length(trim(section_key)) > 0", name="ck_draft_claim_usages_section_nonempty"
        ),
        sa.CheckConstraint(
            "length(trim(block_id)) > 0", name="ck_draft_claim_usages_block_nonempty"
        ),
    )
    op.create_index("ix_draft_claim_usages_draft", "draft_claim_usages", ["draft_id"])
    op.create_index("ix_draft_claim_usages_claim", "draft_claim_usages", ["brief_claim_id"])

    op.create_table(
        "draft_status_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "draft_id",
            sa.Uuid(),
            sa.ForeignKey("content_drafts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "from_status",
            _string_enum(_STATUSES, "ck_draft_status_events_from", 16),
            nullable=False,
        ),
        sa.Column(
            "to_status",
            _string_enum(_STATUSES, "ck_draft_status_events_to", 16),
            nullable=False,
        ),
        sa.Column(
            "actor_origin",
            _string_enum(_ACTORS, "ck_draft_status_events_actor", 16),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column(
            "replacement_draft_id",
            sa.Uuid(),
            sa.ForeignKey("content_drafts.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(trim(reason)) > 0", name="ck_draft_status_events_reason_nonempty"
        ),
        sa.CheckConstraint(
            "request_id IS NULL OR length(trim(request_id)) > 0",
            name="ck_draft_status_events_request_id_nonempty",
        ),
    )
    op.create_index("ix_draft_status_events_draft", "draft_status_events", ["draft_id", "id"])

    # Content drafts: DELETE forbidden; UPDATE may ONLY move status forward
    # (active -> superseded) while setting superseded_by_draft_id once.
    op.execute(
        sa.text(
            f"""
            CREATE FUNCTION {_DRAFT_FUNCTION}()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    RAISE EXCEPTION 'content_drafts rows cannot be deleted'
                        USING ERRCODE = '55000';
                END IF;
                IF NEW.id IS DISTINCT FROM OLD.id
                   OR NEW.work_item_id IS DISTINCT FROM OLD.work_item_id
                   OR NEW.content_brief_id IS DISTINCT FROM OLD.content_brief_id
                   OR NEW.version IS DISTINCT FROM OLD.version
                   OR NEW.locale IS DISTINCT FROM OLD.locale
                   OR NEW.market IS DISTINCT FROM OLD.market
                   OR NEW.origin IS DISTINCT FROM OLD.origin
                   OR NEW.generation_attempt_id IS DISTINCT FROM OLD.generation_attempt_id
                   OR NEW.manual_input_hash IS DISTINCT FROM OLD.manual_input_hash
                   OR NEW.engine_name IS DISTINCT FROM OLD.engine_name
                   OR NEW.engine_version IS DISTINCT FROM OLD.engine_version
                   OR NEW.title_proposal IS DISTINCT FROM OLD.title_proposal
                   OR NEW.body IS DISTINCT FROM OLD.body
                   OR NEW.body_schema_version IS DISTINCT FROM OLD.body_schema_version
                   OR NEW.uncertainty_coverage IS DISTINCT FROM OLD.uncertainty_coverage
                   OR NEW.validation_policy_snapshot IS DISTINCT FROM OLD.validation_policy_snapshot
                   OR NEW.originality_policy_snapshot IS DISTINCT FROM OLD.originality_policy_snapshot
                   OR NEW.originality_result IS DISTINCT FROM OLD.originality_result
                   OR NEW.content_hash IS DISTINCT FROM OLD.content_hash
                   OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                    RAISE EXCEPTION 'content_drafts content fields are immutable'
                        USING ERRCODE = '55000';
                END IF;
                -- Two legal update shapes (both used inside one service
                -- transaction): (1) forward-only status change
                -- active -> superseded, (2) one-shot replacement-pointer
                -- set on an already-superseded row. Everything else is
                -- forbidden.
                IF NOT (
                    (
                        OLD.status = 'active'
                        AND NEW.status = 'superseded'
                        AND OLD.superseded_by_draft_id IS NULL
                    )
                    OR (
                        OLD.status = 'superseded'
                        AND NEW.status = 'superseded'
                        AND OLD.superseded_by_draft_id IS NULL
                        AND NEW.superseded_by_draft_id IS NOT NULL
                    )
                ) THEN
                    RAISE EXCEPTION
                        'content_drafts status transition % -> % is forbidden',
                        OLD.status, NEW.status
                        USING ERRCODE = '55000';
                END IF;
                RETURN NEW;
            END;
            $$
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            CREATE TRIGGER {_DRAFT_TRIGGER}
            BEFORE UPDATE OR DELETE ON content_drafts
            FOR EACH ROW
            EXECUTE FUNCTION {_DRAFT_FUNCTION}()
            """
        )
    )

    for function_name, trigger_name, table_name in (
        (_USAGE_FUNCTION, _USAGE_TRIGGER, "draft_claim_usages"),
        (_EVENT_FUNCTION, _EVENT_TRIGGER, "draft_status_events"),
    ):
        op.execute(
            sa.text(
                f"""
                CREATE FUNCTION {function_name}()
                RETURNS trigger
                LANGUAGE plpgsql
                AS $$
                BEGIN
                    RAISE EXCEPTION
                        '{table_name} is append-only; % is forbidden', TG_OP
                        USING ERRCODE = '55000';
                END;
                $$
                """
            )
        )
        op.execute(
            sa.text(
                f"""
                CREATE TRIGGER {trigger_name}
                BEFORE UPDATE OR DELETE ON {table_name}
                FOR EACH ROW
                EXECUTE FUNCTION {function_name}()
                """
            )
        )


def downgrade() -> None:
    op.execute(sa.text(f"DROP TRIGGER {_EVENT_TRIGGER} ON draft_status_events"))
    op.execute(sa.text(f"DROP FUNCTION {_EVENT_FUNCTION}()"))
    op.execute(sa.text(f"DROP TRIGGER {_USAGE_TRIGGER} ON draft_claim_usages"))
    op.execute(sa.text(f"DROP FUNCTION {_USAGE_FUNCTION}()"))
    op.execute(sa.text(f"DROP TRIGGER {_DRAFT_TRIGGER} ON content_drafts"))
    op.execute(sa.text(f"DROP FUNCTION {_DRAFT_FUNCTION}()"))
    op.drop_index("ix_draft_status_events_draft", table_name="draft_status_events")
    op.drop_table("draft_status_events")
    op.drop_index("ix_draft_claim_usages_claim", table_name="draft_claim_usages")
    op.drop_index("ix_draft_claim_usages_draft", table_name="draft_claim_usages")
    op.drop_table("draft_claim_usages")
    op.drop_index("uq_content_drafts_manual_identity", table_name="content_drafts")
    op.drop_index("uq_content_drafts_active", table_name="content_drafts")
    op.drop_index("ix_content_drafts_brief", table_name="content_drafts")
    op.drop_index("ix_content_drafts_work_item", table_name="content_drafts")
    op.drop_table("content_drafts")

    # Never destroy audit rows to satisfy a narrower constraint: refuse the
    # downgrade while writer_draft attempts exist.
    writer_attempts = (
        op.get_bind()
        .execute(
            sa.text("SELECT count(*) FROM ai_generation_attempts WHERE purpose = 'writer_draft'")
        )
        .scalar()
    )
    if writer_attempts:
        raise RuntimeError(
            "cannot downgrade 0018: ai_generation_attempts contains "
            f"{writer_attempts} writer_draft attempt(s); refusing to destroy "
            "or invalidate audit history"
        )
    op.drop_constraint(_PURPOSE_CONSTRAINT, "ai_generation_attempts", type_="check")
    op.create_check_constraint(
        _PURPOSE_CONSTRAINT, "ai_generation_attempts", _purpose_in(_OLD_PURPOSES)
    )
