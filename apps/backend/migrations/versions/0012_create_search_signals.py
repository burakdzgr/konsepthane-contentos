"""Create the append-only provider-neutral search-signal store.

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen literal vocabulary (never import app enums).
_SIGNAL_TYPES = (
    "search_volume",
    "trend",
    "serp_observation",
    "query_set",
    "manual_intent_note",
)

_IMMUTABILITY_FUNCTION = "contentos_reject_search_signal_mutation"
_IMMUTABILITY_TRIGGER = "trg_search_signals_append_only"


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
        "search_signals",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "signal_type",
            _string_enum(_SIGNAL_TYPES, "ck_search_signals_signal_type", 24),
            nullable=False,
        ),
        sa.Column("subject", sa.String(length=300), nullable=False),
        sa.Column("locale", sa.String(length=20), nullable=False),
        sa.Column("market", sa.String(length=2), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column(
            "value",
            postgresql.JSONB(),
            nullable=False,
        ),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observation_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "length(trim(subject)) > 0",
            name="ck_search_signals_subject_nonempty",
        ),
        sa.CheckConstraint(
            "length(trim(locale)) > 0",
            name="ck_search_signals_locale_nonempty",
        ),
        sa.CheckConstraint(
            "length(trim(market)) = 2",
            name="ck_search_signals_market_length",
        ),
        sa.CheckConstraint(
            "length(trim(provider)) > 0",
            name="ck_search_signals_provider_nonempty",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_search_signals_confidence_range",
        ),
        sa.CheckConstraint(
            "length(observation_hash) = 64 AND observation_hash = lower(observation_hash)",
            name="ck_search_signals_hash_format",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(value) = 'object'",
            name="ck_search_signals_value_object",
        ),
    )
    op.create_index(
        "uq_search_signals_observation_hash",
        "search_signals",
        ["observation_hash"],
        unique=True,
    )
    op.create_index(
        "ix_search_signals_subject",
        "search_signals",
        ["subject", "locale", "market", "observed_at"],
    )
    op.create_index(
        "ix_search_signals_type",
        "search_signals",
        ["signal_type"],
    )

    op.execute(
        sa.text(
            f"""
            CREATE FUNCTION {_IMMUTABILITY_FUNCTION}()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION
                    'search_signals is append-only; % is forbidden', TG_OP
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
            BEFORE UPDATE OR DELETE ON search_signals
            FOR EACH ROW
            EXECUTE FUNCTION {_IMMUTABILITY_FUNCTION}()
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text(f"DROP TRIGGER {_IMMUTABILITY_TRIGGER} ON search_signals"))
    op.execute(sa.text(f"DROP FUNCTION {_IMMUTABILITY_FUNCTION}()"))
    op.drop_index("ix_search_signals_type", table_name="search_signals")
    op.drop_index("ix_search_signals_subject", table_name="search_signals")
    op.drop_index("uq_search_signals_observation_hash", table_name="search_signals")
    op.drop_table("search_signals")
