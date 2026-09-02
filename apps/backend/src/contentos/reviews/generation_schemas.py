"""Strict Editor output schema (`editor-review/1`).

The model emits FINDINGS ONLY — there is no verdict field in the
vocabulary (the verdict is computed by the deterministic policy), no
severity aggregation, no status, no evidence ids, and no free-form
channels. Anchors reference the projected draft's block ids and brief
claim ids; anything else is schema- or domain-rejected. An empty
findings list is a valid, meaningful output.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from contentos.reviews.values import (
    MAX_FINDING_KEY_LENGTH,
    MAX_FINDING_TEXT_LENGTH,
    MAX_FINDINGS_PER_REVIEW,
)

EDITOR_REVIEW_SCHEMA_NAME = "editor-review"
EDITOR_REVIEW_SCHEMA_VERSION = "1"
EDITOR_REVIEW_INPUT_REFS_SCHEMA = "editor-review/1"

FindingKey = Annotated[
    str,
    StringConstraints(
        min_length=1, max_length=MAX_FINDING_KEY_LENGTH, pattern=r"^[a-z0-9][a-z0-9-]{0,63}$"
    ),
]
FindingText = Annotated[str, StringConstraints(min_length=1, max_length=MAX_FINDING_TEXT_LENGTH)]
BlockRef = Annotated[str, StringConstraints(min_length=1, max_length=64)]
ClaimRef = Annotated[str, StringConstraints(min_length=36, max_length=36)]

DimensionLiteral = Literal[
    "claim_faithfulness",
    "exclusion_compliance",
    "objective_fit",
    "clarity_style",
    "uncertainty_framing",
]
SeverityLiteral = Literal["blocking", "major", "minor"]


class EditorFindingV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_key: FindingKey
    dimension: DimensionLiteral
    severity: SeverityLiteral
    description: FindingText
    recommendation: FindingText | None = None
    block_id: BlockRef | None = None
    claim_ref: ClaimRef | None = None


class EditorReviewV1(BaseModel):
    """The whole Editor output contract — findings only, possibly empty."""

    model_config = ConfigDict(extra="forbid")

    findings: list[EditorFindingV1] = Field(
        default_factory=list, max_length=MAX_FINDINGS_PER_REVIEW
    )
