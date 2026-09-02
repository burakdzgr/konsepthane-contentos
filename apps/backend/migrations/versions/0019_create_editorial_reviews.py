"""Create editorial reviews, findings, status audit; add editor purpose.

Revision ID: 0019
Revises: 0018
Create Date: 2026-09-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen literal vocabularies (never import app enums).
_VERDICTS = ("pass", "revise")
_STATUSES = ("active", "superseded")
_ACTORS = ("operator", "system")
_DIMENSIONS = (
    "claim_faithfulness",
    "exclusion_compliance",
    "objective_fit",
    "clarity_style",
    "uncertainty_framing",
)
_SEVERITIES = ("blocking", "major", "minor")
_ORIGINS = ("model_signal", "deterministic")

_OLD_PURPOSES = (
    "idea_candidates",
    "intent_synthesis",
    "brief_composition",
    "evidence_organization",
    "writer_draft",
)
_NEW_PURPOSES = (*_OLD_PURPOSES, "editor_review")
_PURPOSE_CONSTRAINT = "ck_ai_generation_attempts_purpose"

_REVIEW_FUNCTION = "contentos_guard_editorial_review_mutation"
_REVIEW_TRIGGER = "trg_editorial_reviews_guarded"
_FINDING_FUNCTION = "contentos_reject_editorial_review_finding_mutation"
_FINDING_TRIGGER = "trg_editorial_review_findings_append_only"
_EVENT_FUNCTION = "contentos_reject_editorial_review_status_event_mutation"
_EVENT_TRIGGER = "trg_editorial_review_status_events_append_only"


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
    # Widen the attempt purpose vocabulary with the Editor purpose.
    op.drop_constraint(_PURPOSE_CONSTRAINT, "ai_generation_attempts", type_="check")
    op.create_check_constraint(
        _PURPOSE_CONSTRAINT, "ai_generation_attempts", _purpose_in(_NEW_PURPOSES)
    )

    op.create_table(
        "editorial_reviews",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "work_item_id",
            sa.Uuid(),
            sa.ForeignKey("editorial_work_items.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "content_draft_id",
            sa.Uuid(),
            sa.ForeignKey("content_drafts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "content_brief_id",
            sa.Uuid(),
            sa.ForeignKey("content_briefs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "verdict",
            _string_enum(_VERDICTS, "ck_editorial_reviews_verdict", 16),
            nullable=False,
        ),
        sa.Column(
            "generation_attempt_id",
            sa.Uuid(),
            sa.ForeignKey("ai_generation_attempts.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("engine_name", sa.String(length=100), nullable=False),
        sa.Column("engine_version", sa.String(length=50), nullable=False),
        sa.Column(
            "integrity_gate_result",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "verdict_policy_snapshot",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "review_scope",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "status",
            _string_enum(_STATUSES, "ck_editorial_reviews_status", 16),
            nullable=False,
        ),
        sa.Column(
            "superseded_by_review_id",
            sa.Uuid(),
            sa.ForeignKey("editorial_reviews.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("work_item_id", "version", name="uq_editorial_reviews_version"),
        sa.UniqueConstraint("generation_attempt_id", name="uq_editorial_reviews_attempt"),
        sa.CheckConstraint("version > 0", name="ck_editorial_reviews_version_positive"),
        sa.CheckConstraint(
            "length(trim(engine_name)) > 0", name="ck_editorial_reviews_engine_name_nonempty"
        ),
        sa.CheckConstraint(
            "length(trim(engine_version)) > 0",
            name="ck_editorial_reviews_engine_version_nonempty",
        ),
        sa.CheckConstraint(
            "length(content_hash) = 64 AND content_hash = lower(content_hash)",
            name="ck_editorial_reviews_hash_format",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(integrity_gate_result) = 'object'",
            name="ck_editorial_reviews_integrity_object",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(review_scope) = 'object'",
            name="ck_editorial_reviews_scope_object",
        ),
    )
    op.create_index(
        "ix_editorial_reviews_work_item", "editorial_reviews", ["work_item_id", "version"]
    )
    op.create_index("ix_editorial_reviews_draft", "editorial_reviews", ["content_draft_id"])
    op.create_index(
        "uq_editorial_reviews_active",
        "editorial_reviews",
        ["work_item_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "editorial_review_findings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "review_id",
            sa.Uuid(),
            sa.ForeignKey("editorial_reviews.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("finding_key", sa.String(length=64), nullable=False),
        sa.Column(
            "dimension",
            _string_enum(_DIMENSIONS, "ck_editorial_review_findings_dimension", 24),
            nullable=False,
        ),
        sa.Column(
            "severity",
            _string_enum(_SEVERITIES, "ck_editorial_review_findings_severity", 16),
            nullable=False,
        ),
        sa.Column(
            "origin",
            _string_enum(_ORIGINS, "ck_editorial_review_findings_origin", 16),
            nullable=False,
        ),
        sa.Column("block_id", sa.String(length=64), nullable=True),
        sa.Column(
            "brief_claim_id",
            sa.Uuid(),
            sa.ForeignKey("brief_claims.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("recommendation", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("review_id", "finding_key", name="uq_editorial_review_findings_key"),
        sa.CheckConstraint(
            "length(trim(finding_key)) > 0", name="ck_editorial_review_findings_key_nonempty"
        ),
        sa.CheckConstraint(
            "length(trim(description)) > 0",
            name="ck_editorial_review_findings_description_nonempty",
        ),
        sa.CheckConstraint(
            "block_id IS NULL OR length(trim(block_id)) > 0",
            name="ck_editorial_review_findings_block_nonempty",
        ),
    )
    op.create_index(
        "ix_editorial_review_findings_review", "editorial_review_findings", ["review_id"]
    )
    op.create_index(
        "ix_editorial_review_findings_claim", "editorial_review_findings", ["brief_claim_id"]
    )

    op.create_table(
        "editorial_review_status_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "review_id",
            sa.Uuid(),
            sa.ForeignKey("editorial_reviews.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "from_status",
            _string_enum(_STATUSES, "ck_editorial_review_status_events_from", 16),
            nullable=False,
        ),
        sa.Column(
            "to_status",
            _string_enum(_STATUSES, "ck_editorial_review_status_events_to", 16),
            nullable=False,
        ),
        sa.Column(
            "actor_origin",
            _string_enum(_ACTORS, "ck_editorial_review_status_events_actor", 16),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column(
            "replacement_review_id",
            sa.Uuid(),
            sa.ForeignKey("editorial_reviews.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(trim(reason)) > 0", name="ck_editorial_review_status_events_reason_nonempty"
        ),
        sa.CheckConstraint(
            "request_id IS NULL OR length(trim(request_id)) > 0",
            name="ck_editorial_review_status_events_request_id_nonempty",
        ),
    )
    op.create_index(
        "ix_editorial_review_status_events_review",
        "editorial_review_status_events",
        ["review_id", "id"],
    )

    # Editorial reviews: DELETE forbidden; UPDATE may ONLY move status
    # forward (active -> superseded) while setting superseded_by_review_id
    # once (the proven two-shape rule from 0018).
    op.execute(
        sa.text(
            f"""
            CREATE FUNCTION {_REVIEW_FUNCTION}()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    RAISE EXCEPTION 'editorial_reviews rows cannot be deleted'
                        USING ERRCODE = '55000';
                END IF;
                IF NEW.id IS DISTINCT FROM OLD.id
                   OR NEW.work_item_id IS DISTINCT FROM OLD.work_item_id
                   OR NEW.content_draft_id IS DISTINCT FROM OLD.content_draft_id
                   OR NEW.content_brief_id IS DISTINCT FROM OLD.content_brief_id
                   OR NEW.version IS DISTINCT FROM OLD.version
                   OR NEW.verdict IS DISTINCT FROM OLD.verdict
                   OR NEW.generation_attempt_id IS DISTINCT FROM OLD.generation_attempt_id
                   OR NEW.engine_name IS DISTINCT FROM OLD.engine_name
                   OR NEW.engine_version IS DISTINCT FROM OLD.engine_version
                   OR NEW.integrity_gate_result IS DISTINCT FROM OLD.integrity_gate_result
                   OR NEW.verdict_policy_snapshot IS DISTINCT FROM OLD.verdict_policy_snapshot
                   OR NEW.review_scope IS DISTINCT FROM OLD.review_scope
                   OR NEW.content_hash IS DISTINCT FROM OLD.content_hash
                   OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                    RAISE EXCEPTION 'editorial_reviews content fields are immutable'
                        USING ERRCODE = '55000';
                END IF;
                IF NOT (
                    (
                        OLD.status = 'active'
                        AND NEW.status = 'superseded'
                        AND OLD.superseded_by_review_id IS NULL
                    )
                    OR (
                        OLD.status = 'superseded'
                        AND NEW.status = 'superseded'
                        AND OLD.superseded_by_review_id IS NULL
                        AND NEW.superseded_by_review_id IS NOT NULL
                    )
                ) THEN
                    RAISE EXCEPTION
                        'editorial_reviews status transition % -> % is forbidden',
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
            CREATE TRIGGER {_REVIEW_TRIGGER}
            BEFORE UPDATE OR DELETE ON editorial_reviews
            FOR EACH ROW
            EXECUTE FUNCTION {_REVIEW_FUNCTION}()
            """
        )
    )

    for function_name, trigger_name, table_name in (
        (_FINDING_FUNCTION, _FINDING_TRIGGER, "editorial_review_findings"),
        (_EVENT_FUNCTION, _EVENT_TRIGGER, "editorial_review_status_events"),
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
    op.execute(sa.text(f"DROP TRIGGER {_EVENT_TRIGGER} ON editorial_review_status_events"))
    op.execute(sa.text(f"DROP FUNCTION {_EVENT_FUNCTION}()"))
    op.execute(sa.text(f"DROP TRIGGER {_FINDING_TRIGGER} ON editorial_review_findings"))
    op.execute(sa.text(f"DROP FUNCTION {_FINDING_FUNCTION}()"))
    op.execute(sa.text(f"DROP TRIGGER {_REVIEW_TRIGGER} ON editorial_reviews"))
    op.execute(sa.text(f"DROP FUNCTION {_REVIEW_FUNCTION}()"))
    op.drop_index(
        "ix_editorial_review_status_events_review", table_name="editorial_review_status_events"
    )
    op.drop_table("editorial_review_status_events")
    op.drop_index("ix_editorial_review_findings_claim", table_name="editorial_review_findings")
    op.drop_index("ix_editorial_review_findings_review", table_name="editorial_review_findings")
    op.drop_table("editorial_review_findings")
    op.drop_index("uq_editorial_reviews_active", table_name="editorial_reviews")
    op.drop_index("ix_editorial_reviews_draft", table_name="editorial_reviews")
    op.drop_index("ix_editorial_reviews_work_item", table_name="editorial_reviews")
    op.drop_table("editorial_reviews")

    # Never destroy audit rows to satisfy a narrower constraint: refuse the
    # downgrade while editor_review attempts exist.
    editor_attempts = (
        op.get_bind()
        .execute(
            sa.text("SELECT count(*) FROM ai_generation_attempts WHERE purpose = 'editor_review'")
        )
        .scalar()
    )
    if editor_attempts:
        raise RuntimeError(
            "cannot downgrade 0019: ai_generation_attempts contains "
            f"{editor_attempts} editor_review attempt(s); refusing to destroy "
            "or invalidate audit history"
        )
    op.drop_constraint(_PURPOSE_CONSTRAINT, "ai_generation_attempts", type_="check")
    op.create_check_constraint(
        _PURPOSE_CONSTRAINT, "ai_generation_attempts", _purpose_in(_OLD_PURPOSES)
    )
