"""AI-boundary vocabulary. Values are persistence contracts; never rename."""

from enum import StrEnum


class GenerationPurpose(StrEnum):
    """WHY the model was called — never which provider was used."""

    IDEA_CANDIDATES = "idea_candidates"
    INTENT_SYNTHESIS = "intent_synthesis"
    BRIEF_COMPOSITION = "brief_composition"
    EVIDENCE_ORGANIZATION = "evidence_organization"


class GenerationStatus(StrEnum):
    """Outcome of ONE provider attempt.

    These are execution facts, never editorial or workflow decisions:
    there is no approved/rejected/blocked here, and no status ever
    transitions an EditorialWorkItem.
    """

    SUCCEEDED = "succeeded"
    VALIDATION_FAILED = "validation_failed"
    PROVIDER_ERROR = "provider_error"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class ProviderFailureKind(StrEnum):
    """Provider-neutral failure classes an adapter may raise.

    Future adapters translate SDK/provider failures into this contract;
    SDK exception objects never cross the boundary.
    """

    PROVIDER_ERROR = "provider_error"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
