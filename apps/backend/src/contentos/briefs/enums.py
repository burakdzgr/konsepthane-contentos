"""Brief vocabulary. Values are persistence contracts; never rename."""

from enum import StrEnum


class BriefStatus(StrEnum):
    """Lifecycle of one immutable brief version.

    ACCEPTED_FOR_DRAFTING is an editorial decision — the only artifact the
    future Phase 4 Writer may receive. It is NEVER publication approval,
    human review, or scheduling (ADR 0004's gate stays untouched and later).
    """

    DRAFT = "draft"
    ACCEPTED_FOR_DRAFTING = "accepted_for_drafting"
    SUPERSEDED = "superseded"


class BriefClaimKind(StrEnum):
    """The accepted claim classification (design §9.2).

    Deliberately NO STATISTIC kind: statistics are an evidence TYPE
    (ResearchEvidence.STATISTIC), not a claim classification — and no regex
    pretends to identify every statistical statement.
    """

    FACTUAL = "factual"
    SOURCE_ASSERTION = "source_assertion"
    OBSERVATION = "observation"
    INFERENCE = "inference"
    EDITORIAL_JUDGMENT = "editorial_judgment"
    INSTRUCTION = "instruction"


class BriefActorOrigin(StrEnum):
    """Who performed a brief status action (operator-only phase)."""

    OPERATOR = "operator"


class StructureGuardOutcome(StrEnum):
    """Deterministic structural copyright-guard result (never AI)."""

    PASSED = "passed"
    FAILED = "failed"
    NOT_CHECKABLE = "not_checkable"
