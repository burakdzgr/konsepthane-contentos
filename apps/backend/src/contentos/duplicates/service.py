"""Validated idempotent orchestration and persistence for duplicate decisions."""

import math
import uuid
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from contentos.duplicates.engine import DuplicateEngine, DuplicateEngineV1
from contentos.duplicates.enums import DuplicateDecisionOutcome
from contentos.duplicates.models import DuplicateDecision
from contentos.duplicates.repository import (
    DuplicateCandidateRepository,
    DuplicateDecisionRepository,
)
from contentos.duplicates.signals import DuplicateEvaluation
from contentos.normalization.enums import NormalizationStatus

MAX_ENGINE_NAME_LENGTH = 100
MAX_ENGINE_VERSION_LENGTH = 100
MAX_JSON_DEPTH = 8
MAX_JSON_ITEMS = 2_000
MAX_JSON_STRING_LENGTH = 20_000

_SEMANTIC_FIELDS = (
    "normalized_document_id",
    "engine_name",
    "engine_version",
    "decision",
    "signals",
    "thresholds",
    "matches",
    "rationale_codes",
)


class DuplicateDecisionError(Exception):
    """Base class for typed duplicate-decision failures."""


class DuplicateDocumentNotFoundError(DuplicateDecisionError):
    """The requested normalized document does not exist."""


class DuplicateDocumentNotEligibleError(DuplicateDecisionError):
    """Only successful complete normalized documents may be evaluated."""


class InvalidDuplicateEvaluationError(DuplicateDecisionError):
    """Engine identity or output violated the durable decision contract."""


class DuplicateDecisionConflictError(DuplicateDecisionError):
    """The same document/engine identity already has different immutable output."""


class DuplicateDecisionPersistenceError(DuplicateDecisionError):
    """The database refused a duplicate-decision recording operation."""


class DuplicateDecisionService:
    """Evaluate one local normalized document and flush one immutable decision."""

    def __init__(self, session: Session, engine: DuplicateEngine | None = None) -> None:
        self._session = session
        self._engine = engine or DuplicateEngineV1()
        self._decisions = DuplicateDecisionRepository(session)
        self._candidates = DuplicateCandidateRepository(session)

    def evaluate_and_record(self, normalized_document_id: uuid.UUID) -> DuplicateDecision:
        """Run the bounded local engine and flush without committing."""
        target = self._candidates.get_document(normalized_document_id)
        if target is None:
            raise DuplicateDocumentNotFoundError(
                f"no normalized document with id {normalized_document_id}"
            )
        if (
            target.normalization_status is not NormalizationStatus.SUCCEEDED
            or not target.content_fingerprint
            or not target.clean_text
        ):
            raise DuplicateDocumentNotEligibleError(
                "duplicate evaluation requires a successful fingerprinted normalized document"
            )
        engine_name = _validate_identity("engine_name", self._engine.name, MAX_ENGINE_NAME_LENGTH)
        engine_version = _validate_identity(
            "engine_version", self._engine.version, MAX_ENGINE_VERSION_LENGTH
        )
        _validate_thresholds(self._engine.thresholds)
        existing = self._decisions.get_by_document_and_engine(
            normalized_document_id,
            engine_name,
            engine_version,
        )
        if existing is not None:
            return existing
        candidates = self._candidates.list_candidates(
            target,
            limit=self._engine.thresholds.max_candidate_documents,
        )
        evaluation = self._engine.evaluate(target, candidates)
        if evaluation.thresholds != self._engine.thresholds:
            raise InvalidDuplicateEvaluationError(
                "evaluation thresholds differ from the engine threshold contract"
            )
        candidate = _decision_from_evaluation(
            normalized_document_id,
            engine_name,
            engine_version,
            evaluation,
        )
        return self._record(candidate)

    def _record(self, candidate: DuplicateDecision) -> DuplicateDecision:
        existing = self._decisions.get_by_document_and_engine(
            candidate.normalized_document_id,
            candidate.engine_name,
            candidate.engine_version,
        )
        if existing is not None:
            return _resolve_existing(existing, candidate)
        try:
            with self._session.begin_nested():
                return self._decisions.add(candidate)
        except IntegrityError:
            winner = self._decisions.get_by_document_and_engine(
                candidate.normalized_document_id,
                candidate.engine_name,
                candidate.engine_version,
            )
            if winner is not None:
                return _resolve_existing(winner, candidate)
            raise DuplicateDecisionPersistenceError(
                "database rejected duplicate decision"
            ) from None
        except SQLAlchemyError:
            raise DuplicateDecisionPersistenceError(
                "database rejected duplicate decision"
            ) from None


