"""Typed decision domain errors; transport-neutral."""


class DecisionError(Exception):
    """Base class for decision domain errors."""


class DecisionInputError(DecisionError):
    """A decision input violates the bounded contract."""


class DecisionPreconditionError(DecisionError):
    """The durable state does not admit this decision (wrong workflow
    state, missing pins, no ready QA report, or a package hash mismatch)."""


class DecisionConflictError(DecisionError):
    """Durable decision state conflicts with the request (e.g. revoking
    when no current approval exists)."""
