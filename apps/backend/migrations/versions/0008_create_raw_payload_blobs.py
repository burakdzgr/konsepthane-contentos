"""Create immutable content-addressed raw_payload_blobs.

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen literals; the application setting range can never exceed this bound.
_ABSOLUTE_MAX_PAYLOAD_BYTES = 52_428_800
_IMMUTABILITY_FUNCTION = "contentos_reject_raw_payload_blob_mutation"
_IMMUTABILITY_TRIGGER = "trg_raw_payload_blobs_append_only"


def upgrade() -> None:
    op.create_table(
        "raw_payload_blobs",
        sa.Column("sha256", sa.String(length=64), primary_key=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("payload", postgresql.BYTEA(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_raw_payload_blobs_sha256_format",
        ),
        sa.CheckConstraint("size_bytes >= 0", name="ck_raw_payload_blobs_size_nonnegative"),
        sa.CheckConstraint(
            f"size_bytes <= {_ABSOLUTE_MAX_PAYLOAD_BYTES}",
            name="ck_raw_payload_blobs_size_bounded",
        ),
        sa.CheckConstraint(
            "octet_length(payload) = size_bytes",
            name="ck_raw_payload_blobs_size_consistency",
        ),
    )
    op.execute(
        sa.text(
            f"""
            CREATE FUNCTION {_IMMUTABILITY_FUNCTION}()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION 'raw_payload_blobs is append-only; % is forbidden', TG_OP
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
            BEFORE UPDATE OR DELETE ON raw_payload_blobs
            FOR EACH ROW
            EXECUTE FUNCTION {_IMMUTABILITY_FUNCTION}()
            """
        )
    )


def downgrade() -> None:
    # Removes only objects introduced by 0008; earlier tables and pgvector
    # are untouched.
    op.execute(sa.text(f"DROP TRIGGER {_IMMUTABILITY_TRIGGER} ON raw_payload_blobs"))
    op.execute(sa.text(f"DROP FUNCTION {_IMMUTABILITY_FUNCTION}()"))
    op.drop_table("raw_payload_blobs")
