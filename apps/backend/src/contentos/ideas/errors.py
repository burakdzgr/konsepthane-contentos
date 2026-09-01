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
