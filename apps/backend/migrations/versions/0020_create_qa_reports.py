"""Create QA reports, gate waivers, status audit.

Revision ID: 0020
Revises: 0019
Create Date: 2026-09-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen literal vocabularies (never import app enums).
_OUTCOMES = ("ready_for_human_review", "not_ready")
_STATUSES = ("active", "superseded")
_ACTORS = ("operator", "system")
_WAIVABLE_GATES = ("media_needs",)

_REPORT_FUNCTION = "contentos_guard_qa_report_mutation"
_REPORT_TRIGGER = "trg_qa_reports_guarded"
_WAIVER_FUNCTION = "contentos_reject_qa_gate_waiver_mutation"
_WAIVER_TRIGGER = "trg_qa_gate_waivers_append_only"
_EVENT_FUNCTION = "contentos_reject_qa_report_status_event_mutation"
_EVENT_TRIGGER = "trg_qa_report_status_events_append_only"


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
        "qa_reports",
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
            "editorial_review_id",
            sa.Uuid(),
            sa.ForeignKey("editorial_reviews.id", ondelete="RESTRICT"),
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
            "outcome",
            _string_enum(_OUTCOMES, "ck_qa_reports_outcome", 32),
            nullable=False,
        ),
        sa.Column(
            "gate_results",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "gate_policy_snapshot",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("engine_name", sa.String(length=100), nullable=False),
        sa.Column("engine_version", sa.String(length=50), nullable=False),
        sa.Column(
            "status",
            _string_enum(_STATUSES, "ck_qa_reports_status", 16),
            nullable=False,
        ),
        sa.Column(
            "superseded_by_report_id",
            sa.Uuid(),
            sa.ForeignKey("qa_reports.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("work_item_id", "version", name="uq_qa_reports_version"),
        sa.CheckConstraint("version > 0", name="ck_qa_reports_version_positive"),
        sa.CheckConstraint(
            "length(trim(engine_name)) > 0", name="ck_qa_reports_engine_name_nonempty"
        ),
        sa.CheckConstraint(
            "length(trim(engine_version)) > 0", name="ck_qa_reports_engine_version_nonempty"
        ),
        sa.CheckConstraint(
            "length(content_hash) = 64 AND content_hash = lower(content_hash)",
            name="ck_qa_reports_hash_format",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(gate_results) = 'object'",
            name="ck_qa_reports_gate_results_object",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(gate_policy_snapshot) = 'object'",
            name="ck_qa_reports_policy_object",
        ),
    )
    op.create_index("ix_qa_reports_work_item", "qa_reports", ["work_item_id", "version"])
    op.create_index("ix_qa_reports_draft", "qa_reports", ["content_draft_id"])
    op.create_index(
        "uq_qa_reports_active",
        "qa_reports",
        ["work_item_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "qa_gate_waivers",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "work_item_id",
            sa.Uuid(),
            sa.ForeignKey("editorial_work_items.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "gate_key",
            _string_enum(_WAIVABLE_GATES, "ck_qa_gate_waivers_key", 24),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("length(trim(reason)) > 0", name="ck_qa_gate_waivers_reason_nonempty"),
        sa.CheckConstraint(
            "request_id IS NULL OR length(trim(request_id)) > 0",
            name="ck_qa_gate_waivers_request_id_nonempty",
        ),
    )
    op.create_index("ix_qa_gate_waivers_work_item", "qa_gate_waivers", ["work_item_id"])

    op.create_table(
        "qa_report_status_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "report_id",
            sa.Uuid(),
            sa.ForeignKey("qa_reports.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "from_status",
            _string_enum(_STATUSES, "ck_qa_report_status_events_from", 16),
            nullable=False,
        ),
        sa.Column(
            "to_status",
            _string_enum(_STATUSES, "ck_qa_report_status_events_to", 16),
            nullable=False,
        ),
        sa.Column(
            "actor_origin",
            _string_enum(_ACTORS, "ck_qa_report_status_events_actor", 16),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column(
            "replacement_report_id",
            sa.Uuid(),
            sa.ForeignKey("qa_reports.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(trim(reason)) > 0", name="ck_qa_report_status_events_reason_nonempty"
        ),
        sa.CheckConstraint(
            "request_id IS NULL OR length(trim(request_id)) > 0",
            name="ck_qa_report_status_events_request_id_nonempty",
        ),
    )
    op.create_index(
        "ix_qa_report_status_events_report", "qa_report_status_events", ["report_id", "id"]
    )

    # QA reports: DELETE forbidden; UPDATE may ONLY move status forward
    # (active -> superseded) while setting superseded_by_report_id once
    # (the proven two-shape rule).
    op.execute(
        sa.text(
            f"""
            CREATE FUNCTION {_REPORT_FUNCTION}()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    RAISE EXCEPTION 'qa_reports rows cannot be deleted'
                        USING ERRCODE = '55000';
                END IF;
                IF NEW.id IS DISTINCT FROM OLD.id
                   OR NEW.work_item_id IS DISTINCT FROM OLD.work_item_id
                   OR NEW.content_draft_id IS DISTINCT FROM OLD.content_draft_id
                   OR NEW.editorial_review_id IS DISTINCT FROM OLD.editorial_review_id
                   OR NEW.content_brief_id IS DISTINCT FROM OLD.content_brief_id
                   OR NEW.version IS DISTINCT FROM OLD.version
                   OR NEW.outcome IS DISTINCT FROM OLD.outcome
                   OR NEW.gate_results IS DISTINCT FROM OLD.gate_results
                   OR NEW.gate_policy_snapshot IS DISTINCT FROM OLD.gate_policy_snapshot
                   OR NEW.engine_name IS DISTINCT FROM OLD.engine_name
                   OR NEW.engine_version IS DISTINCT FROM OLD.engine_version
                   OR NEW.content_hash IS DISTINCT FROM OLD.content_hash
                   OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                    RAISE EXCEPTION 'qa_reports content fields are immutable'
                        USING ERRCODE = '55000';
                END IF;
                IF NOT (
                    (
                        OLD.status = 'active'
                        AND NEW.status = 'superseded'
                        AND OLD.superseded_by_report_id IS NULL
                    )
                    OR (
                        OLD.status = 'superseded'
                        AND NEW.status = 'superseded'
                        AND OLD.superseded_by_report_id IS NULL
                        AND NEW.superseded_by_report_id IS NOT NULL
                    )
                ) THEN
                    RAISE EXCEPTION
                        'qa_reports status transition % -> % is forbidden',
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
            CREATE TRIGGER {_REPORT_TRIGGER}
            BEFORE UPDATE OR DELETE ON qa_reports
            FOR EACH ROW
            EXECUTE FUNCTION {_REPORT_FUNCTION}()
            """
        )
    )

    for function_name, trigger_name, table_name in (
        (_WAIVER_FUNCTION, _WAIVER_TRIGGER, "qa_gate_waivers"),
        (_EVENT_FUNCTION, _EVENT_TRIGGER, "qa_report_status_events"),
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
    op.execute(sa.text(f"DROP TRIGGER {_EVENT_TRIGGER} ON qa_report_status_events"))
    op.execute(sa.text(f"DROP FUNCTION {_EVENT_FUNCTION}()"))
    op.execute(sa.text(f"DROP TRIGGER {_WAIVER_TRIGGER} ON qa_gate_waivers"))
    op.execute(sa.text(f"DROP FUNCTION {_WAIVER_FUNCTION}()"))
    op.execute(sa.text(f"DROP TRIGGER {_REPORT_TRIGGER} ON qa_reports"))
    op.execute(sa.text(f"DROP FUNCTION {_REPORT_FUNCTION}()"))
    op.drop_index("ix_qa_report_status_events_report", table_name="qa_report_status_events")
    op.drop_table("qa_report_status_events")
    op.drop_index("ix_qa_gate_waivers_work_item", table_name="qa_gate_waivers")
    op.drop_table("qa_gate_waivers")
    op.drop_index("uq_qa_reports_active", table_name="qa_reports")
    op.drop_index("ix_qa_reports_draft", table_name="qa_reports")
    op.drop_index("ix_qa_reports_work_item", table_name="qa_reports")
    op.drop_table("qa_reports")
