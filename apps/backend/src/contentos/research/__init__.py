"""Auditable, immutable research-evidence primitives."""

from contentos.research.enums import (
    EvidenceType,
    ExtractionMethod,
    VerificationStatus,
)
from contentos.research.models import ResearchEvidence
from contentos.research.service import ResearchEvidenceService

__all__ = [
    "EvidenceType",
    "ExtractionMethod",
    "ResearchEvidence",
    "ResearchEvidenceService",
    "VerificationStatus",
]
