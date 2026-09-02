"""Widen the AI attempt purpose vocabulary with media_image.

Revision ID: 0024
Revises: 0023
Create Date: 2026-09-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen literal vocabularies (never import app enums).
_OLD_PURPOSES = (
    "idea_candidates",
    "intent_synthesis",
    "brief_composition",
    "evidence_organization",
    "writer_draft",
    "editor_review",
)
_NEW_PURPOSES = (*_OLD_PURPOSES, "media_image")
_PURPOSE_CONSTRAINT = "ck_ai_generation_attempts_purpose"


def _purpose_in(values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"purpose IN ({quoted})"


def upgrade() -> None:
    op.drop_constraint(_PURPOSE_CONSTRAINT, "ai_generation_attempts", type_="check")
    op.create_check_constraint(
        _PURPOSE_CONSTRAINT, "ai_generation_attempts", _purpose_in(_NEW_PURPOSES)
    )


def downgrade() -> None:
    # Never destroy audit rows to satisfy a narrower constraint: refuse the
    # downgrade while media_image attempts exist.
    media_attempts = (
        op.get_bind()
        .execute(
            sa.text("SELECT count(*) FROM ai_generation_attempts WHERE purpose = 'media_image'")
        )
        .scalar()
    )
    if media_attempts:
        raise RuntimeError(
            "cannot downgrade 0024: ai_generation_attempts contains "
            f"{media_attempts} media_image attempt(s); refusing to destroy "
            "or invalidate audit history"
        )
    op.drop_constraint(_PURPOSE_CONSTRAINT, "ai_generation_attempts", type_="check")
    op.create_check_constraint(
        _PURPOSE_CONSTRAINT, "ai_generation_attempts", _purpose_in(_OLD_PURPOSES)
    )
