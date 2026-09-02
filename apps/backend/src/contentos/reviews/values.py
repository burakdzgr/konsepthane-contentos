"""Bounded editor-review value objects (PHASE4_EDITOR_ARCHITECTURE.md §4/§6).

A finding is a POLICY SIGNAL about one exact draft: bounded safe text,
anchored only to identities that exist in the reviewed draft (block ids,
brief claim ids). Findings never carry facts, URLs, HTML, or evidence.
"""

import re
import uuid
from dataclasses import dataclass
from typing import Any

from contentos.drafts.values import require_safe_text
from contentos.reviews.enums import FindingDimension, FindingOrigin, FindingSeverity
from contentos.reviews.errors import ReviewInputError

EDITOR_ENGINE_NAME = "editor"
EDITOR_ENGINE_VERSION = "1"

INTEGRITY_GATE_VERSION = "editor-integrity/1"

MAX_FINDINGS_PER_REVIEW = 50
MAX_FINDING_KEY_LENGTH = 64
MAX_FINDING_TEXT_LENGTH = 2000

_FINDING_KEY_PATTERN = re.compile(rf"^[a-z0-9][a-z0-9-]{{0,{MAX_FINDING_KEY_LENGTH - 1}}}$")


@dataclass(frozen=True, slots=True)
class ReviewFindingInput:
    """One typed finding; `finding_key` is the stable per-review anchor."""

    finding_key: str
    dimension: FindingDimension
    severity: FindingSeverity
    origin: FindingOrigin
    description: str
    recommendation: str | None = None
    block_id: str | None = None
    brief_claim_id: uuid.UUID | None = None

    def cleaned(self) -> dict[str, Any]:
        if not isinstance(self.dimension, FindingDimension):
            raise ReviewInputError("finding dimension must be a FindingDimension value")
        if not isinstance(self.severity, FindingSeverity):
            raise ReviewInputError("finding severity must be a FindingSeverity value")
        if not isinstance(self.origin, FindingOrigin):
            raise ReviewInputError("finding origin must be a FindingOrigin value")
        key = self.finding_key.strip() if isinstance(self.finding_key, str) else ""
        if not _FINDING_KEY_PATTERN.fullmatch(key):
            raise ReviewInputError(
                "finding_key must be a lowercase slug (a-z, 0-9, '-') of at "
                f"most {MAX_FINDING_KEY_LENGTH} characters"
            )
        description = require_safe_text(
            f"finding {key} description", self.description, MAX_FINDING_TEXT_LENGTH
        )
        recommendation: str | None = None
        if self.recommendation is not None:
            recommendation = require_safe_text(
                f"finding {key} recommendation", self.recommendation, MAX_FINDING_TEXT_LENGTH
            )
        block_id: str | None = None
        if self.block_id is not None:
            block_id = self.block_id.strip()
            if not block_id:
                raise ReviewInputError(f"finding {key}: block_id must not be blank when given")
        if self.brief_claim_id is not None and not isinstance(self.brief_claim_id, uuid.UUID):
            raise ReviewInputError(f"finding {key}: brief_claim_id must be a UUID")
        return {
            "finding_key": key,
            "dimension": self.dimension.value,
            "severity": self.severity.value,
            "origin": self.origin.value,
            "description": description,
            "recommendation": recommendation,
            "block_id": block_id,
            "brief_claim_id": str(self.brief_claim_id) if self.brief_claim_id else None,
        }
