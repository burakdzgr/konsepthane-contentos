"""Create publication packages and attempt facts.

Revision ID: 0025
Revises: 0024
Create Date: 2026-09-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PACKAGE_FUNCTION = "contentos_reject_publication_package_mutation"
_PACKAGE_TRIGGER = "trg_publication_packages_append_only"
_ATTEMPT_FUNCTION = "contentos_reject_publication_attempt_mutation"
_ATTEMPT_TRIGGER = "trg_publication_attempts_append_only"


def upgrade() -> None:
    op.create_table(
        "publication_packages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "work_item_id",
            sa.Uuid(),
            sa.ForeignKey("editorial_work_items.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "human_decision_id",
            sa.Uuid(),
            sa.ForeignKey("human_decisions.id", ondelete="RESTRICT"),
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
        sa.Column(
            "qa_report_id",
            sa.Uuid(),
            sa.ForeignKey("qa_reports.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("payload_schema_version", sa.String(length=50), nullable=False),
        sa.Column("package_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "media_manifest",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "assembled_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("work_item_id", "version", name="uq_publication_packages_version"),
        sa.UniqueConstraint("work_item_id", "package_hash", name="uq_publication_packages_content"),
        sa.CheckConstraint("version > 0", name="ck_publication_packages_version_positive"),
        sa.CheckConstraint(
            "length(content_hash) = 64 AND content_hash = lower(content_hash)",
            name="ck_publication_packages_content_hash_format",
        ),
        sa.CheckConstraint(
            "length(package_hash) = 64 AND package_hash = lower(package_hash)",
            name="ck_publication_packages_package_hash_format",
        ),
        sa.CheckConstraint(
            "length(trim(payload_schema_version)) > 0",
            name="ck_publication_packages_schema_version_nonempty",
        ),
        sa.CheckConstraint(
            "request_id IS NULL OR length(trim(request_id)) > 0",
            name="ck_publication_packages_request_id_nonempty",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(payload) = 'object'", name="ck_publication_packages_payload_object"
        ),
    )
    op.create_index(
        "ix_publication_packages_work_item", "publication_packages", ["work_item_id", "version"]
    )

    op.create_table(
        "publication_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "publication_package_id",
            sa.Uuid(),
            sa.ForeignKey("publication_packages.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_class", sa.String(length=100), nullable=True),
        sa.Column("remote_publication_ref", sa.Text(), nullable=True),
        sa.Column("transport_name", sa.String(length=100), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "publication_package_id", "attempt_number", name="uq_publication_attempts_number"
        ),
        sa.CheckConstraint("attempt_number > 0", name="ck_publication_attempts_number_positive"),
        sa.CheckConstraint(
            "status IN ('succeeded', 'transport_error', 'rejected_by_api', 'timeout')",
            name="ck_publication_attempts_status",
        ),
        sa.CheckConstraint(
            "(status = 'succeeded') = (remote_publication_ref IS NOT NULL)",
            name="ck_publication_attempts_remote_ref",
        ),
        sa.CheckConstraint(
            "length(trim(idempotency_key)) > 0",
            name="ck_publication_attempts_idempotency_nonempty",
        ),
        sa.CheckConstraint(
            "length(trim(transport_name)) > 0",
            name="ck_publication_attempts_transport_nonempty",
        ),
        sa.CheckConstraint(
            "request_id IS NULL OR length(trim(request_id)) > 0",
            name="ck_publication_attempts_request_id_nonempty",
        ),
    )
    op.create_index(
        "ix_publication_attempts_package",
        "publication_attempts",
        ["publication_package_id", "attempt_number"],
    )
    op.create_index(
        "ix_publication_attempts_idempotency", "publication_attempts", ["idempotency_key"]
    )

    for function_name, trigger_name, table_name in (
        (_PACKAGE_FUNCTION, _PACKAGE_TRIGGER, "publication_packages"),
        (_ATTEMPT_FUNCTION, _ATTEMPT_TRIGGER, "publication_attempts"),
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
    op.execute(sa.text(f"DROP TRIGGER {_ATTEMPT_TRIGGER} ON publication_attempts"))
    op.execute(sa.text(f"DROP FUNCTION {_ATTEMPT_FUNCTION}()"))
    op.execute(sa.text(f"DROP TRIGGER {_PACKAGE_TRIGGER} ON publication_packages"))
    op.execute(sa.text(f"DROP FUNCTION {_PACKAGE_FUNCTION}()"))
    op.drop_index("ix_publication_attempts_idempotency", table_name="publication_attempts")
    op.drop_index("ix_publication_attempts_package", table_name="publication_attempts")
    op.drop_table("publication_attempts")
    op.drop_index("ix_publication_packages_work_item", table_name="publication_packages")
    op.drop_table("publication_packages")
