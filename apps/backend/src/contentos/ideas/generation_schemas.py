"""Versioned structured-output schemas for model-assisted idea candidates.

Strict-mode friendly: every model is a closed object (extra="forbid") with
every field required (nullable where genuinely optional), so the derived
JSON Schema satisfies OpenAI strict Structured Outputs while our own
Pydantic validation stays the authoritative second defense layer.

The model proposes ONLY editorial content fields. It can never supply
database IDs, logical idea identity, opportunity/locale/market, origin,
attempt references, scores, evidence provenance, workflow state, selection
markers, or publication status — those are deterministic system-owned
fields, and ranking/selection is never model output.
"""

from pydantic import BaseModel, ConfigDict, Field

from contentos.ideas.enums import ContentType

IDEA_CANDIDATE_SCHEMA_NAME = "idea-candidate-batch"
IDEA_CANDIDATE_SCHEMA_VERSION = "1"

MIN_CANDIDATES = 1
MAX_CANDIDATES = 5


class PlanningDimensionsV1(BaseModel):
    """Closed nullable projection of the Task-7 planning vocabulary."""

    model_config = ConfigDict(extra="forbid")

    theme: str | None = Field(max_length=200)
    cake: str | None = Field(max_length=200)
    budget_band: str | None = Field(max_length=200)
    space: str | None = Field(max_length=200)
    preparation_time: str | None = Field(max_length=200)
    diy_level: str | None = Field(max_length=200)
    suitability: str | None = Field(max_length=200)
    color_palette: list[str] | None = Field(max_length=12)
    decorations: list[str] | None = Field(max_length=30)
    menu: list[str] | None = Field(max_length=30)
    shopping_list: list[str] | None = Field(max_length=50)
    practical_steps: list[str] | None = Field(max_length=30)

    def to_dimensions(self) -> dict[str, str | list[str]]:
        """Only the genuinely proposed dimensions, for Task-7 validation."""
        return {name: value for name, value in self.model_dump().items() if value is not None}


class IdeaCandidateV1(BaseModel):
    """One model-proposed editorial concept (never an article, never facts)."""

    model_config = ConfigDict(extra="forbid")

    working_title: str = Field(min_length=1, max_length=200)
    angle: str = Field(min_length=1, max_length=2000)
    audience: str = Field(min_length=1, max_length=500)
    value_proposition: str = Field(min_length=1, max_length=1000)
    rationale: str = Field(min_length=1, max_length=2000)
    content_type: ContentType
    exclusions: list[str] = Field(max_length=20)
    planning_dimensions: PlanningDimensionsV1


class IdeaCandidateBatchV1(BaseModel):
    """The complete structured generation result: candidates only."""

    model_config = ConfigDict(extra="forbid")

    candidates: list[IdeaCandidateV1] = Field(min_length=MIN_CANDIDATES, max_length=MAX_CANDIDATES)
