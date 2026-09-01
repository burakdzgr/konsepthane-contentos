"""Typed search-signal domain errors; transport-neutral."""


class SignalError(Exception):
    """Base class for search-signal domain errors."""


class InvalidSignalInputError(SignalError):
    """Subject, locale/market, timestamps, or confidence violate the contract."""


class UnsupportedSignalValueError(SignalError):
    """The value payload does not satisfy the signal type's v1 schema."""


class SignalConflictError(SignalError):
    """A concurrent identical-identity write conflicted and could not be recovered."""
