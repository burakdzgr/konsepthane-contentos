"""Create media assets, need satisfactions, and their audit events.

Revision ID: 0023
Revises: 0022
Create Date: 2026-09-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen literal vocabularies (never import app enums).
_ORIGINS = ("human_upload", "ai_generated")
_STATUSES = ("active", "superseded")
_MEDIA_TYPES = ("image/png", "image/jpeg", "image/webp")

_ASSET_FUNCTION = "contentos_reject_media_asset_mutation"
_ASSET_TRIGGER = "trg_media_assets_append_only"
_SATISFACTION_FUNCTION = "contentos_guard_media_satisfaction_mutation"
_SATISFACTION_TRIGGER = "trg_media_need_satisfactions_guarded"
_EVENT_FUNCTION = "contentos_reject_media_satisfaction_event_mutation"
_EVENT_TRIGGER = "trg_media_satisfaction_events_append_only"


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
        "media_assets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "origin",
            _string_enum(_ORIGINS, "ck_media_assets_origin", 16),
            nullable=False,
        ),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("media_type", sa.String(length=50), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("alt_text", sa.Text(), nullable=False),
        sa.Column("license_note", sa.Text(), nullable=False),
        sa.Column("source_attribution", sa.Text(), nullable=True),
        sa.Column(
            "generation_attempt_id",
            sa.Uuid(),
            sa.ForeignKey("ai_generation_attempts.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "created_by_user_id",
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
        sa.UniqueConstraint("content_sha256", name="uq_media_assets_content"),
        sa.UniqueConstraint("generation_attempt_id", name="uq_media_assets_attempt"),
        sa.CheckConstraint(
            "(origin = 'ai_generated') = (generation_attempt_id IS NOT NULL)",
            name="ck_media_assets_origin_attempt",
        ),
        sa.CheckConstraint(
            "length(content_sha256) = 64 AND content_sha256 = lower(content_sha256)",
            name="ck_media_assets_sha_format",
        ),
        sa.CheckConstraint("byte_size > 0", name="ck_media_assets_bytes_positive"),
        sa.CheckConstraint(
            "media_type IN ('image/png', 'image/jpeg', 'image/webp')",
            name="ck_media_assets_media_type",
        ),
        sa.CheckConstraint("width IS NULL OR width > 0", name="ck_media_assets_width_positive"),
        sa.CheckConstraint("height IS NULL OR height > 0", name="ck_media_assets_height_positive"),
        sa.CheckConstraint("length(trim(alt_text)) > 0", name="ck_media_assets_alt_text_nonempty"),
        sa.CheckConstraint(
            "length(trim(license_note)) > 0", name="ck_media_assets_license_nonempty"
        ),
        sa.CheckConstraint(
            "request_id IS NULL OR length(trim(request_id)) > 0",
            name="ck_media_assets_request_id_nonempty",
        ),
    )
    op.create_index("ix_media_assets_creator", "media_assets", ["created_by_user_id"])

    op.create_table(
        "media_need_satisfactions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "work_item_id",
            sa.Uuid(),
            sa.ForeignKey("editorial_work_items.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "content_brief_id",
            sa.Uuid(),
            sa.ForeignKey("content_briefs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("need_index", sa.Integer(), nullable=False),
        sa.Column(
            "media_asset_id",
            sa.Uuid(),
            sa.ForeignKey("media_assets.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "status",
            _string_enum(_STATUSES, "ck_media_satisfactions_status", 16),
            nullable=False,
        ),
        sa.Column(
            "superseded_by_satisfaction_id",
            sa.Uuid(),
            sa.ForeignKey("media_need_satisfactions.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "satisfied_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
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
        sa.CheckConstraint("need_index >= 0", name="ck_media_satisfactions_need_index"),
        sa.CheckConstraint(
            "length(trim(reason)) > 0", name="ck_media_satisfactions_reason_nonempty"
        ),
        sa.CheckConstraint(
            "request_id IS NULL OR length(trim(request_id)) > 0",
            name="ck_media_satisfactions_request_id_nonempty",
        ),
    )
    op.create_index(
        "ix_media_satisfactions_work_item", "media_need_satisfactions", ["work_item_id"]
    )
    op.create_index("ix_media_satisfactions_asset", "media_need_satisfactions", ["media_asset_id"])
    op.create_index(
        "uq_media_satisfactions_active",
        "media_need_satisfactions",
        ["work_item_id", "content_brief_id", "need_index"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "media_satisfaction_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "satisfaction_id",
            sa.Uuid(),
            sa.ForeignKey("media_need_satisfactions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "from_status",
            _string_enum(_STATUSES, "ck_media_satisfaction_events_from", 16),
            nullable=False,
        ),
        sa.Column(
            "to_status",
            _string_enum(_STATUSES, "ck_media_satisfaction_events_to", 16),
            nullable=False,
        ),
        sa.Column(
            "actor_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column(
            "replacement_satisfaction_id",
            sa.Uuid(),
            sa.ForeignKey("media_need_satisfactions.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(trim(reason)) > 0", name="ck_media_satisfaction_events_reason_nonempty"
        ),
        sa.CheckConstraint(
            "request_id IS NULL OR length(trim(request_id)) > 0",
            name="ck_media_satisfaction_events_request_id_nonempty",
        ),
    )
    op.create_index(
        "ix_media_satisfaction_events_satisfaction",
        "media_satisfaction_events",
        ["satisfaction_id", "id"],
    )

    # Media assets are IMMUTABLE: no UPDATE, no DELETE, ever.
    op.execute(
        sa.text(
            f"""
            CREATE FUNCTION {_ASSET_FUNCTION}()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION
                    'media_assets is append-only; % is forbidden', TG_OP
                    USING ERRCODE = '55000';
            END;
            $$
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            CREATE TRIGGER {_ASSET_TRIGGER}
            BEFORE UPDATE OR DELETE ON media_assets
            FOR EACH ROW
            EXECUTE FUNCTION {_ASSET_FUNCTION}()
            """
        )
    )

    # Satisfactions: DELETE forbidden; UPDATE may ONLY move status forward
    # (active -> superseded) or set the replacement pointer once afterwards.
    op.execute(
        sa.text(
            f"""
            CREATE FUNCTION {_SATISFACTION_FUNCTION}()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    RAISE EXCEPTION 'media_need_satisfactions rows cannot be deleted'
                        USING ERRCODE = '55000';
                END IF;
                IF NEW.id IS DISTINCT FROM OLD.id
                   OR NEW.work_item_id IS DISTINCT FROM OLD.work_item_id
                   OR NEW.content_brief_id IS DISTINCT FROM OLD.content_brief_id
                   OR NEW.need_index IS DISTINCT FROM OLD.need_index
                   OR NEW.media_asset_id IS DISTINCT FROM OLD.media_asset_id
                   OR NEW.satisfied_by_user_id IS DISTINCT FROM OLD.satisfied_by_user_id
                   OR NEW.reason IS DISTINCT FROM OLD.reason
                   OR NEW.request_id IS DISTINCT FROM OLD.request_id
                   OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                    RAISE EXCEPTION 'media_need_satisfactions content fields are immutable'
                        USING ERRCODE = '55000';
                END IF;
                IF NOT (
                    (
                        OLD.status = 'active'
                        AND NEW.status = 'superseded'
                        AND OLD.superseded_by_satisfaction_id IS NULL
                        AND NEW.superseded_by_satisfaction_id IS NULL
                    )
                    OR (
                        OLD.status = 'superseded'
                        AND NEW.status = 'superseded'
                        AND OLD.superseded_by_satisfaction_id IS NULL
                        AND NEW.superseded_by_satisfaction_id IS NOT NULL
                    )
                ) THEN
                    RAISE EXCEPTION
                        'media_need_satisfactions status transition % -> % is forbidden',
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
            CREATE TRIGGER {_SATISFACTION_TRIGGER}
            BEFORE UPDATE OR DELETE ON media_need_satisfactions
            FOR EACH ROW
            EXECUTE FUNCTION {_SATISFACTION_FUNCTION}()
            """
        )
    )

    op.execute(
        sa.text(
            f"""
            CREATE FUNCTION {_EVENT_FUNCTION}()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION
                    'media_satisfaction_events is append-only; % is forbidden', TG_OP
                    USING ERRCODE = '55000';
            END;
            $$
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            CREATE TRIGGER {_EVENT_TRIGGER}
            BEFORE UPDATE OR DELETE ON media_satisfaction_events
            FOR EACH ROW
            EXECUTE FUNCTION {_EVENT_FUNCTION}()
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text(f"DROP TRIGGER {_EVENT_TRIGGER} ON media_satisfaction_events"))
    op.execute(sa.text(f"DROP FUNCTION {_EVENT_FUNCTION}()"))
    op.execute(sa.text(f"DROP TRIGGER {_SATISFACTION_TRIGGER} ON media_need_satisfactions"))
    op.execute(sa.text(f"DROP FUNCTION {_SATISFACTION_FUNCTION}()"))
    op.execute(sa.text(f"DROP TRIGGER {_ASSET_TRIGGER} ON media_assets"))
    op.execute(sa.text(f"DROP FUNCTION {_ASSET_FUNCTION}()"))
    op.drop_index(
        "ix_media_satisfaction_events_satisfaction", table_name="media_satisfaction_events"
    )
    op.drop_table("media_satisfaction_events")
    op.drop_index("uq_media_satisfactions_active", table_name="media_need_satisfactions")
    op.drop_index("ix_media_satisfactions_asset", table_name="media_need_satisfactions")
    op.drop_index("ix_media_satisfactions_work_item", table_name="media_need_satisfactions")
    op.drop_table("media_need_satisfactions")
    op.drop_index("ix_media_assets_creator", table_name="media_assets")
    op.drop_table("media_assets")
