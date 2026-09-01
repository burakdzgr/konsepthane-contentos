"""Versioned structured-output schema for optional intent synthesis.

Strict-mode friendly closed models. The model may propose ONLY semantic
analysis fields; system-owned facts (ids, version, locale/market, signal
refs, missing signals, cannibalization status/basis, related references,
attempt id, target audience) remain deterministic and cannot enter through
this schema.
"""

from pydantic import BaseModel, ConfigDict, Field

SEARCH_INTENT_SYNTHESIS_SCHEMA_NAME = "search-intent-synthesis"
SEARCH_INTENT_SYNTHESIS_SCHEMA_VERSION = "1"


class SearchIntentSynthesisV1(BaseModel):
    """Semantic intent proposal — concepts, never measured demand."""

    model_config = ConfigDict(extra="forbid")

    primary_intent: str = Field(min_length=1, max_length=200)
    secondary_intents: list[str] = Field(max_length=10)
    query_concepts: list[str] = Field(max_length=30)
    page_purpose: str = Field(min_length=1, max_length=500)
    likely_format: str = Field(min_length=1, max_length=200)
