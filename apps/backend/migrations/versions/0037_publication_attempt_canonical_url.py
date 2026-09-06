"""Publication attempts keep the canonical URL Konsepthane reports.

The Publishing API answers a successful publish with `publication_ref` (the
one required field) and, optionally, `canonical_url`. The reference alone is
not an address, so the performance loop could never match Search Console or
GA4 rows to the content. The attempt row now carries the reported URL;
nothing is derived by guessing.

Revision ID: 0037
Revises: 0036
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0037"
down_revision: str | None = "0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("publication_attempts", sa.Column("canonical_url", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("publication_attempts", "canonical_url")
