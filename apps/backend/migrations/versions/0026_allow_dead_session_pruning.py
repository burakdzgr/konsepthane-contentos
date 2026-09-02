"""Permit deleting DEAD auth sessions (expired or revoked) for pruning.

Revision ID: 0026
Revises: 0025
Create Date: 2026-09-02

Live sessions stay undeletable and the one-shot-revocation UPDATE rule
is unchanged; only rows that can never authenticate again (revoked, or
past their expiry) may be removed by the audited prune command. The
retention window itself is service policy — the trigger's job is that
a LIVE session can never be destroyed.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SESSION_FUNCTION = "contentos_guard_auth_session_mutation"

_GUARD_V2 = f"""
CREATE OR REPLACE FUNCTION {_SESSION_FUNCTION}()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.revoked_at IS NULL AND OLD.expires_at >= now() THEN
            RAISE EXCEPTION 'live auth_sessions rows cannot be deleted'
                USING ERRCODE = '55000';
        END IF;
        RETURN OLD;
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

_GUARD_V1 = f"""
CREATE OR REPLACE FUNCTION {_SESSION_FUNCTION}()
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


def upgrade() -> None:
    op.execute(sa.text(_GUARD_V2))


def downgrade() -> None:
    op.execute(sa.text(_GUARD_V1))
