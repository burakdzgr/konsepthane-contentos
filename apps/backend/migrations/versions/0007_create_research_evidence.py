"""Create immutable research_evidence.

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EVIDENCE_TYPES = ("source_assertion", "observation", "statistic", "quote", "instruction")
_EXTRACTION_METHODS = ("machine", "human")
_VERIFICATION_STATUSES = ("unverified", "verified", "disputed", "retracted")
_IMMUTABILITY_FUNCTION = "contentos_reject_research_evidence_mutation"
_IMMUTABILITY_TRIGGER = "trg_research_evidence_append_only"


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
        "research_evidence",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "normalized_document_id",
            sa.Uuid(),
            sa.ForeignKey("normalized_documents.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "fetch_snapshot_id",
            sa.Uuid(),
            sa.ForeignKey("fetch_snapshots.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "source_id",
            sa.Uuid(),
            sa.ForeignKey("sources.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_url", sa.String(length=2000), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "evidence_type",
            _string_enum(_EVIDENCE_TYPES, "ck_research_evidence_evidence_type", 24),
            nullable=False,
        ),
        sa.Column("statement", sa.String(length=2000), nullable=False),
        sa.Column("excerpt", sa.String(length=750), nullable=True),
        sa.Column("excerpt_start", sa.Integer(), nullable=True),
        sa.Column("excerpt_end", sa.Integer(), nullable=True),
        sa.Column("offset_version", sa.Integer(), nullable=True),
        sa.Column("source_locator", sa.String(length=500), nullable=True),
        sa.Column(
            "verification_status",
            _string_enum(
                _VERIFICATION_STATUSES,
                "ck_research_evidence_verification_status",
                16,
            ),
            nullable=False,
        ),
        sa.Column("confidence", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("confidence_basis", sa.String(length=500), nullable=True),
        sa.Column("extractor_name", sa.String(length=100), nullable=False),
        sa.Column("extractor_version", sa.String(length=100), nullable=False),
        sa.Column(
            "extraction_method",
            _string_enum(
                _EXTRACTION_METHODS,
                "ck_research_evidence_extraction_method",
                16,
            ),
            nullable=False,
        ),
        sa.Column("licensing_notes", sa.String(length=1000), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("evidence_key", sa.String(length=64), nullable=False),
        sa.Column(
            "evidence_key_version", sa.Integer(), nullable=False, server_default=sa.text("1")
        ),
        sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "normalized_document_id",
            "extractor_name",
            "extractor_version",
            "evidence_key",
            name="uq_research_evidence_document_extractor_key",
        ),
        sa.CheckConstraint(
            "length(trim(statement)) > 0",
            name="ck_research_evidence_statement_nonempty",
        ),
        sa.CheckConstraint(
            "length(trim(extractor_name)) > 0",
            name="ck_research_evidence_extractor_name_nonempty",
        ),
        sa.CheckConstraint(
            "length(trim(extractor_version)) > 0",
            name="ck_research_evidence_extractor_version_nonempty",
        ),
        sa.CheckConstraint(
            "length(trim(source_url)) > 0",
            name="ck_research_evidence_source_url_nonempty",
        ),
        sa.CheckConstraint(
            "evidence_key ~ '^[0-9a-f]{64}$'",
            name="ck_research_evidence_key_format",
        ),
        sa.CheckConstraint(
            "evidence_key_version = 1",
            name="ck_research_evidence_key_version",
        ),
        sa.CheckConstraint(
            "(excerpt IS NULL AND excerpt_start IS NULL AND excerpt_end IS NULL "
            "AND offset_version IS NULL AND source_locator IS NOT NULL) OR "
            "(excerpt IS NOT NULL AND length(excerpt) > 0 AND length(excerpt) <= 750 "
            "AND excerpt_start IS NOT NULL AND excerpt_start >= 0 "
            "AND excerpt_end IS NOT NULL AND excerpt_end > excerpt_start "
            "AND offset_version = 1)",
            name="ck_research_evidence_excerpt_consistency",
        ),
        sa.CheckConstraint(
            "verification_status != 'verified' OR excerpt IS NOT NULL",
            name="ck_research_evidence_verified_has_excerpt",
        ),
        sa.CheckConstraint(
            "evidence_type != 'quote' OR excerpt IS NOT NULL",
            name="ck_research_evidence_quote_has_excerpt",
        ),
        sa.CheckConstraint(
            "source_locator IS NULL OR length(trim(source_locator)) > 0",
            name="ck_research_evidence_source_locator_nonempty",
        ),
        sa.CheckConstraint(
            "(confidence IS NULL AND confidence_basis IS NULL) OR "
            "(confidence IS NOT NULL AND confidence >= 0 AND confidence <= 1 "
            "AND confidence_basis IS NOT NULL AND length(trim(confidence_basis)) > 0)",
            name="ck_research_evidence_confidence_consistency",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(metadata) = 'object'",
            name="ck_research_evidence_metadata_object",
        ),
    )
    op.create_index(
        "ix_research_evidence_verification_status",
        "research_evidence",
        ["verification_status"],
    )
    op.create_index(
        "ix_research_evidence_evidence_type",
        "research_evidence",
        ["evidence_type"],
    )
    op.create_index("ix_research_evidence_source_id", "research_evidence", ["source_id"])
    op.execute(
        sa.text(
            f"""
            CREATE FUNCTION {_IMMUTABILITY_FUNCTION}()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION 'research_evidence is append-only; % is forbidden', TG_OP
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
            BEFORE UPDATE OR DELETE ON research_evidence
            FOR EACH ROW
            EXECUTE FUNCTION {_IMMUTABILITY_FUNCTION}()
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text(f"DROP TRIGGER {_IMMUTABILITY_TRIGGER} ON research_evidence"))
    op.execute(sa.text(f"DROP FUNCTION {_IMMUTABILITY_FUNCTION}()"))
    op.drop_index("ix_research_evidence_source_id", table_name="research_evidence")
    op.drop_index("ix_research_evidence_evidence_type", table_name="research_evidence")
    op.drop_index("ix_research_evidence_verification_status", table_name="research_evidence")
    op.drop_table("research_evidence")
