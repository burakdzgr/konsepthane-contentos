"""Stable duplicate-decision vocabulary."""

from enum import StrEnum


class DuplicateDecisionOutcome(StrEnum):
    """Approved Phase 2 outcomes; persisted as stable lowercase values."""

    UNIQUE = "unique"
    RELATED = "related"
    UPDATE_EXISTING = "update_existing"
    DUPLICATE = "duplicate"
    REJECT = "reject"
