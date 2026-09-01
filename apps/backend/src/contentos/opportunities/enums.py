"""Opportunity vocabulary. Values are persistence contracts; never rename."""

from enum import StrEnum


class OpportunityDisposition(StrEnum):
    """Operator disposition of an opportunity (never the work item's state)."""

    OPEN = "open"
    COMMISSIONED = "commissioned"
    REJECTED = "rejected"


class ResearchInputRole(StrEnum):
    """How one research input relates to the opportunity."""

    PRIMARY_SIGNAL = "primary_signal"
    SUPPORTING = "supporting"
    CONTRADICTING = "contradicting"
    CONTEXT = "context"
    UPDATE_SIGNAL = "update_signal"


class OpportunityActor(StrEnum):
    """Who attached an input or decided a disposition.

    Deliberately distinct from WorkItemOrigin and WorkflowActorOrigin, and
    never an AI provider identity.
    """

    SYSTEM = "system"
    OPERATOR = "operator"
