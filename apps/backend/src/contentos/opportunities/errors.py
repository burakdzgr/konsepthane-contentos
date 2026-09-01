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


class OpportunityNotFoundError(OpportunityError):
    """No editorial opportunity exists for the given identity."""


class InvalidScoringStateError(OpportunityError):
    """The opportunity's durable inputs do not admit a scoring evaluation."""


class ScoringConflictError(OpportunityError):
    """A concurrent evaluation conflicted and could not be recovered."""
