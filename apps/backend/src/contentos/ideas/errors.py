"""Typed transport-neutral idea domain errors."""


class IdeaError(Exception):
    """Base class for idea domain failures."""


class IdeaNotFoundError(IdeaError):
    """No idea version exists with the given identity."""


class InvalidIdeaInputError(IdeaError):
    """A caller-supplied idea field violates the domain contract."""


class InvalidPlanningDimensionsError(InvalidIdeaInputError):
    """planning_dimensions violates the bounded versioned schema."""


class FakeUgcRejectionError(IdeaError):
    """Idea text claims user-generated content that has no real provenance.

    Phase 3 has no UGC ingestion, so such ideas are rejected
    deterministically and no idea row is persisted.
    """


class IdeaRevisionConflictError(IdeaError):
    """A concurrent revision won the version allocation race."""


class InvalidSelectionError(IdeaError):
    """A selection command carries invalid input."""


class SelectionConflictError(IdeaError):
    """The selection command contradicts the current effective selection."""


class IdeaGenerationError(IdeaError):
    """Base class for model-assisted idea generation failures."""


class OpportunityNotCommissionedError(IdeaGenerationError):
    """Idea generation runs only on a COMMISSIONED opportunity (design §18).

    The engine validates the precondition and NEVER commissions anything
    itself — commissioning stays a separate future operator command.
    """


class InvalidGenerationAttemptError(IdeaGenerationError):
    """The referenced attempt cannot back model-assisted ideas.

    Raised when purpose is not IDEA_CANDIDATES, status is not SUCCEEDED, or
    the attempt's persisted input provenance does not match this
    opportunity/generator context — the FK alone is never trusted.
    """


class IncompleteMaterializationError(IdeaGenerationError):
    """A reused SUCCEEDED attempt has no linked ideas and no payload.

    Raw model output is deliberately never persisted, and the provider must
    not be re-invoked under the exact same attempt identity — request a new
    provider invocation explicitly with retry_number + 1.
    """
