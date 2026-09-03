"""Typed intake-run errors."""


class IntakeError(Exception):
    """Base class for intake orchestration failures."""


class IntakeRunNotFoundError(IntakeError):
    pass


class IntakeSourceNotEligibleError(IntakeError):
    """The source cannot run autonomous intake (missing, inactive, or
    without an automated discovery strategy)."""


class IntakeRunConflictError(IntakeError):
    """A live (running or paused) run already exists for the source."""


class IntakeRunStateError(IntakeError):
    """The requested control does not apply to the run's current status."""
