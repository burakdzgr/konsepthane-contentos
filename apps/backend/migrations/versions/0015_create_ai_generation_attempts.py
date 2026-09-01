"""Create AI generation attempts and stage Idea/EvidencePack AI provenance.

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen literal vocabularies (never import app enums).
_PURPOSES = (
    "idea_candidates",
    "intent_synthesis",
    "brief_composition",
    "evidence_organization",
)
_STATUSES = ("succeeded", "validation_failed", "provider_error", "timeout", "cancelled")

_ATTEMPT_FUNCTION = "contentos_reject_ai_generation_attempt_mutation"
_ATTEMPT_TRIGGER = "trg_ai_generation_attempts_append_only"

# Task 7's operator-only origin CHECK is widened here; the downgrade
# restores it (and PostgreSQL validates existing rows on ADD CONSTRAINT, so
# a downgrade in the presence of model-assisted rows fails loudly instead
# of silently corrupting provenance).
_ORIGIN_CHECK_OPERATOR_ONLY = "origin IN ('operator')"
_ORIGIN_CHECK_WIDENED = "origin IN ('operator', 'model_assisted')"


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
        "ai_generation_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "purpose",
            _string_enum(_PURPOSES, "ck_ai_generation_attempts_purpose", 24),
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("model_name", sa.String(length=200), nullable=False),
        sa.Column("model_version", sa.String(length=50), nullable=True),
        sa.Column("schema_name", sa.String(length=100), nullable=False),
        sa.Column("schema_version", sa.String(length=50), nullable=False),
        sa.Column("template_name", sa.String(length=100), nullable=False),
        sa.Column("template_version", sa.String(length=50), nullable=False),
        sa.Column(
            "input_refs",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("attempt_identity_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            _string_enum(_STATUSES, "ck_ai_generation_attempts_status", 24),
            nullable=False,
        ),
        sa.Column("error_class", sa.String(length=100), nullable=True),
        sa.Column("retry_number", sa.Integer(), nullable=False),
        sa.Column(
            "usage",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("attempt_identity_hash", name="uq_ai_generation_attempts_identity"),
        sa.CheckConstraint(
            "length(trim(provider)) > 0",
            name="ck_ai_generation_attempts_provider_nonempty",
        ),
        sa.CheckConstraint(
            "length(trim(model_name)) > 0",
            name="ck_ai_generation_attempts_model_name_nonempty",
        ),
        sa.CheckConstraint(
            "model_version IS NULL OR length(trim(model_version)) > 0",
            name="ck_ai_generation_attempts_model_version_nonempty",
        ),
        sa.CheckConstraint(
            "length(trim(schema_name)) > 0",
            name="ck_ai_generation_attempts_schema_name_nonempty",
        ),
        sa.CheckConstraint(
            "length(trim(schema_version)) > 0",
            name="ck_ai_generation_attempts_schema_version_nonempty",
        ),
        sa.CheckConstraint(
            "length(trim(template_name)) > 0",
            name="ck_ai_generation_attempts_template_name_nonempty",
        ),
        sa.CheckConstraint(
            "length(trim(template_version)) > 0",
            name="ck_ai_generation_attempts_template_version_nonempty",
        ),
        sa.CheckConstraint(
            "length(input_hash) = 64 AND input_hash = lower(input_hash)",
            name="ck_ai_generation_attempts_input_hash_format",
        ),
        sa.CheckConstraint(
            "length(attempt_identity_hash) = 64 AND "
            "attempt_identity_hash = lower(attempt_identity_hash)",
            name="ck_ai_generation_attempts_identity_hash_format",
        ),
        sa.CheckConstraint("retry_number >= 0", name="ck_ai_generation_attempts_retry_range"),
        sa.CheckConstraint(
            "(status = 'succeeded' AND error_class IS NULL) OR "
            "(status != 'succeeded' AND error_class IS NOT NULL "
            "AND length(trim(error_class)) > 0)",
            name="ck_ai_generation_attempts_error_consistency",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(input_refs) = 'object'",
            name="ck_ai_generation_attempts_input_refs_object",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(usage) = 'object'",
            name="ck_ai_generation_attempts_usage_object",
        ),
    )
    op.create_index(
        "ix_ai_generation_attempts_purpose",
        "ai_generation_attempts",
        ["purpose", "created_at"],
    )
    op.create_index(
        "ix_ai_generation_attempts_input_hash", "ai_generation_attempts", ["input_hash"]
    )

    op.execute(
        sa.text(
            f"""
            CREATE FUNCTION {_ATTEMPT_FUNCTION}()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION
                    'ai_generation_attempts is append-only; % is forbidden', TG_OP
                    USING ERRCODE = '55000';
            END;
            $$
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            CREATE TRIGGER {_ATTEMPT_TRIGGER}
            BEFORE UPDATE OR DELETE ON ai_generation_attempts
            FOR EACH ROW
            EXECUTE FUNCTION {_ATTEMPT_FUNCTION}()
            """
        )
    )

    # Staged Idea AI provenance: widen the origin vocabulary and add the
    # real generation-attempt FK; operator rows stay valid with NULL.
    op.add_column("ideas", sa.Column("generation_attempt_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_ideas_generation_attempt",
        "ideas",
        "ai_generation_attempts",
        ["generation_attempt_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_ideas_generation_attempt", "ideas", ["generation_attempt_id"])
    op.drop_constraint("ck_ideas_origin", "ideas", type_="check")
    op.create_check_constraint("ck_ideas_origin", "ideas", _ORIGIN_CHECK_WIDENED)
    op.create_check_constraint(
        "ck_ideas_origin_attempt_consistency",
        "ideas",
        "(origin = 'operator' AND generation_attempt_id IS NULL) OR "
        "(origin = 'model_assisted' AND generation_attempt_id IS NOT NULL)",
    )

    # Staged EvidencePack AI organization link (deferred by Task 6): the
    # deterministic assembly service keeps writing NULL.
    op.add_column("evidence_packs", sa.Column("organization_attempt_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_evidence_packs_organization_attempt",
        "evidence_packs",
        "ai_generation_attempts",
        ["organization_attempt_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_evidence_packs_organization_attempt",
        "evidence_packs",
        ["organization_attempt_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_evidence_packs_organization_attempt", table_name="evidence_packs")
    op.drop_constraint(
        "fk_evidence_packs_organization_attempt", "evidence_packs", type_="foreignkey"
    )
    op.drop_column("evidence_packs", "organization_attempt_id")

    op.drop_constraint("ck_ideas_origin_attempt_consistency", "ideas", type_="check")
    op.drop_index("ix_ideas_generation_attempt", table_name="ideas")
    op.drop_constraint("fk_ideas_generation_attempt", "ideas", type_="foreignkey")
    op.drop_column("ideas", "generation_attempt_id")
    op.drop_constraint("ck_ideas_origin", "ideas", type_="check")
    # PostgreSQL validates existing rows here: model-assisted rows make the
    # downgrade FAIL rather than silently losing provenance.
    op.create_check_constraint("ck_ideas_origin", "ideas", _ORIGIN_CHECK_OPERATOR_ONLY)

    op.execute(sa.text(f"DROP TRIGGER {_ATTEMPT_TRIGGER} ON ai_generation_attempts"))
    op.execute(sa.text(f"DROP FUNCTION {_ATTEMPT_FUNCTION}()"))
    op.drop_index("ix_ai_generation_attempts_input_hash", table_name="ai_generation_attempts")
    op.drop_index("ix_ai_generation_attempts_purpose", table_name="ai_generation_attempts")
    op.drop_table("ai_generation_attempts")
