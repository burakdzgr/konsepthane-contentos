"""Add editorial purpose (primary_role, capabilities) to sources.

Revision ID: 0031
Revises: 0030

``kind`` stays technical (how content is acquired); ``primary_role`` and
``capabilities`` record the editorial purpose. Existing rows become
inspiration / ["inspiration"] through server defaults, so the migration is
additive and never rewrites a source definition.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLES = (
    "inspiration",
    "turkish_editorial",
    "community_intent",
    "competitor",
    "taxonomy",
    "trend",
    "search",
)
_ROLE_LIST = ", ".join(f"'{value}'" for value in _ROLES)


def upgrade() -> None:
    op.add_column(
        "sources",
        sa.Column(
            "primary_role",
            sa.String(length=24),
            nullable=False,
            server_default="inspiration",
        ),
    )
    op.add_column(
        "sources",
        sa.Column(
            "capabilities",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=False,
            server_default=sa.text("'[\"inspiration\"]'"),
        ),
    )
    op.create_check_constraint(
        "ck_sources_primary_role", "sources", f"primary_role IN ({_ROLE_LIST})"
    )
    op.create_index("ix_sources_primary_role", "sources", ["primary_role"])


def downgrade() -> None:
    op.drop_index("ix_sources_primary_role", table_name="sources")
    op.drop_constraint("ck_sources_primary_role", "sources", type_="check")
    op.drop_column("sources", "capabilities")
    op.drop_column("sources", "primary_role")
