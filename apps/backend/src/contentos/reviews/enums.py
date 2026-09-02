"""Editor review vocabularies. Values are persistence contracts; never rename."""

from enum import StrEnum


class ReviewVerdict(StrEnum):
    """Computed by the deterministic verdict policy — never model-authored,
    and never a rejection (REJECTED is an exclusively human decision)."""

    PASS = "pass"
    REVISE = "revise"


class ReviewStatus(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"


class FindingDimension(StrEnum):
    """What one finding is about (PHASE4_EDITOR_ARCHITECTURE.md §4)."""

    CLAIM_FAITHFULNESS = "claim_faithfulness"
    EXCLUSION_COMPLIANCE = "exclusion_compliance"
    OBJECTIVE_FIT = "objective_fit"
    CLARITY_STYLE = "clarity_style"
    UNCERTAINTY_FRAMING = "uncertainty_framing"


class FindingSeverity(StrEnum):
    BLOCKING = "blocking"
    MAJOR = "major"
    MINOR = "minor"


class FindingOrigin(StrEnum):
    """Where a finding came from: the model-assisted review (a policy
    signal, never Evidence) or a deterministic gate recomputation."""

    MODEL_SIGNAL = "model_signal"
    DETERMINISTIC = "deterministic"


class ReviewActorOrigin(StrEnum):
    """Who caused a review status change (supersession)."""

    OPERATOR = "operator"
    SYSTEM = "system"
