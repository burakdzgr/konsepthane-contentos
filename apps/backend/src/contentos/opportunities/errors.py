"""Typed opportunity/promotion domain errors; transport-neutral."""


class OpportunityError(Exception):
    """Base class for opportunity domain errors."""


class InvalidPromotionInputError(OpportunityError):
    """A promotion input violates the promotion contract."""


class PromotionRootNotFoundError(OpportunityError):
    """No NormalizedDocument exists for the requested promotion root."""


class PromotionNotEligibleError(OpportunityError):
    """The Phase 2 chain does not admit promotion (ADR 0008 gate)."""


class PromotionConflictError(OpportunityError):
    """A durable promotion exists with incompatible semantics; nothing was overwritten."""
