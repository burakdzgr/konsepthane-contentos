"""Idea vocabulary. Values are persistence contracts; never rename."""

from enum import StrEnum


class ContentType(StrEnum):
    """The accepted controlled initial content-type vocabulary (design §13.1).

    An idea-level editorial choice: never inferred from a single source
    article, never free text. Extension is a migration-time vocabulary
    addition.
    """

    GUIDE = "guide"
    IDEA_LIST = "idea_list"
    CHECKLIST = "checklist"
    PLANNING_GUIDE = "planning_guide"
    COMPARISON = "comparison"
    FAQ = "faq"
    HOW_TO = "how_to"
    INSPIRATION = "inspiration"


class IdeaOrigin(StrEnum):
    """Who authored this idea version.

    Task 7 deliberately contains ONLY the operator origin: MODEL_ASSISTED
    arrives with the AI-boundary task's own migration together with the real
    ai_generation_attempts FK, so fake model provenance is impossible today.
    This is dependency-safe staged implementation, not a design change.
    """

    OPERATOR = "operator"


class OriginalityStatus(StrEnum):
    """Aggregate deterministic originality result for one idea version.

    NOT_CHECKABLE is a first-class state: "could not evaluate" is never
    silently promoted to a pass.
    """

    PASSED = "passed"
    FAILED = "failed"
    NOT_CHECKABLE = "not_checkable"


class IdeaSelectionAction(StrEnum):
    """Selection is an operator editorial decision — NEVER publication
    approval (ADR 0004 untouched)."""

    SELECTED = "selected"
    DESELECTED = "deselected"


class IdeaSelectionActor(StrEnum):
    """Who performed a selection action (operator only in Phase 3)."""

    OPERATOR = "operator"
