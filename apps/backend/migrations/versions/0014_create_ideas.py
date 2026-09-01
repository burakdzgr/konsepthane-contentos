"""Create ideas, idea selection events, and the evidence-pack idea link.

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen literal vocabularies (never import app enums). Origin is
# deliberately operator-only: MODEL_ASSISTED arrives with the AI-boundary
# task's own migration together with the real generation-attempt FK.
_CONTENT_TYPES = (
    "guide",
    "idea_list",
    "checklist",
    "planning_guide",
    "comparison",
    "faq",
    "how_to",
    "inspiration",
)
_ORIGINS = ("operator",)
_ORIGINALITY_STATUSES = ("passed", "failed", "not_checkable")
_SELECTION_ACTIONS = ("selected", "deselected")
_SELECTION_ACTORS = ("operator",)

_IDEA_FUNCTION = "contentos_reject_idea_mutation"
_IDEA_TRIGGER = "trg_ideas_append_only"
_EVENT_FUNCTION = "contentos_reject_idea_selection_event_mutation"
_EVENT_TRIGGER = "trg_idea_selection_events_append_only"


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
        "ideas",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("logical_idea_id", sa.Uuid(), nullable=False),
        sa.Column(
            "opportunity_id",
            sa.Uuid(),
            sa.ForeignKey("editorial_opportunities.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("working_title", sa.String(length=200), nullable=False),
        sa.Column("angle", sa.Text(), nullable=False),
        sa.Column("audience", sa.String(length=500), nullable=False),
        sa.Column("value_proposition", sa.Text(), nullable=False),
        sa.Column(
            "content_type",
            _string_enum(_CONTENT_TYPES, "ck_ideas_content_type", 16),
            nullable=False,
        ),
        sa.Column("locale", sa.String(length=20), nullable=False),
        sa.Column("market", sa.String(length=2), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column(
            "exclusions",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "planning_dimensions",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "originality_status",
            _string_enum(_ORIGINALITY_STATUSES, "ck_ideas_originality_status", 16),
            nullable=False,
        ),
        sa.Column(
            "originality_detail",
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
            "origin",
            _string_enum(_ORIGINS, "ck_ideas_origin", 16),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("logical_idea_id", "version", name="uq_ideas_logical_version"),
        sa.CheckConstraint("version > 0", name="ck_ideas_version_positive"),
        sa.CheckConstraint(
            "length(trim(working_title)) > 0", name="ck_ideas_working_title_nonempty"
        ),
        sa.CheckConstraint("length(trim(angle)) > 0", name="ck_ideas_angle_nonempty"),
        sa.CheckConstraint("length(trim(audience)) > 0", name="ck_ideas_audience_nonempty"),
        sa.CheckConstraint(
            "length(trim(value_proposition)) > 0",
            name="ck_ideas_value_proposition_nonempty",
        ),
        sa.CheckConstraint("length(trim(rationale)) > 0", name="ck_ideas_rationale_nonempty"),
        sa.CheckConstraint("length(trim(locale)) > 0", name="ck_ideas_locale_nonempty"),
        sa.CheckConstraint("length(trim(market)) = 2", name="ck_ideas_market_length"),
        sa.CheckConstraint("jsonb_typeof(exclusions) = 'array'", name="ck_ideas_exclusions_array"),
        sa.CheckConstraint(
            "jsonb_typeof(planning_dimensions) = 'object'",
            name="ck_ideas_planning_dimensions_object",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(originality_detail) = 'object'",
            name="ck_ideas_originality_detail_object",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(originality_policy_snapshot) = 'object'",
            name="ck_ideas_originality_policy_object",
        ),
    )
    op.create_index("ix_ideas_opportunity", "ideas", ["opportunity_id"])

    op.create_table(
        "idea_selection_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "opportunity_id",
            sa.Uuid(),
            sa.ForeignKey("editorial_opportunities.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "idea_id",
            sa.Uuid(),
            sa.ForeignKey("ideas.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "action",
            _string_enum(_SELECTION_ACTIONS, "ck_idea_selection_events_action", 16),
            nullable=False,
        ),
        sa.Column(
            "actor_origin",
            _string_enum(_SELECTION_ACTORS, "ck_idea_selection_events_actor", 16),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(trim(reason)) > 0", name="ck_idea_selection_events_reason_nonempty"
        ),
        sa.CheckConstraint(
            "request_id IS NULL OR length(trim(request_id)) > 0",
            name="ck_idea_selection_events_request_id_nonempty",
        ),
    )
    op.create_index(
        "ix_idea_selection_events_opportunity",
        "idea_selection_events",
        ["opportunity_id", "id"],
    )

    # The accepted nullable EvidencePack -> Idea relationship, deferred by
    # Task 6 until ideas existed. Existing packs stay NULL and valid.
    op.add_column("evidence_packs", sa.Column("idea_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_evidence_packs_idea",
        "evidence_packs",
        "ideas",
        ["idea_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_evidence_packs_idea", "evidence_packs", ["idea_id"])

    for function_name, trigger_name, table_name in (
        (_IDEA_FUNCTION, _IDEA_TRIGGER, "ideas"),
        (_EVENT_FUNCTION, _EVENT_TRIGGER, "idea_selection_events"),
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
    # The evidence-pack link must go before the ideas table it references;
    # Task 6 packs themselves survive untouched.
    op.drop_index("ix_evidence_packs_idea", table_name="evidence_packs")
    op.drop_constraint("fk_evidence_packs_idea", "evidence_packs", type_="foreignkey")
    op.drop_column("evidence_packs", "idea_id")
    op.execute(sa.text(f"DROP TRIGGER {_EVENT_TRIGGER} ON idea_selection_events"))
    op.execute(sa.text(f"DROP FUNCTION {_EVENT_FUNCTION}()"))
    op.execute(sa.text(f"DROP TRIGGER {_IDEA_TRIGGER} ON ideas"))
    op.execute(sa.text(f"DROP FUNCTION {_IDEA_FUNCTION}()"))
    op.drop_index("ix_idea_selection_events_opportunity", table_name="idea_selection_events")
    op.drop_table("idea_selection_events")
    op.drop_index("ix_ideas_opportunity", table_name="ideas")
    op.drop_table("ideas")
