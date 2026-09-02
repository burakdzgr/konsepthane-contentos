"""Create users, user events, auth sessions.

Revision ID: 0021
Revises: 0020
Create Date: 2026-09-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen literal vocabularies (never import app enums).
_ACTIONS = (
    "provisioned",
    "password_rotated",
    "roles_changed",
    "deactivated",
    "reactivated",
)

_USER_FUNCTION = "contentos_guard_user_mutation"
_USER_TRIGGER = "trg_users_guarded"
_EVENT_FUNCTION = "contentos_reject_user_event_mutation"
_EVENT_TRIGGER = "trg_user_events_append_only"
_SESSION_FUNCTION = "contentos_guard_auth_session_mutation"
_SESSION_TRIGGER = "trg_auth_sessions_guarded"


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
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column(
            "roles",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("credentials_rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("username", name="uq_users_username"),
        sa.CheckConstraint("length(trim(username)) > 0", name="ck_users_username_nonempty"),
        sa.CheckConstraint("length(trim(display_name)) > 0", name="ck_users_display_nonempty"),
        sa.CheckConstraint("length(trim(password_hash)) > 0", name="ck_users_password_nonempty"),
        sa.CheckConstraint("jsonb_typeof(roles) = 'array'", name="ck_users_roles_array"),
    )

    op.create_table(
        "user_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "action",
            _string_enum(_ACTIONS, "ck_user_events_action", 24),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "detail",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("length(trim(reason)) > 0", name="ck_user_events_reason_nonempty"),
    )
    op.create_index("ix_user_events_user", "user_events", ["user_id", "id"])

    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("token_hash", name="uq_auth_sessions_token_hash"),
        sa.CheckConstraint(
            "length(token_hash) = 64 AND token_hash = lower(token_hash)",
            name="ck_auth_sessions_token_hash_format",
        ),
    )
    op.create_index("ix_auth_sessions_user", "auth_sessions", ["user_id"])

    # Users: DELETE forbidden; UPDATE may touch ONLY the credential/role/
    # activation fields — identity is immutable.
    op.execute(
        sa.text(
            f"""
            CREATE FUNCTION {_USER_FUNCTION}()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    RAISE EXCEPTION 'users rows cannot be deleted; deactivate instead'
                        USING ERRCODE = '55000';
                END IF;
                IF NEW.id IS DISTINCT FROM OLD.id
                   OR NEW.username IS DISTINCT FROM OLD.username
                   OR NEW.display_name IS DISTINCT FROM OLD.display_name
                   OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                    RAISE EXCEPTION 'users identity fields are immutable'
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
            CREATE TRIGGER {_USER_TRIGGER}
            BEFORE UPDATE OR DELETE ON users
            FOR EACH ROW
            EXECUTE FUNCTION {_USER_FUNCTION}()
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
                    'user_events is append-only; % is forbidden', TG_OP
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
            BEFORE UPDATE OR DELETE ON user_events
            FOR EACH ROW
            EXECUTE FUNCTION {_EVENT_FUNCTION}()
            """
        )
    )

    # Sessions: DELETE forbidden (audit); the one legal UPDATE is the
    # one-shot revocation (revoked_at NULL -> value).
    op.execute(
        sa.text(
            f"""
            CREATE FUNCTION {_SESSION_FUNCTION}()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    RAISE EXCEPTION 'auth_sessions rows cannot be deleted'
                        USING ERRCODE = '55000';
                END IF;
                IF NEW.id IS DISTINCT FROM OLD.id
                   OR NEW.user_id IS DISTINCT FROM OLD.user_id
                   OR NEW.token_hash IS DISTINCT FROM OLD.token_hash
                   OR NEW.created_at IS DISTINCT FROM OLD.created_at
                   OR NEW.expires_at IS DISTINCT FROM OLD.expires_at THEN
                    RAISE EXCEPTION 'auth_sessions content fields are immutable'
                        USING ERRCODE = '55000';
                END IF;
                IF NOT (OLD.revoked_at IS NULL AND NEW.revoked_at IS NOT NULL) THEN
                    RAISE EXCEPTION
                        'auth_sessions permits only the one-shot revocation'
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
            CREATE TRIGGER {_SESSION_TRIGGER}
            BEFORE UPDATE OR DELETE ON auth_sessions
            FOR EACH ROW
            EXECUTE FUNCTION {_SESSION_FUNCTION}()
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text(f"DROP TRIGGER {_SESSION_TRIGGER} ON auth_sessions"))
    op.execute(sa.text(f"DROP FUNCTION {_SESSION_FUNCTION}()"))
    op.execute(sa.text(f"DROP TRIGGER {_EVENT_TRIGGER} ON user_events"))
    op.execute(sa.text(f"DROP FUNCTION {_EVENT_FUNCTION}()"))
    op.execute(sa.text(f"DROP TRIGGER {_USER_TRIGGER} ON users"))
    op.execute(sa.text(f"DROP FUNCTION {_USER_FUNCTION}()"))
    op.drop_index("ix_auth_sessions_user", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_index("ix_user_events_user", table_name="user_events")
    op.drop_table("user_events")
    op.drop_table("users")
