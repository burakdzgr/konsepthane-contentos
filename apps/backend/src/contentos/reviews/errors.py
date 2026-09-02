"""Typed editor-review domain errors; transport-neutral."""


class ReviewError(Exception):
    """Base class for editor-review domain errors."""


class ReviewInputError(ReviewError):
    """A finding or review input violates the bounded editor-review contract."""


class ReviewNotFoundError(ReviewError):
    """No editorial review exists for the given identity."""


class ReviewPreconditionError(ReviewError):
    """The durable workflow/draft/brief state does not admit review creation
    (work item not in EDITING, no pinned draft in the entry event, no active
    draft, or the brief is no longer the accepted writing contract)."""


class InvalidReviewAttemptError(ReviewError):
    """The supplied generation attempt cannot legitimately back this review
    (wrong purpose, not SUCCEEDED, or pinned to different inputs)."""


class ReviewConflictError(ReviewError):
    """Durable review state conflicts with the requested creation and could
    not be resolved idempotently; nothing was overwritten."""


class ReviewStatusConflictError(ReviewError):
    """The requested status change violates the forward-only status model."""


class IncompleteReviewMaterializationError(ReviewError):
    """A SUCCEEDED editor attempt has no materialized review and its raw
    output was (by design) never persisted; recovery is an explicit new
    provider invocation with retry_number + 1."""


class ReviewGenerationMaterializationError(ReviewError):
    """Structurally valid editor output was rejected by deterministic review
    persistence; the completed attempt keeps its real SUCCEEDED status."""
