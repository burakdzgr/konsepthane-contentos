"""Model-assisted evidence: new generation purpose and extraction method.

`ai_generation_attempts.purpose` gains `evidence_extraction` and
`research_evidence.extraction_method` gains `model_assisted`. Both are
VARCHAR-backed enums with CHECK constraints, widened in place.

Revision ID: 0036
Revises: 0035
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0036"
down_revision: str | None = "0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_PURPOSES = (
    "idea_candidates",
    "intent_synthesis",
    "brief_composition",
    "evidence_organization",
    "writer_draft",
    "editor_review",
    "media_image",
)
_NEW_PURPOSES = (*_OLD_PURPOSES, "evidence_extraction")
_PURPOSE_CONSTRAINT = "ck_ai_generation_attempts_purpose"

_OLD_METHODS = ("machine", "human")
_NEW_METHODS = (*_OLD_METHODS, "model_assisted")
_METHOD_CONSTRAINT = "ck_research_evidence_extraction_method"


def _in(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({quoted})"


def upgrade() -> None:
    op.drop_constraint(_PURPOSE_CONSTRAINT, "ai_generation_attempts", type_="check")
    op.create_check_constraint(
        _PURPOSE_CONSTRAINT, "ai_generation_attempts", _in("purpose", _NEW_PURPOSES)
    )
    op.drop_constraint(_METHOD_CONSTRAINT, "research_evidence", type_="check")
    op.create_check_constraint(
        _METHOD_CONSTRAINT, "research_evidence", _in("extraction_method", _NEW_METHODS)
    )


def downgrade() -> None:
    # Never destroy audit rows to satisfy a narrower constraint: refuse the
    # downgrade while widened rows exist.
    bind = op.get_bind()
    attempts = bind.execute(
        sa.text("SELECT count(*) FROM ai_generation_attempts WHERE purpose = 'evidence_extraction'")
    ).scalar_one()
    evidence = bind.execute(
        sa.text("SELECT count(*) FROM research_evidence WHERE extraction_method = 'model_assisted'")
    ).scalar_one()
    if attempts or evidence:
        raise RuntimeError(
            "cannot downgrade 0036: evidence_extraction attempts or model_assisted evidence exist"
        )
    op.drop_constraint(_METHOD_CONSTRAINT, "research_evidence", type_="check")
    op.create_check_constraint(
        _METHOD_CONSTRAINT, "research_evidence", _in("extraction_method", _OLD_METHODS)
    )
    op.drop_constraint(_PURPOSE_CONSTRAINT, "ai_generation_attempts", type_="check")
    op.create_check_constraint(
        _PURPOSE_CONSTRAINT, "ai_generation_attempts", _in("purpose", _OLD_PURPOSES)
    )
