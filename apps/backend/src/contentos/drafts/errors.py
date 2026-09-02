"""Typed draft domain errors; transport-neutral."""


class DraftError(Exception):
    """Base class for draft domain errors."""


class DraftInputError(DraftError):
    """A draft body/input violates the bounded writer-draft-body contract."""


class DraftNotFoundError(DraftError):
    """No content draft exists for the given identity."""


class DraftPreconditionError(DraftError):
    """The pinned upstream contract does not admit draft creation
    (brief missing, not ACCEPTED_FOR_DRAFTING, or superseded)."""


class InvalidDraftAttemptError(DraftError):
    """The supplied generation attempt cannot legitimately back this draft
    (wrong purpose, not SUCCEEDED, or pinned to a different brief)."""


class DraftPolicyViolationError(DraftError):
    """A deterministic Writer-stage policy gate failed (numeric assertion
    without claim binding, missing/unknown handling coverage, framing
    violation, or a verbatim-overlap breach); no draft row is created."""


class DraftConflictError(DraftError):
    """Durable draft state conflicts with the requested creation and could
    not be resolved idempotently; nothing was overwritten."""


class DraftStatusConflictError(DraftError):
    """The requested status change violates the forward-only status model."""
