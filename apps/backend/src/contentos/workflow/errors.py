"""Typed workflow domain errors; the layer stays transport-neutral."""


class WorkflowError(Exception):
    """Base class for editorial workflow domain errors."""


class InvalidWorkflowInputError(WorkflowError):
    """A creation/transition input violates the workflow contract."""


class WorkItemNotFoundError(WorkflowError):
    """No editorial work item exists for the given identity."""


class InvalidWorkflowTransitionError(WorkflowError):
    """The requested transition is not structurally allowed from the actual state."""
