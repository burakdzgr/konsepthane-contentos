"""Versioned structured-output schema for automated brief composition.

Strict closed models (extra="forbid", all fields required, nullable where
genuinely optional). The model may propose ONLY writing-contract fields —
never system-owned facts (ids, locale/market, audience, angle, version,
status, engine identity, guard results, hashes, workflow state) and never
article prose. Bounds are imported from the Task-11 persistence contract so
model limits can never exceed persistence limits.
"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from contentos.briefs.enums import BriefClaimKind
from contentos.briefs.values import (
    MAX_ACCEPTANCE_CRITERIA,
    MAX_CLAIM_EVIDENCE_LINKS,
    MAX_CLAIM_HANDLING_LENGTH,
    MAX_CLAIM_KEY_LENGTH,
    MAX_CLAIM_TEXT_LENGTH,
    MAX_CLAIMS,
    MAX_CONTENT_OBJECTIVE_LENGTH,
    MAX_CRITERION_KEY_LENGTH,
    MAX_CRITERION_TEXT_LENGTH,
    MAX_EXCLUSION_LENGTH,
    MAX_EXCLUSIONS,
    MAX_FAQ_QUESTION_LENGTH,
    MAX_FAQ_QUESTIONS,
    MAX_INTENT_SUMMARY_LENGTH,
    MAX_LINK_NEEDS,
    MAX_MEDIA_NEEDS,
    MAX_NEED_TEXT_LENGTH,
    MAX_SECTION_HEADING_LENGTH,
    MAX_SECTION_KEY_LENGTH,
    MAX_SECTION_PURPOSE_LENGTH,
    MAX_SECTIONS,
    MAX_TITLE_CONSTRAINT_LENGTH,
    MAX_TITLE_CONSTRAINTS,
    MAX_TITLE_DIRECTION_LENGTH,
    MAX_UNCERTAINTY_NOTE_LENGTH,
    MAX_UNCERTAINTY_NOTES,
)

BRIEF_COMPOSITION_SCHEMA_NAME = "brief-composition"
BRIEF_COMPOSITION_SCHEMA_VERSION = "1"
BRIEF_COMPOSITION_INPUT_REFS_SCHEMA = "brief-composition/1"

ExclusionText = Annotated[str, Field(min_length=1, max_length=MAX_EXCLUSION_LENGTH)]
UncertaintyText = Annotated[str, Field(min_length=1, max_length=MAX_UNCERTAINTY_NOTE_LENGTH)]
FaqText = Annotated[str, Field(min_length=1, max_length=MAX_FAQ_QUESTION_LENGTH)]
TitleConstraintText = Annotated[str, Field(min_length=1, max_length=MAX_TITLE_CONSTRAINT_LENGTH)]


class BriefSectionV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=MAX_SECTION_KEY_LENGTH)
    heading_guidance: str = Field(min_length=1, max_length=MAX_SECTION_HEADING_LENGTH)
    purpose: str = Field(min_length=1, max_length=MAX_SECTION_PURPOSE_LENGTH)


class InternalLinkNeedV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str = Field(min_length=1, max_length=MAX_NEED_TEXT_LENGTH)
    purpose: str = Field(min_length=1, max_length=MAX_NEED_TEXT_LENGTH)


class MediaNeedV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str = Field(min_length=1, max_length=MAX_NEED_TEXT_LENGTH)
    purpose: str = Field(min_length=1, max_length=MAX_NEED_TEXT_LENGTH)
    constraints: str | None = Field(max_length=MAX_NEED_TEXT_LENGTH)


class AcceptanceCriterionV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=MAX_CRITERION_KEY_LENGTH)
    requirement: str = Field(min_length=1, max_length=MAX_CRITERION_TEXT_LENGTH)


class BriefClaimV1(BaseModel):
    """One proposed claim contract; evidence is ALWAYS exact projected ids."""

    model_config = ConfigDict(extra="forbid")

    claim_key: str = Field(min_length=1, max_length=MAX_CLAIM_KEY_LENGTH)
    claim_text: str = Field(min_length=1, max_length=MAX_CLAIM_TEXT_LENGTH)
    claim_kind: BriefClaimKind
    handling: str | None = Field(max_length=MAX_CLAIM_HANDLING_LENGTH)
    evidence_ids: list[str] = Field(max_length=MAX_CLAIM_EVIDENCE_LINKS)


class BriefCompositionV1(BaseModel):
    """The complete structured composition proposal (contract, not content)."""

    model_config = ConfigDict(extra="forbid")

    intent_summary: str = Field(min_length=1, max_length=MAX_INTENT_SUMMARY_LENGTH)
    content_objective: str = Field(min_length=1, max_length=MAX_CONTENT_OBJECTIVE_LENGTH)
    required_sections: list[BriefSectionV1] = Field(min_length=1, max_length=MAX_SECTIONS)
    optional_sections: list[BriefSectionV1] = Field(max_length=MAX_SECTIONS)
    title_direction: str | None = Field(max_length=MAX_TITLE_DIRECTION_LENGTH)
    title_constraints: list[TitleConstraintText] = Field(max_length=MAX_TITLE_CONSTRAINTS)
    additional_exclusions: list[ExclusionText] = Field(max_length=MAX_EXCLUSIONS)
    additional_uncertainty_notes: list[UncertaintyText] = Field(max_length=MAX_UNCERTAINTY_NOTES)
    internal_link_needs: list[InternalLinkNeedV1] = Field(max_length=MAX_LINK_NEEDS)
    media_needs: list[MediaNeedV1] = Field(max_length=MAX_MEDIA_NEEDS)
    faq_questions: list[FaqText] = Field(max_length=MAX_FAQ_QUESTIONS)
    acceptance_criteria: list[AcceptanceCriterionV1] = Field(max_length=MAX_ACCEPTANCE_CRITERIA)
    claims: list[BriefClaimV1] = Field(min_length=1, max_length=MAX_CLAIMS)
