"""Versioned structured-output contracts of the research-driven idea engine.

Three model calls, three explicit schemas. Every field the model returns is
validated here and again by the deterministic domain layer in
``missions.engine``; nothing the model says becomes a fact.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

MISSION_PLAN_SCHEMA_NAME = "mission-plan"
MISSION_PLAN_SCHEMA_VERSION = "1"
MISSION_PLAN_TEMPLATE_NAME = "mission-planning"
MISSION_PLAN_TEMPLATE_VERSION = "1"

RESEARCH_SIGNALS_SCHEMA_NAME = "research-signals"
RESEARCH_SIGNALS_SCHEMA_VERSION = "1"
WEB_RESEARCH_TEMPLATE_NAME = "web-research"
WEB_RESEARCH_TEMPLATE_VERSION = "1"

IDEA_SYNTHESIS_SCHEMA_NAME = "idea-synthesis"
IDEA_SYNTHESIS_SCHEMA_VERSION = "1"
IDEA_SYNTHESIS_TEMPLATE_NAME = "idea-synthesis"
IDEA_SYNTHESIS_TEMPLATE_VERSION = "1"

MAX_QUERIES = 16
MAX_WEB_SIGNALS = 40
MAX_SYNTHESIS_CANDIDATES = 30
MAX_PRIMITIVES = 24

Short = Annotated[str, StringConstraints(min_length=1, max_length=300)]
Medium = Annotated[str, StringConstraints(min_length=1, max_length=1200)]
Key = Annotated[
    str, StringConstraints(min_length=1, max_length=80, pattern=r"^[a-z0-9][a-z0-9_-]{0,79}$")
]

QueryPurpose = Literal["intent", "inspiration", "application", "market", "visual", "community"]
QuerySurface = Literal["open_web", "visual_inspiration", "community_need"]
SignalSurface = Literal["open_web", "visual_inspiration", "community_need"]


class PlannedQueryV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: Short
    language: Literal["tr", "en"]
    purpose: QueryPurpose
    surface: QuerySurface


class MissionPlanV1(BaseModel):
    """What the reader wants, how to look, what to avoid."""

    model_config = ConfigDict(extra="forbid")

    intent_summary: Medium
    audience_notes: Medium
    keywords: list[Short] = Field(min_length=1, max_length=20)
    queries: list[PlannedQueryV1] = Field(min_length=1, max_length=MAX_QUERIES)
    cliche_patterns: list[Short] = Field(default_factory=list, max_length=20)
    primitive_hints: list[Short] = Field(default_factory=list, max_length=20)


class WebSignalV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Short
    snippet: Medium
    url: Annotated[str, StringConstraints(min_length=1, max_length=2000)] | None = None
    surface: SignalSurface
    language: Literal["tr", "en", "other"]
    why_relevant: Medium
    query: Short | None = None


class ResearchSignalsV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signals: list[WebSignalV1] = Field(default_factory=list, max_length=MAX_WEB_SIGNALS)
    search_notes: Medium | None = None


class IdeaPrimitiveV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: Key
    label: Short
    description: Medium


class QualityFactorsV1(BaseModel):
    """Creative quality axes, 0–100 each. None of them is a demand measure."""

    model_config = ConfigDict(extra="forbid")

    novelty: int = Field(ge=0, le=100)
    usefulness: int = Field(ge=0, le=100)
    specificity: int = Field(ge=0, le=100)
    visual_potential: int = Field(ge=0, le=100)
    shareability: int = Field(ge=0, le=100)
    emotional_impact: int = Field(ge=0, le=100)
    audience_fit: int = Field(ge=0, le=100)
    turkey_applicability: int = Field(ge=0, le=100)


class IdeaCandidateV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Short
    angle: Medium
    kind: Literal["extracted", "synthesized"]
    signal_ids: list[Annotated[str, StringConstraints(min_length=36, max_length=36)]] = Field(
        default_factory=list, max_length=12
    )
    primitive_keys: list[Key] = Field(default_factory=list, max_length=8)
    cluster_key: Key
    is_cliche: bool
    cliche_reason: Medium | None = None
    factors: QualityFactorsV1
    implementation_steps: list[Medium] = Field(default_factory=list, max_length=6)
    factual_claims_needed: list[Medium] = Field(default_factory=list, max_length=6)
    rationale: Medium


class IdeaSynthesisV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primitives: list[IdeaPrimitiveV1] = Field(default_factory=list, max_length=MAX_PRIMITIVES)
    candidates: list[IdeaCandidateV1] = Field(min_length=1, max_length=MAX_SYNTHESIS_CANDIDATES)
