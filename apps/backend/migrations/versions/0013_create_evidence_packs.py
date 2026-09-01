"""Create evidence packs, items, and contradictions.

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen literal vocabularies (never import app enums).
_SUFFICIENCIES = ("ready", "insufficient", "conflicted", "blocked")
_ROLES = ("key_fact", "supporting", "contradicting", "context", "caution")
_SEVERITIES = ("low", "material", "blocking")
_RESOLUTIONS = (
    "unresolved",
    "resolved_cautious_wording",
    "resolved_needs_research",
    "resolved_editorial_judgment",
)
_RESOLVERS = ("operator",)

_PACK_FUNCTION = "contentos_reject_evidence_pack_mutation"
_PACK_TRIGGER = "trg_evidence_packs_append_only"
_ITEM_FUNCTION = "contentos_reject_evidence_pack_item_mutation"
_ITEM_TRIGGER = "trg_evidence_pack_items_append_only"
_CONTRADICTION_FUNCTION = "contentos_guard_evidence_contradiction_mutation"
_CONTRADICTION_TRIGGER = "trg_evidence_contradictions_guarded"


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
        "evidence_packs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "opportunity_id",
            sa.Uuid(),
            sa.ForeignKey("editorial_opportunities.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("assembler_name", sa.String(length=100), nullable=False),
        sa.Column("assembler_version", sa.String(length=100), nullable=False),
        sa.Column(
            "sufficiency",
            _string_enum(_SUFFICIENCIES, "ck_evidence_packs_sufficiency", 16),
            nullable=False,
        ),
        sa.Column(
            "sufficiency_detail",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "source_diversity",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "staleness_notes",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "locale_limitations",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "licensing_cautions",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "policy_snapshot",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "assembly_input_snapshot",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("assembly_input_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("opportunity_id", "version", name="uq_evidence_packs_version"),
        sa.UniqueConstraint(
            "opportunity_id",
            "assembler_name",
            "assembler_version",
            "assembly_input_hash",
            name="uq_evidence_packs_identity",
        ),
        sa.CheckConstraint("version > 0", name="ck_evidence_packs_version_positive"),
        sa.CheckConstraint(
            "length(trim(assembler_name)) > 0",
            name="ck_evidence_packs_assembler_name_nonempty",
        ),
        sa.CheckConstraint(
            "length(trim(assembler_version)) > 0",
            name="ck_evidence_packs_assembler_version_nonempty",
        ),
        sa.CheckConstraint(
            "length(assembly_input_hash) = 64 AND assembly_input_hash = lower(assembly_input_hash)",
            name="ck_evidence_packs_hash_format",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(assembly_input_snapshot) = 'object'",
            name="ck_evidence_packs_assembly_snapshot_object",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(sufficiency_detail) = 'object'",
            name="ck_evidence_packs_detail_object",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(policy_snapshot) = 'object'",
            name="ck_evidence_packs_policy_object",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(staleness_notes) = 'array'",
            name="ck_evidence_packs_staleness_array",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(licensing_cautions) = 'array'",
            name="ck_evidence_packs_licensing_array",
        ),
    )
    op.create_index(
        "ix_evidence_packs_opportunity", "evidence_packs", ["opportunity_id", "version"]
    )

    op.create_table(
        "evidence_pack_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "pack_id",
            sa.Uuid(),
            sa.ForeignKey("evidence_packs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "research_evidence_id",
            sa.Uuid(),
            sa.ForeignKey("research_evidence.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "role",
            _string_enum(_ROLES, "ck_evidence_pack_items_role", 16),
            nullable=False,
        ),
        sa.Column("claim_cluster", sa.String(length=100), nullable=False),
        sa.Column("display_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "pack_id", "research_evidence_id", name="uq_evidence_pack_items_evidence"
        ),
        sa.CheckConstraint(
            "length(trim(claim_cluster)) > 0",
            name="ck_evidence_pack_items_cluster_nonempty",
        ),
    )
    op.create_index("ix_evidence_pack_items_pack", "evidence_pack_items", ["pack_id"])
    op.create_index(
        "ix_evidence_pack_items_evidence", "evidence_pack_items", ["research_evidence_id"]
    )

    op.create_table(
        "evidence_contradictions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "pack_id",
            sa.Uuid(),
            sa.ForeignKey("evidence_packs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("claim_key", sa.String(length=100), nullable=False),
        sa.Column(
            "evidence_side_a",
            postgresql.JSONB(),
            nullable=False,
        ),
        sa.Column(
            "evidence_side_b",
            postgresql.JSONB(),
            nullable=False,
        ),
        sa.Column("nature", sa.Text(), nullable=False),
        sa.Column(
            "severity",
            _string_enum(_SEVERITIES, "ck_evidence_contradictions_severity", 16),
            nullable=False,
        ),
        sa.Column(
            "resolution_status",
            _string_enum(_RESOLUTIONS, "ck_evidence_contradictions_resolution_status", 32),
            nullable=False,
        ),
        sa.Column("handling_recommendation", sa.Text(), nullable=True),
        sa.Column("resolution_reason", sa.Text(), nullable=True),
        sa.Column(
            "resolved_by",
            _string_enum(_RESOLVERS, "ck_evidence_contradictions_resolved_by", 16),
            nullable=True,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "length(trim(claim_key)) > 0",
            name="ck_evidence_contradictions_claim_key_nonempty",
        ),
        sa.CheckConstraint(
            "length(trim(nature)) > 0",
            name="ck_evidence_contradictions_nature_nonempty",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(evidence_side_a) = 'array'",
            name="ck_evidence_contradictions_side_a_array",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(evidence_side_b) = 'array'",
            name="ck_evidence_contradictions_side_b_array",
        ),
        sa.CheckConstraint(
            "(resolution_status = 'unresolved' AND resolved_at IS NULL "
            "AND resolved_by IS NULL AND resolution_reason IS NULL) OR "
            "(resolution_status != 'unresolved' AND resolved_at IS NOT NULL "
            "AND resolved_by IS NOT NULL AND resolution_reason IS NOT NULL "
            "AND length(trim(resolution_reason)) > 0)",
            name="ck_evidence_contradictions_resolution_consistency",
        ),
    )
    op.create_index("ix_evidence_contradictions_pack", "evidence_contradictions", ["pack_id"])

    for function_name, trigger_name, table_name in (
        (_PACK_FUNCTION, _PACK_TRIGGER, "evidence_packs"),
        (_ITEM_FUNCTION, _ITEM_TRIGGER, "evidence_pack_items"),
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

    # Contradictions: DELETE forbidden; UPDATE may touch ONLY the resolution
    # dimension (status, reason, resolver, timestamp, handling note).
    op.execute(
        sa.text(
            f"""
            CREATE FUNCTION {_CONTRADICTION_FUNCTION}()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    RAISE EXCEPTION
                        'evidence_contradictions rows cannot be deleted'
                        USING ERRCODE = '55000';
                END IF;
                IF NEW.id IS DISTINCT FROM OLD.id
                   OR NEW.pack_id IS DISTINCT FROM OLD.pack_id
                   OR NEW.claim_key IS DISTINCT FROM OLD.claim_key
                   OR NEW.evidence_side_a IS DISTINCT FROM OLD.evidence_side_a
                   OR NEW.evidence_side_b IS DISTINCT FROM OLD.evidence_side_b
                   OR NEW.nature IS DISTINCT FROM OLD.nature
                   OR NEW.severity IS DISTINCT FROM OLD.severity
                   OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                    RAISE EXCEPTION
                        'evidence_contradictions core fields are immutable'
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
            CREATE TRIGGER {_CONTRADICTION_TRIGGER}
            BEFORE UPDATE OR DELETE ON evidence_contradictions
            FOR EACH ROW
            EXECUTE FUNCTION {_CONTRADICTION_FUNCTION}()
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text(f"DROP TRIGGER {_CONTRADICTION_TRIGGER} ON evidence_contradictions"))
    op.execute(sa.text(f"DROP FUNCTION {_CONTRADICTION_FUNCTION}()"))
    op.execute(sa.text(f"DROP TRIGGER {_ITEM_TRIGGER} ON evidence_pack_items"))
    op.execute(sa.text(f"DROP FUNCTION {_ITEM_FUNCTION}()"))
    op.execute(sa.text(f"DROP TRIGGER {_PACK_TRIGGER} ON evidence_packs"))
    op.execute(sa.text(f"DROP FUNCTION {_PACK_FUNCTION}()"))
    op.drop_index("ix_evidence_contradictions_pack", table_name="evidence_contradictions")
    op.drop_table("evidence_contradictions")
    op.drop_index("ix_evidence_pack_items_evidence", table_name="evidence_pack_items")
    op.drop_index("ix_evidence_pack_items_pack", table_name="evidence_pack_items")
    op.drop_table("evidence_pack_items")
    op.drop_index("ix_evidence_packs_opportunity", table_name="evidence_packs")
    op.drop_table("evidence_packs")
