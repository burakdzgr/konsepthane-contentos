"""Create content briefs, claims, claim evidence, and status audit.

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen literal vocabularies (never import app enums).
_STATUSES = ("draft", "accepted_for_drafting", "superseded")
_CLAIM_KINDS = (
    "factual",
    "source_assertion",
    "observation",
    "inference",
    "editorial_judgment",
    "instruction",
)
_ACTORS = ("operator",)

_BRIEF_FUNCTION = "contentos_guard_content_brief_mutation"
_BRIEF_TRIGGER = "trg_content_briefs_guarded"
_CLAIM_FUNCTION = "contentos_reject_brief_claim_mutation"
_CLAIM_TRIGGER = "trg_brief_claims_append_only"
_LINK_FUNCTION = "contentos_reject_brief_claim_evidence_mutation"
_LINK_TRIGGER = "trg_brief_claim_evidence_append_only"
_EVENT_FUNCTION = "contentos_reject_brief_status_event_mutation"
_EVENT_TRIGGER = "trg_brief_status_events_append_only"


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
        "content_briefs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "work_item_id",
            sa.Uuid(),
            sa.ForeignKey("editorial_work_items.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "idea_id",
            sa.Uuid(),
            sa.ForeignKey("ideas.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "evidence_pack_id",
            sa.Uuid(),
            sa.ForeignKey("evidence_packs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "search_intent_analysis_id",
            sa.Uuid(),
            sa.ForeignKey("search_intent_analyses.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("locale", sa.String(length=20), nullable=False),
        sa.Column("market", sa.String(length=2), nullable=False),
        sa.Column("target_audience", sa.String(length=500), nullable=False),
        sa.Column("intent_summary", sa.Text(), nullable=False),
        sa.Column("original_angle", sa.Text(), nullable=False),
        sa.Column(
            "title_guidance",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("content_objective", sa.Text(), nullable=False),
        sa.Column(
            "required_sections",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "optional_sections",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "practical_requirements",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "exclusions",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "uncertainty_notes",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "internal_link_needs",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "media_needs",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "faq_questions",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "acceptance_criteria",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "structure_guard_result",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "structure_policy_snapshot",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "status",
            _string_enum(_STATUSES, "ck_content_briefs_status", 24),
            nullable=False,
        ),
        sa.Column(
            "composition_attempt_id",
            sa.Uuid(),
            sa.ForeignKey("ai_generation_attempts.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("engine_name", sa.String(length=100), nullable=False),
        sa.Column("engine_version", sa.String(length=50), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("work_item_id", "version", name="uq_content_briefs_version"),
        sa.UniqueConstraint(
            "work_item_id",
            "idea_id",
            "evidence_pack_id",
            "search_intent_analysis_id",
            "engine_name",
            "engine_version",
            name="uq_content_briefs_identity",
        ),
        sa.CheckConstraint("version > 0", name="ck_content_briefs_version_positive"),
        sa.CheckConstraint("length(trim(locale)) > 0", name="ck_content_briefs_locale_nonempty"),
        sa.CheckConstraint("length(trim(market)) = 2", name="ck_content_briefs_market_length"),
        sa.CheckConstraint(
            "length(trim(target_audience)) > 0",
            name="ck_content_briefs_audience_nonempty",
        ),
        sa.CheckConstraint(
            "length(trim(intent_summary)) > 0",
            name="ck_content_briefs_intent_summary_nonempty",
        ),
        sa.CheckConstraint(
            "length(trim(original_angle)) > 0", name="ck_content_briefs_angle_nonempty"
        ),
        sa.CheckConstraint(
            "length(trim(content_objective)) > 0",
            name="ck_content_briefs_objective_nonempty",
        ),
        sa.CheckConstraint(
            "length(trim(engine_name)) > 0",
            name="ck_content_briefs_engine_name_nonempty",
        ),
        sa.CheckConstraint(
            "length(trim(engine_version)) > 0",
            name="ck_content_briefs_engine_version_nonempty",
        ),
        sa.CheckConstraint(
            "length(content_hash) = 64 AND content_hash = lower(content_hash)",
            name="ck_content_briefs_hash_format",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(title_guidance) = 'object'",
            name="ck_content_briefs_title_guidance_object",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(required_sections) = 'array'",
            name="ck_content_briefs_required_sections_array",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(exclusions) = 'array'",
            name="ck_content_briefs_exclusions_array",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(structure_guard_result) = 'object'",
            name="ck_content_briefs_guard_object",
        ),
    )
    op.create_index("ix_content_briefs_work_item", "content_briefs", ["work_item_id", "version"])
    op.create_index("ix_content_briefs_idea", "content_briefs", ["idea_id"])
    op.create_index("ix_content_briefs_pack", "content_briefs", ["evidence_pack_id"])
    op.create_index("ix_content_briefs_intent", "content_briefs", ["search_intent_analysis_id"])
    op.create_index(
        "ix_content_briefs_composition_attempt", "content_briefs", ["composition_attempt_id"]
    )
    op.create_index(
        "uq_content_briefs_active",
        "content_briefs",
        ["work_item_id"],
        unique=True,
        postgresql_where=sa.text("status != 'superseded'"),
    )

    op.create_table(
        "brief_claims",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "brief_id",
            sa.Uuid(),
            sa.ForeignKey("content_briefs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("claim_key", sa.String(length=100), nullable=False),
        sa.Column("claim_text", sa.Text(), nullable=False),
        sa.Column(
            "claim_kind",
            _string_enum(_CLAIM_KINDS, "ck_brief_claims_kind", 24),
            nullable=False,
        ),
        sa.Column("handling", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("brief_id", "claim_key", name="uq_brief_claims_key"),
        sa.CheckConstraint("length(trim(claim_key)) > 0", name="ck_brief_claims_key_nonempty"),
        sa.CheckConstraint("length(trim(claim_text)) > 0", name="ck_brief_claims_text_nonempty"),
    )
    op.create_index("ix_brief_claims_brief", "brief_claims", ["brief_id"])

    op.create_table(
        "brief_claim_evidence",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "claim_id",
            sa.Uuid(),
            sa.ForeignKey("brief_claims.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "research_evidence_id",
            sa.Uuid(),
            sa.ForeignKey("research_evidence.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "claim_id", "research_evidence_id", name="uq_brief_claim_evidence_link"
        ),
    )
    op.create_index("ix_brief_claim_evidence_claim", "brief_claim_evidence", ["claim_id"])
    op.create_index(
        "ix_brief_claim_evidence_evidence", "brief_claim_evidence", ["research_evidence_id"]
    )

    op.create_table(
        "brief_status_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "brief_id",
            sa.Uuid(),
            sa.ForeignKey("content_briefs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "from_status",
            _string_enum(_STATUSES, "ck_brief_status_events_from", 24),
            nullable=False,
        ),
        sa.Column(
            "to_status",
            _string_enum(_STATUSES, "ck_brief_status_events_to", 24),
            nullable=False,
        ),
        sa.Column(
            "actor_origin",
            _string_enum(_ACTORS, "ck_brief_status_events_actor", 16),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column(
            "replacement_brief_id",
            sa.Uuid(),
            sa.ForeignKey("content_briefs.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(trim(reason)) > 0", name="ck_brief_status_events_reason_nonempty"
        ),
        sa.CheckConstraint(
            "request_id IS NULL OR length(trim(request_id)) > 0",
            name="ck_brief_status_events_request_id_nonempty",
        ),
    )
    op.create_index("ix_brief_status_events_brief", "brief_status_events", ["brief_id", "id"])

    # Content briefs: DELETE forbidden; UPDATE may change ONLY `status`,
    # and only along the accepted forward-only transitions.
    op.execute(
        sa.text(
            f"""
            CREATE FUNCTION {_BRIEF_FUNCTION}()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    RAISE EXCEPTION 'content_briefs rows cannot be deleted'
                        USING ERRCODE = '55000';
                END IF;
                IF NEW.id IS DISTINCT FROM OLD.id
                   OR NEW.work_item_id IS DISTINCT FROM OLD.work_item_id
                   OR NEW.version IS DISTINCT FROM OLD.version
                   OR NEW.idea_id IS DISTINCT FROM OLD.idea_id
                   OR NEW.evidence_pack_id IS DISTINCT FROM OLD.evidence_pack_id
                   OR NEW.search_intent_analysis_id IS DISTINCT FROM OLD.search_intent_analysis_id
                   OR NEW.locale IS DISTINCT FROM OLD.locale
                   OR NEW.market IS DISTINCT FROM OLD.market
                   OR NEW.target_audience IS DISTINCT FROM OLD.target_audience
                   OR NEW.intent_summary IS DISTINCT FROM OLD.intent_summary
                   OR NEW.original_angle IS DISTINCT FROM OLD.original_angle
                   OR NEW.title_guidance IS DISTINCT FROM OLD.title_guidance
                   OR NEW.content_objective IS DISTINCT FROM OLD.content_objective
                   OR NEW.required_sections IS DISTINCT FROM OLD.required_sections
                   OR NEW.optional_sections IS DISTINCT FROM OLD.optional_sections
                   OR NEW.practical_requirements IS DISTINCT FROM OLD.practical_requirements
                   OR NEW.exclusions IS DISTINCT FROM OLD.exclusions
                   OR NEW.uncertainty_notes IS DISTINCT FROM OLD.uncertainty_notes
                   OR NEW.internal_link_needs IS DISTINCT FROM OLD.internal_link_needs
                   OR NEW.media_needs IS DISTINCT FROM OLD.media_needs
                   OR NEW.faq_questions IS DISTINCT FROM OLD.faq_questions
                   OR NEW.acceptance_criteria IS DISTINCT FROM OLD.acceptance_criteria
                   OR NEW.structure_guard_result IS DISTINCT FROM OLD.structure_guard_result
                   OR NEW.structure_policy_snapshot IS DISTINCT FROM OLD.structure_policy_snapshot
                   OR NEW.composition_attempt_id IS DISTINCT FROM OLD.composition_attempt_id
                   OR NEW.engine_name IS DISTINCT FROM OLD.engine_name
                   OR NEW.engine_version IS DISTINCT FROM OLD.engine_version
                   OR NEW.content_hash IS DISTINCT FROM OLD.content_hash
                   OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                    RAISE EXCEPTION 'content_briefs content fields are immutable'
                        USING ERRCODE = '55000';
                END IF;
                IF NOT (
                    (OLD.status = 'draft' AND NEW.status = 'accepted_for_drafting')
                    OR (OLD.status = 'draft' AND NEW.status = 'superseded')
                    OR (OLD.status = 'accepted_for_drafting' AND NEW.status = 'superseded')
                ) THEN
                    RAISE EXCEPTION
                        'content_briefs status transition % -> % is forbidden',
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
            CREATE TRIGGER {_BRIEF_TRIGGER}
            BEFORE UPDATE OR DELETE ON content_briefs
            FOR EACH ROW
            EXECUTE FUNCTION {_BRIEF_FUNCTION}()
            """
        )
    )

    for function_name, trigger_name, table_name in (
        (_CLAIM_FUNCTION, _CLAIM_TRIGGER, "brief_claims"),
        (_LINK_FUNCTION, _LINK_TRIGGER, "brief_claim_evidence"),
        (_EVENT_FUNCTION, _EVENT_TRIGGER, "brief_status_events"),
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
    op.execute(sa.text(f"DROP TRIGGER {_EVENT_TRIGGER} ON brief_status_events"))
    op.execute(sa.text(f"DROP FUNCTION {_EVENT_FUNCTION}()"))
    op.execute(sa.text(f"DROP TRIGGER {_LINK_TRIGGER} ON brief_claim_evidence"))
    op.execute(sa.text(f"DROP FUNCTION {_LINK_FUNCTION}()"))
    op.execute(sa.text(f"DROP TRIGGER {_CLAIM_TRIGGER} ON brief_claims"))
    op.execute(sa.text(f"DROP FUNCTION {_CLAIM_FUNCTION}()"))
    op.execute(sa.text(f"DROP TRIGGER {_BRIEF_TRIGGER} ON content_briefs"))
    op.execute(sa.text(f"DROP FUNCTION {_BRIEF_FUNCTION}()"))
    op.drop_index("ix_brief_status_events_brief", table_name="brief_status_events")
    op.drop_table("brief_status_events")
    op.drop_index("ix_brief_claim_evidence_evidence", table_name="brief_claim_evidence")
    op.drop_index("ix_brief_claim_evidence_claim", table_name="brief_claim_evidence")
    op.drop_table("brief_claim_evidence")
    op.drop_index("ix_brief_claims_brief", table_name="brief_claims")
    op.drop_table("brief_claims")
    op.drop_index("uq_content_briefs_active", table_name="content_briefs")
    op.drop_index("ix_content_briefs_composition_attempt", table_name="content_briefs")
    op.drop_index("ix_content_briefs_intent", table_name="content_briefs")
    op.drop_index("ix_content_briefs_pack", table_name="content_briefs")
    op.drop_index("ix_content_briefs_idea", table_name="content_briefs")
    op.drop_index("ix_content_briefs_work_item", table_name="content_briefs")
    op.drop_table("content_briefs")
