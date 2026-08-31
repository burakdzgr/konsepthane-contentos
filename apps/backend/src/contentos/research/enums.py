"""Frozen persisted vocabulary for research evidence."""

from enum import StrEnum


class EvidenceType(StrEnum):
    """Durable evidence categories approved by the Phase 2 design."""

    SOURCE_ASSERTION = "source_assertion"
    OBSERVATION = "observation"
    STATISTIC = "statistic"
    QUOTE = "quote"
    INSTRUCTION = "instruction"


class ExtractionMethod(StrEnum):
    """Who or what extracted the evidence; MACHINE currently means deterministic code."""

    MACHINE = "machine"
    HUMAN = "human"


class VerificationStatus(StrEnum):
    """Recorded review state; VERIFIED means exact grounding, not factual truth."""

    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    DISPUTED = "disputed"
    RETRACTED = "retracted"
