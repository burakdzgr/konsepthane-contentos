"""Deterministic originality guards (design §5.3).

These are deterministic protections, NOT a plagiarism oracle: they cannot
detect every semantic paraphrase or translation. Everything they do record
is explainable — the exact policy snapshot travels with each idea version.

The mandatory-angle/rationale guard is enforced as domain validation (an
idea without a stated original angle is invalid); the fake-UGC guard is a
hard deterministic rejection performed before any row exists.
"""

import uuid
from dataclasses import dataclass
from typing import Any

from contentos.duplicates.signals import TITLE_SIMILARITY_METRIC, title_similarity
from contentos.ideas.enums import OriginalityStatus
from contentos.ideas.policy import IdeaOriginalityPolicy


@dataclass(frozen=True, slots=True)
class InputTitle:
    """One admitted input document's title (None when the document has none)."""

    normalized_document_id: uuid.UUID
    title: str | None


@dataclass(frozen=True, slots=True)
class OriginalityEvaluation:
    """Immutable aggregate result persisted on the idea version."""

    status: OriginalityStatus
    detail: dict[str, Any]


def find_fake_ugc_violations(
    fields: dict[str, str], policy: IdeaOriginalityPolicy
) -> list[dict[str, str]]:
    """Deterministic policy-list scan of idea text fields.

    Whitespace-normalized casefolded substring matching only — bounded,
    versioned, and honest about being literal.
    """
    violations: list[dict[str, str]] = []
    for field_name, text in fields.items():
        haystack = " ".join(text.split()).casefold()
        for pattern in policy.fake_ugc_patterns:
            if pattern.casefold() in haystack:
                violations.append({"field": field_name, "pattern": pattern})
    return violations


def evaluate_originality(
    *,
    working_title: str,
    input_titles: list[InputTitle],
    distinct_source_count: int,
    policy: IdeaOriginalityPolicy,
) -> OriginalityEvaluation:
    """Run the deterministic recorded checks and aggregate honestly.

    Aggregation: any failed check -> FAILED; otherwise any not-checkable
    check -> NOT_CHECKABLE (never silently PASS); otherwise PASSED.
    """
    source_check = _source_diversity_check(distinct_source_count, policy)
    title_check = _title_similarity_check(working_title, input_titles, policy)
    fake_ugc_check = {
        # A violation is a hard rejection before persistence, so a stored
        # idea always records this guard as passed for its policy version.
        "status": "passed",
        "patterns_checked": len(policy.fake_ugc_patterns),
    }

    statuses = (source_check["status"], title_check["status"])
    if "failed" in statuses:
        status = OriginalityStatus.FAILED
    elif "not_checkable" in statuses:
        status = OriginalityStatus.NOT_CHECKABLE
    else:
        status = OriginalityStatus.PASSED

    return OriginalityEvaluation(
        status=status,
        detail={
            "checks": {
                "source_diversity": source_check,
                "title_similarity": title_check,
                "fake_ugc": fake_ugc_check,
            }
        },
    )


def _source_diversity_check(
    distinct_source_count: int, policy: IdeaOriginalityPolicy
) -> dict[str, Any]:
    passed = distinct_source_count >= policy.min_distinct_sources
    return {
        "status": "passed" if passed else "failed",
        "distinct_sources": distinct_source_count,
        "required": policy.min_distinct_sources,
    }


def _title_similarity_check(
    working_title: str,
    input_titles: list[InputTitle],
    policy: IdeaOriginalityPolicy,
) -> dict[str, Any]:
    usable = [entry for entry in input_titles if entry.title is not None and entry.title.strip()]
    skipped = sorted(
        str(entry.normalized_document_id)
        for entry in input_titles
        if entry.title is None or not entry.title.strip()
    )
    if not usable:
        return {
            "status": "not_checkable",
            "titles_checked": 0,
            "skipped_documents": skipped,
            "max_similarity": None,
            "most_similar_document_id": None,
            "threshold": policy.title_similarity_failure_threshold,
            "metric": TITLE_SIMILARITY_METRIC,
        }

    max_similarity = -1.0
    most_similar: uuid.UUID | None = None
    for entry in usable:
        similarity = title_similarity(working_title, entry.title)
        if similarity > max_similarity:
            max_similarity = similarity
            most_similar = entry.normalized_document_id
    failed = max_similarity >= policy.title_similarity_failure_threshold
    return {
        "status": "failed" if failed else "passed",
        "titles_checked": len(usable),
        "skipped_documents": skipped,
        "max_similarity": max_similarity,
        "most_similar_document_id": str(most_similar),
        "threshold": policy.title_similarity_failure_threshold,
        "metric": TITLE_SIMILARITY_METRIC,
    }
