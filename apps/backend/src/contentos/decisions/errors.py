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


class StaleApprovalError(DecisionError):
    """The approval on record does not cover the ACTIVE draft (missing,
    revoked, or hash-stale). The guard every approval consumer (the
    future scheduling/publishing phase) must pass — a stale approval is
    surfaced, never ridden."""
