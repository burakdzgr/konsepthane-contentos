"""Deterministic, local-only, pre-AI duplicate engine v1."""

from dataclasses import dataclass
from typing import Protocol

from contentos.duplicates.enums import DuplicateDecisionOutcome
from contentos.duplicates.signals import (
    V1_THRESHOLDS,
    ComparisonDocument,
    DuplicateEvaluation,
    DuplicateMatch,
    DuplicateSignals,
    DuplicateThresholds,
    lexical_similarity,
    title_similarity,
)

DUPLICATE_ENGINE_NAME = "duplicate-engine"
DUPLICATE_ENGINE_VERSION = "1"

_EXACT_FINGERPRINT = "exact_content_fingerprint"
_EXACT_RAW_BODY = "exact_raw_body"
_SAME_CANONICAL_CHANGED = "same_canonical_url_changed_content"
_SAME_FINAL_CHANGED = "same_final_url_changed_content"
_HIGH_FUZZY = "high_title_and_lexical_similarity"
_RELATED_LEXICAL = "related_lexical_similarity"
_RELATED_TITLE = "related_title_and_lexical_similarity"
_NO_OVERLAP = "no_material_overlap"


class DuplicateEngine(Protocol):
    """Versioned deterministic evaluator contract used by the persistence service."""

    name: str
    version: str
    thresholds: DuplicateThresholds

    def evaluate(
        self,
        target: ComparisonDocument,
        candidates: tuple[ComparisonDocument, ...],
    ) -> DuplicateEvaluation: ...


@dataclass(frozen=True, slots=True)
class _ScoredCandidate:
    priority: int
    match: DuplicateMatch


class DuplicateEngineV1:
    """Transparent v1 policy using exact identity plus bounded text metrics."""

    name = DUPLICATE_ENGINE_NAME
    version = DUPLICATE_ENGINE_VERSION

    def __init__(self, thresholds: DuplicateThresholds = V1_THRESHOLDS) -> None:
        self.thresholds = thresholds

    def evaluate(
        self,
        target: ComparisonDocument,
        candidates: tuple[ComparisonDocument, ...],
    ) -> DuplicateEvaluation:
        scored = tuple(self._score(target, candidate) for candidate in candidates)
        exact_fingerprint_count = sum(
            candidate.match.exact_content_fingerprint for candidate in scored
        )
        exact_raw_count = sum(candidate.match.exact_raw_body for candidate in scored)
        exact_canonical_count = sum(candidate.match.exact_canonical_url for candidate in scored)
        exact_final_count = sum(candidate.match.exact_final_url for candidate in scored)
        ranked = sorted(
            (candidate for candidate in scored if candidate.priority > 0),
            key=lambda candidate: (
                -candidate.priority,
                -candidate.match.lexical_similarity,
                -candidate.match.title_similarity,
                str(candidate.match.normalized_document_id),
            ),
        )
        best = ranked[0] if ranked else None
        decision = _decision_for_priority(best.priority if best is not None else 0)
        rationale = best.match.rationale_codes if best is not None else (_NO_OVERLAP,)
        return DuplicateEvaluation(
            decision=decision,
            signals=DuplicateSignals(
                candidate_count=len(candidates),
                exact_canonical_url_matches=exact_canonical_count,
                exact_final_url_matches=exact_final_count,
                exact_raw_body_matches=exact_raw_count,
                exact_content_fingerprint_matches=exact_fingerprint_count,
                highest_title_similarity=max(
                    (candidate.match.title_similarity for candidate in scored), default=0.0
                ),
                highest_lexical_similarity=max(
                    (candidate.match.lexical_similarity for candidate in scored), default=0.0
                ),
            ),
            thresholds=self.thresholds,
            matches=tuple(
                candidate.match for candidate in ranked[: self.thresholds.max_stored_matches]
            ),
            rationale_codes=rationale[: self.thresholds.max_rationale_codes],
        )

    def _score(
        self,
        target: ComparisonDocument,
        candidate: ComparisonDocument,
    ) -> _ScoredCandidate:
        exact_fingerprint = (
            target.content_fingerprint is not None
            and target.content_fingerprint == candidate.content_fingerprint
        )
        exact_raw = (
            target.raw_body_sha256 is not None
            and target.raw_body_sha256 == candidate.raw_body_sha256
        )
        exact_canonical = target.canonical_url == candidate.canonical_url
        exact_final = target.final_url is not None and target.final_url == candidate.final_url
        title_score = title_similarity(target.title, candidate.title)
        lexical_score = lexical_similarity(
            target.clean_text,
            candidate.clean_text,
            max_chars=self.thresholds.max_lexical_text_chars,
            max_tokens=self.thresholds.max_tokens,
        )
        priority, reasons = self._classify(
            exact_fingerprint=exact_fingerprint,
            exact_raw=exact_raw,
            exact_canonical=exact_canonical,
            exact_final=exact_final,
            title_score=title_score,
            lexical_score=lexical_score,
        )
        return _ScoredCandidate(
            priority=priority,
            match=DuplicateMatch(
                normalized_document_id=candidate.normalized_document_id,
                fetch_snapshot_id=candidate.fetch_snapshot_id,
                discovery_item_id=candidate.discovery_item_id,
                exact_canonical_url=exact_canonical,
                exact_final_url=exact_final,
                exact_raw_body=exact_raw,
                exact_content_fingerprint=exact_fingerprint,
                title_similarity=title_score,
                lexical_similarity=lexical_score,
                rationale_codes=reasons,
            ),
        )

    def _classify(
        self,
        *,
        exact_fingerprint: bool,
        exact_raw: bool,
        exact_canonical: bool,
        exact_final: bool,
        title_score: float,
        lexical_score: float,
    ) -> tuple[int, tuple[str, ...]]:
        if exact_fingerprint or exact_raw:
            reasons = tuple(
                code
                for matched, code in (
                    (exact_fingerprint, _EXACT_FINGERPRINT),
                    (exact_raw, _EXACT_RAW_BODY),
                )
                if matched
            )
            return 5, reasons
        if exact_canonical or exact_final:
            reasons = tuple(
                code
                for matched, code in (
                    (exact_canonical, _SAME_CANONICAL_CHANGED),
                    (exact_final, _SAME_FINAL_CHANGED),
                )
                if matched
            )
            return 4, reasons
        if (
            title_score >= self.thresholds.duplicate_title_similarity
            and lexical_score >= self.thresholds.duplicate_lexical_similarity
        ):
            return 3, (_HIGH_FUZZY,)
        if lexical_score >= self.thresholds.related_lexical_similarity:
            return 2, (_RELATED_LEXICAL,)
        if (
            title_score >= self.thresholds.related_title_similarity
            and lexical_score >= self.thresholds.related_title_lexical_floor
        ):
            return 2, (_RELATED_TITLE,)
        return 0, ()


def _decision_for_priority(priority: int) -> DuplicateDecisionOutcome:
    if priority == 5 or priority == 3:
        return DuplicateDecisionOutcome.DUPLICATE
    if priority == 4:
        return DuplicateDecisionOutcome.UPDATE_EXISTING
    if priority == 2:
        return DuplicateDecisionOutcome.RELATED
    return DuplicateDecisionOutcome.UNIQUE
