"""QA vocabularies. Values are persistence contracts; never rename."""

from enum import StrEnum


class QaOutcome(StrEnum):
    """Computed deterministically from gate results — never supplied, and
    never a rejection (REJECTED is an exclusively human decision) and
    never an execution-failure label."""

    READY_FOR_HUMAN_REVIEW = "ready_for_human_review"
    NOT_READY = "not_ready"


class QaReportStatus(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"


class QaGateKey(StrEnum):
    """The seven hard gates of qa-gates/1 (PHASE4_QA_ARCHITECTURE.md §3)."""

    PACKAGE_INTEGRITY = "package_integrity"
    PROVENANCE_CHAIN = "provenance_chain"
    WRITER_ENVELOPE = "writer_envelope"
    CONTENT_SAFETY = "content_safety"
    EDITORIAL_REVIEW_CURRENCY = "editorial_review_currency"
    MEDIA_NEEDS = "media_needs"
    INTERNAL_LINK_NEEDS = "internal_link_needs"


class WaivableGateKey(StrEnum):
    """Gates a human may explicitly waive (audited, needs stay visible).
    v1: only the media gate — nothing can evaluate media yet."""

    MEDIA_NEEDS = "media_needs"


class QaActorOrigin(StrEnum):
    """Who caused a QA report status change (supersession)."""

    OPERATOR = "operator"
    SYSTEM = "system"
