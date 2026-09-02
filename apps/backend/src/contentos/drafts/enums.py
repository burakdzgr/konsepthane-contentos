from enum import StrEnum


class DraftOrigin(StrEnum):
    """Who produced the draft content. Both origins pass the SAME gates."""

    WRITER_ENGINE = "writer_engine"
    OPERATOR = "operator"


class DraftStatus(StrEnum):
    """Minimal artifact status. Validity is a precondition of existence
    (invalid output never becomes a draft), FAILED belongs to generation
    attempts, and editorial rejection belongs to workflow decisions —
    none of those are draft statuses."""

    ACTIVE = "active"
    SUPERSEDED = "superseded"


class DraftBlockKind(StrEnum):
    """Typed content blocks of the bounded writer-draft body schema."""

    PARAGRAPH = "paragraph"
    LIST = "list"
    HOW_TO_STEP = "how_to_step"
    CALLOUT = "callout"
    FAQ_ITEM = "faq_item"
    INTERNAL_LINK_NEED = "internal_link_need"
    MEDIA_NEED = "media_need"


class DraftActorOrigin(StrEnum):
    """Who caused a draft status change (supersession)."""

    OPERATOR = "operator"
    SYSTEM = "system"
