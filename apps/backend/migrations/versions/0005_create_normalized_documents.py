"""Create immutable normalized_documents.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NORMALIZATION_STATUSES = ("succeeded", "failed")
_FAILURE_CODES = (
    "unsupported_content",
    "decode_error",
    "parse_error",
    "empty_content",
    "extractor_error",
    "policy_rejected",
)
_IMMUTABILITY_FUNCTION = "contentos_reject_normalized_document_mutation"
_IMMUTABILITY_TRIGGER = "trg_normalized_documents_append_only"


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
        "normalized_documents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "fetch_snapshot_id",
            sa.Uuid(),
            sa.ForeignKey("fetch_snapshots.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("extractor_name", sa.String(length=100), nullable=False),
        sa.Column("extractor_version", sa.String(length=100), nullable=False),
        sa.Column("parser_version", sa.String(length=100), nullable=True),
        sa.Column(
            "normalization_status",
            _string_enum(
                _NORMALIZATION_STATUSES,
                "ck_normalized_documents_normalization_status",
                16,
            ),
            nullable=False,
        ),
        sa.Column(
            "failure_code",
            _string_enum(
                _FAILURE_CODES,
                "ck_normalized_documents_failure_code",
                32,
            ),
            nullable=True,
        ),
        sa.Column("failure_detail", sa.String(length=1000), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("clean_text", sa.Text(), nullable=True),
        sa.Column("language", sa.String(length=35), nullable=True),
        sa.Column("author_name", sa.String(length=300), nullable=True),
        sa.Column("external_published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "headings",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "sections",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "links",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "structured_metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("content_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("fingerprint_version", sa.Integer(), nullable=True),
        sa.Column("normalized_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "fetch_snapshot_id",
            "extractor_name",
            "extractor_version",
            name="uq_normalized_documents_snapshot_extractor",
        ),
        sa.CheckConstraint(
            "(normalization_status = 'succeeded' "
            "AND clean_text IS NOT NULL AND length(trim(clean_text)) > 0 "
            "AND failure_code IS NULL AND failure_detail IS NULL "
            "AND content_fingerprint IS NOT NULL AND fingerprint_version IS NOT NULL) "
            "OR (normalization_status = 'failed' "
            "AND failure_code IS NOT NULL "
            "AND title IS NULL AND clean_text IS NULL AND language IS NULL "
            "AND author_name IS NULL AND external_published_at IS NULL "
            "AND content_fingerprint IS NULL AND fingerprint_version IS NULL)",
            name="ck_normalized_documents_status_consistency",
        ),
        sa.CheckConstraint(
            "content_fingerprint IS NULL OR "
            "(length(content_fingerprint) = 64 "
            "AND content_fingerprint = lower(content_fingerprint))",
            name="ck_normalized_documents_fingerprint_format",
        ),
        sa.CheckConstraint(
            "fingerprint_version IS NULL OR fingerprint_version > 0",
            name="ck_normalized_documents_fingerprint_version_positive",
        ),
    )
    op.create_index(
        "ix_normalized_documents_status",
        "normalized_documents",
        ["normalization_status"],
    )
    op.create_index(
        "ix_normalized_documents_content_fingerprint",
        "normalized_documents",
        ["content_fingerprint"],
    )
    op.execute(
        sa.text(
            f"""
            CREATE FUNCTION {_IMMUTABILITY_FUNCTION}()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION 'normalized_documents is append-only; % is forbidden', TG_OP
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
            BEFORE UPDATE OR DELETE ON normalized_documents
            FOR EACH ROW
            EXECUTE FUNCTION {_IMMUTABILITY_FUNCTION}()
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text(f"DROP TRIGGER {_IMMUTABILITY_TRIGGER} ON normalized_documents"))
    op.execute(sa.text(f"DROP FUNCTION {_IMMUTABILITY_FUNCTION}()"))
    op.drop_index(
        "ix_normalized_documents_content_fingerprint",
        table_name="normalized_documents",
    )
    op.drop_index("ix_normalized_documents_status", table_name="normalized_documents")
    op.drop_table("normalized_documents")
