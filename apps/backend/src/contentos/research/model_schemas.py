"""Versioned structured-output schema for model-assisted evidence extraction.

The model proposes ONLY candidate statements with the verbatim span they
rest on. It can never supply identities, provenance, verification status,
confidence or roles — those are deterministic, system-owned. Every
candidate is re-validated against the normalized text before anything is
persisted: an excerpt that is not an exact contiguous span of the source
text is rejected, never "corrected".
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

EVIDENCE_CANDIDATE_SCHEMA_NAME = "evidence-candidate-batch"
EVIDENCE_CANDIDATE_SCHEMA_VERSION = "1"
MAX_MODEL_CANDIDATES = 8
MAX_CANDIDATE_STATEMENT_LENGTH = 600
MAX_CANDIDATE_EXCERPT_LENGTH = 400
MAX_CANDIDATE_BASIS_LENGTH = 300

EvidenceCandidateType = Literal["statistic", "instruction", "source_assertion", "quote"]


class EvidenceCandidateV1(BaseModel):
    """One model-proposed statement grounded in one verbatim excerpt."""

    model_config = ConfigDict(extra="forbid")

    evidence_type: EvidenceCandidateType
    statement: str = Field(min_length=1, max_length=MAX_CANDIDATE_STATEMENT_LENGTH)
    excerpt: str = Field(min_length=1, max_length=MAX_CANDIDATE_EXCERPT_LENGTH)
    basis: str = Field(min_length=1, max_length=MAX_CANDIDATE_BASIS_LENGTH)


class EvidenceCandidateBatchV1(BaseModel):
    """The complete structured generation result: candidates only (may be empty)."""

    model_config = ConfigDict(extra="forbid")

    candidates: list[EvidenceCandidateV1] = Field(max_length=MAX_MODEL_CANDIDATES)
