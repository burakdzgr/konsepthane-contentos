"""Canonical workflow vocabulary. Values are persistence contracts; never rename."""

from enum import StrEnum


class WorkflowState(StrEnum):
    """The canonical editorial state machine from docs/WORKFLOW.md.

    The full vocabulary is persisted so later phases never migrate the enum;
    Phase 3 exercises only IDEA_SCORING..BRIEFING plus the cross-cutting
    states. The early states (DISCOVERED..DUPLICATE) remain canonical
    vocabulary realized by Phase 2 artifacts — work items are never created
    in them (promotion, not replay).
    """

    DISCOVERED = "discovered"
    RESEARCHING = "researching"
    NORMALIZED = "normalized"
    DUPLICATE_CHECK = "duplicate_check"
    DUPLICATE = "duplicate"
    IDEA_SCORING = "idea_scoring"
    EVIDENCE_BUILDING = "evidence_building"
    SEO_RESEARCH = "seo_research"
    BRIEFING = "briefing"
    DRAFTING = "drafting"
    EDITING = "editing"
    QA_REVIEW = "qa_review"
    AWAITING_HUMAN_REVIEW = "awaiting_human_review"
    APPROVED = "approved"
    SCHEDULED = "scheduled"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    PINTEREST_PENDING = "pinterest_pending"
    DISTRIBUTED = "distributed"
    MEASURING = "measuring"
    REFRESH_CANDIDATE = "refresh_candidate"
    CHANGES_REQUESTED = "changes_requested"
    BLOCKED = "blocked"
    APPROVAL_EXPIRED = "approval_expired"
    REJECTED = "rejected"
    ARCHIVED = "archived"


class WorkItemOrigin(StrEnum):
    """How an EditorialWorkItem came to exist."""

    RESEARCH_INTAKE = "research_intake"
    OPERATOR = "operator"


class WorkflowActorOrigin(StrEnum):
    """Who or what caused one workflow transition (never queue/provider state)."""

    OPERATOR = "operator"
    SYSTEM = "system"
