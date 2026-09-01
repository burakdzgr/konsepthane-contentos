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


class ScoreBand(StrEnum):
    """Overall opportunity strength band (the primary public contract)."""

    STRONG = "strong"
    MODERATE = "moderate"
    WEAK = "weak"
    INELIGIBLE = "ineligible"


class ScoreEligibility(StrEnum):
    """What the evaluation recommends; never a disposition mutation."""

    COMMISSIONABLE = "commissionable"
    NOT_COMMISSIONABLE = "not_commissionable"
    NEEDS_OPERATOR_REVIEW = "needs_operator_review"


class ComponentAvailability(StrEnum):
    """UNKNOWN is a first-class state and is never coerced to zero."""

    KNOWN = "known"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class ScoreComponent(StrEnum):
    """The full accepted component vocabulary (frozen now to avoid enum churn).

    Engine v1 computes only the components with a durable deterministic
    source today; everything else is explicitly persisted as UNKNOWN.
    """

    RECENCY = "recency"
    AUDIENCE_FIT = "audience_fit"
    EVIDENCE_AVAILABILITY = "evidence_availability"
    SOURCE_DIVERSITY = "source_diversity"
    SOURCE_TRUST = "source_trust"
    COMPETITION = "competition"
    SEARCH_DEMAND = "search_demand"
    EDITORIAL_VALUE = "editorial_value"
    SEASONALITY = "seasonality"
    DUPLICATE_OVERLAP_RISK = "duplicate_overlap_risk"
    POLICY_RISK = "policy_risk"
    PRODUCTION_COST_ESTIMATE = "production_cost_estimate"
