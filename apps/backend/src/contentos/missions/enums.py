"""Vocabulary of the research-driven idea engine.

A mission is the operator's research goal; the engine plans, searches,
synthesizes and evaluates. Every enum here is persisted as a VARCHAR-backed
CHECK constraint, so values are stable identifiers, never display text.
"""

from enum import StrEnum


class MissionStatus(StrEnum):
    DRAFT = "draft"
    QUEUED = "queued"
    RUNNING = "running"
    GROUNDING = "grounding"
    COMPLETED = "completed"
    NEEDS_MORE_RESEARCH = "needs_more_research"
    FAILED = "failed"


class MissionStage(StrEnum):
    """Operator-visible progress; each stage is committed when it starts."""

    PLANNING = "planning"
    KEYWORDS = "keywords"
    SEARCHING = "searching"
    EXTRACTING = "extracting"
    CLUSTERING = "clustering"
    EVALUATING = "evaluating"
    GROUNDING = "grounding"
    PROMOTING = "promoting"
    COMPLETED = "completed"


class SurfaceKind(StrEnum):
    REGISTERED_SOURCE = "registered_source"
    OPEN_WEB = "open_web"
    VISUAL_INSPIRATION = "visual_inspiration"
    COMMUNITY_NEED = "community_need"
    TREND_MARKET = "trend_market"


class CandidateKind(StrEnum):
    EXTRACTED = "extracted"
    SYNTHESIZED = "synthesized"


class CandidateRecommendation(StrEnum):
    PROMOTE = "promote"
    CONTINUE_RESEARCH = "continue_research"
    ELIMINATE = "eliminate"
    MERGED = "merged"


class IdeaConfidence(StrEnum):
    """Creative confidence — never a statement about verifiable facts."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class FactualEvidenceConfidence(StrEnum):
    """Separate axis: only the evidence pipeline can raise it above UNKNOWN."""

    UNKNOWN = "unknown"
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