def _decision_from_evaluation(
    normalized_document_id: uuid.UUID,
    engine_name: str,
    engine_version: str,
    evaluation: DuplicateEvaluation,
) -> DuplicateDecision:
    if not isinstance(evaluation.decision, DuplicateDecisionOutcome):
        raise InvalidDuplicateEvaluationError("decision must be an approved outcome")
    thresholds = asdict(evaluation.thresholds)
    signals = asdict(evaluation.signals)
    matches = [
        {
            **asdict(match),
            "normalized_document_id": str(match.normalized_document_id),
            "fetch_snapshot_id": str(match.fetch_snapshot_id),
            "discovery_item_id": str(match.discovery_item_id),
            "rationale_codes": list(match.rationale_codes),
        }
        for match in evaluation.matches
    ]
    rationale_codes = list(evaluation.rationale_codes)
    if len(matches) > evaluation.thresholds.max_stored_matches:
        raise InvalidDuplicateEvaluationError("matches exceed the engine threshold limit")
    if len(rationale_codes) > evaluation.thresholds.max_rationale_codes:
        raise InvalidDuplicateEvaluationError("rationale codes exceed the engine threshold limit")
    _validate_json("signals", signals, dict)
    _validate_json("thresholds", thresholds, dict)
    _validate_json("matches", matches, list)
    _validate_json("rationale_codes", rationale_codes, list)
    return DuplicateDecision(
        normalized_document_id=normalized_document_id,
        engine_name=engine_name,
        engine_version=engine_version,
        decision=evaluation.decision,
        signals=deepcopy(signals),
        thresholds=deepcopy(thresholds),
        matches=deepcopy(matches),
        rationale_codes=deepcopy(rationale_codes),
        evaluated_at=datetime.now(UTC),
    )


def _validate_identity(name: str, value: str, limit: int) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise InvalidDuplicateEvaluationError(f"{name} must not be empty")
    if len(cleaned) > limit:
        raise InvalidDuplicateEvaluationError(f"{name} exceeds the persistence limit")
    return cleaned


def _validate_thresholds(thresholds: Any) -> None:
    integer_fields = (
        thresholds.max_candidate_documents,
        thresholds.max_lexical_text_chars,
        thresholds.max_tokens,
        thresholds.max_stored_matches,
        thresholds.max_rationale_codes,
    )
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value <= 0
        for value in integer_fields
    ):
        raise InvalidDuplicateEvaluationError("engine limits must be positive integers")
    scores = (
        thresholds.duplicate_title_similarity,
        thresholds.duplicate_lexical_similarity,
        thresholds.related_title_similarity,
        thresholds.related_lexical_similarity,
        thresholds.related_title_lexical_floor,
    )
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0 <= value <= 1
        for value in scores
    ):
        raise InvalidDuplicateEvaluationError("engine similarity thresholds must be finite 0..1")
    if (
        thresholds.duplicate_title_similarity < thresholds.related_title_similarity
        or thresholds.duplicate_lexical_similarity < thresholds.related_lexical_similarity
        or thresholds.related_title_lexical_floor > thresholds.related_lexical_similarity
    ):
        raise InvalidDuplicateEvaluationError("engine threshold bands are inconsistent")


def _resolve_existing(
    existing: DuplicateDecision,
    candidate: DuplicateDecision,
) -> DuplicateDecision:
    if all(getattr(existing, field) == getattr(candidate, field) for field in _SEMANTIC_FIELDS):
        return existing
    raise DuplicateDecisionConflictError(
        "engine identity already exists with different duplicate-decision output"
    )


def _validate_json(
    name: str,
    value: Any,
    expected_root: type[list[Any]] | type[dict[str, Any]],
) -> None:
    if not isinstance(value, expected_root):
        raise InvalidDuplicateEvaluationError(f"{name} has the wrong JSON container type")
    item_count = 0

    def walk(node: Any, depth: int) -> None:
        nonlocal item_count
        if depth > MAX_JSON_DEPTH:
            raise InvalidDuplicateEvaluationError(f"{name} exceeds the JSON depth limit")
        if isinstance(node, dict):
            item_count += len(node)
            for key, child in node.items():
                if not isinstance(key, str) or len(key) > MAX_JSON_STRING_LENGTH:
                    raise InvalidDuplicateEvaluationError(f"{name} contains an invalid JSON key")
                walk(child, depth + 1)
        elif isinstance(node, list):
            item_count += len(node)
            for child in node:
                walk(child, depth + 1)
        elif isinstance(node, str):
            if len(node) > MAX_JSON_STRING_LENGTH:
                raise InvalidDuplicateEvaluationError(f"{name} contains an oversized JSON string")
        elif isinstance(node, float):
            if not math.isfinite(node):
                raise InvalidDuplicateEvaluationError(f"{name} contains a non-finite number")
        elif node is not None and not isinstance(node, (bool, int)):
            raise InvalidDuplicateEvaluationError(f"{name} contains a non-JSON value")
        if item_count > MAX_JSON_ITEMS:
            raise InvalidDuplicateEvaluationError(f"{name} exceeds the JSON item limit")

    walk(value, 1)
