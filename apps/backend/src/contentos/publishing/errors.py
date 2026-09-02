"""Typed publishing domain errors; transport-neutral."""


class PublishingError(Exception):
    """Base class for publishing domain errors."""


class PublicationInputError(PublishingError):
    """A publishing input violates the bounded contract."""


class PublicationPreconditionError(PublishingError):
    """The durable state does not admit this publishing operation
    (wrong workflow state, missing approved package parts, or unmet
    unwaived media needs)."""
