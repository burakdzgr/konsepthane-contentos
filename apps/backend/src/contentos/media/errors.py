"""Typed media domain errors; transport-neutral."""


class MediaError(Exception):
    """Base class for media domain errors."""


class MediaInputError(MediaError):
    """A media input violates the bounded contract (size, type, missing
    required accessibility/licensing fields, unknown need index)."""


class MediaPreconditionError(MediaError):
    """The durable state does not admit this media operation (missing
    work item/brief/asset, or a workflow state outside the permitted
    media window)."""


class MediaConflictError(MediaError):
    """Durable media state conflicts with the request (e.g. unsatisfying
    a need that has no active satisfaction)."""
