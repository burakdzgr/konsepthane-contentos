"""Typed operational-control errors."""

from contentos.operations.enums import PauseScope


class OperationsError(Exception):
    """Base class for operational-control failures."""


class IntakePausedError(OperationsError):
    """Dispatch was refused because an intake pause gates this scope.

    An EXECUTION condition: nothing was queued, no workflow state moved,
    and no editorial meaning is implied.
    """

    def __init__(self, scope: PauseScope, reason: str) -> None:
        self.scope = scope
        self.reason = reason
        super().__init__(f"intake paused ({scope.value}): {reason}")
