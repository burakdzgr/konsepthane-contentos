"""Enable the PostgreSQL pgvector extension.

Revision ID: 0001
Revises:
Create Date: 2026-08-31
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    # Intentionally NOT dropping the vector extension: future ContentOS data
    # (vector columns and indexes) may depend on it, so removal must stay a
    # deliberate manual operator decision, never an automated downgrade.
    pass
