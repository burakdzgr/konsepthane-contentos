"""Validated, idempotent recording of immutable normalized documents."""

import hashlib
import math
import re
import uuid
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from contentos.fetching.models import FetchOutcome
from contentos.fetching.snapshot_repository import FetchSnapshotRepository
from contentos.fetching.snapshots import FetchSnapshot
from contentos.normalization.enums import NormalizationFailureCode, NormalizationStatus
from contentos.normalization.models import NormalizedDocument
from contentos.normalization.repository import NormalizedDocumentRepository

NORMALIZED_CONTENT_FINGERPRINT_VERSION = 1
MAX_EXTRACTOR_NAME_LENGTH = 100
MAX_EXTRACTOR_VERSION_LENGTH = 100
MAX_PARSER_VERSION_LENGTH = 100
MAX_TITLE_LENGTH = 500
MAX_LANGUAGE_LENGTH = 35
MAX_AUTHOR_NAME_LENGTH = 300
MAX_CLEAN_TEXT_LENGTH = 2_000_000
MAX_FAILURE_DETAIL_LENGTH = 1_000
MAX_JSON_DEPTH = 8
MAX_JSON_ITEMS = 2_000
MAX_JSON_STRING_LENGTH = 20_000

_WHITESPACE = re.compile(r"\s+")
_SEMANTIC_FIELDS = (
    "fetch_snapshot_id",
    "extractor_name",
    "extractor_version",
    "parser_version",
    "normalization_status",
    "failure_code",
    "failure_detail",
    "title",
    "clean_text",
    "language",
    "author_name",
    "external_published_at",
    "headings",
    "sections",
    "links",
    "structured_metadata",
    "content_fingerprint",
    "fingerprint_version",
)


class NormalizationError(Exception):
    """Base class for normalized-document recording failures."""


class FetchSnapshotNotFoundError(NormalizationError):
    """The requested FetchSnapshot does not exist."""


class FetchSnapshotNotEligibleError(NormalizationError):
    """The snapshot is not a reproducible successful payload."""


class InvalidNormalizationInputError(NormalizationError):
    """Submitted normalized content violates the durable contract."""


class NormalizationConflictError(NormalizationError):
    """The extractor identity already exists with different immutable content."""


class NormalizationPersistenceError(NormalizationError):
    """The database refused a normalized-document recording operation."""


class NormalizationService:
    """Record success/failure outputs without fetching, extracting, or committing."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._snapshots = FetchSnapshotRepository(session)
        self._documents = NormalizedDocumentRepository(session)

    def record_success(
        self,
        fetch_snapshot_id: uuid.UUID,
        *,
        extractor_name: str,
        extractor_version: str,
        clean_text: str,
        parser_version: str | None = None,
        title: str | None = None,
        language: str | None = None,
        author_name: str | None = None,
        external_published_at: datetime | None = None,
        headings: list[dict[str, Any]] | None = None,
        sections: list[dict[str, Any]] | None = None,
        links: list[dict[str, Any]] | None = None,
        structured_metadata: dict[str, Any] | None = None,
    ) -> NormalizedDocument:
        """Record a usable extractor result and its deterministic v1 fingerprint."""
        snapshot = self._require_eligible_snapshot(fetch_snapshot_id)
        identity = _validate_identity(extractor_name, extractor_version, parser_version)
        if not clean_text.strip():
            raise InvalidNormalizationInputError("successful clean_text must not be empty")
        if len(clean_text) > MAX_CLEAN_TEXT_LENGTH:
            raise InvalidNormalizationInputError("clean_text exceeds the persistence limit")

        candidate = NormalizedDocument(
            fetch_snapshot_id=snapshot.id,
            extractor_name=identity[0],
            extractor_version=identity[1],
            parser_version=identity[2],
            normalization_status=NormalizationStatus.SUCCEEDED,
            failure_code=None,
            failure_detail=None,
            title=_validate_optional_text("title", title, MAX_TITLE_LENGTH),
            clean_text=clean_text,
            language=_validate_optional_text("language", language, MAX_LANGUAGE_LENGTH),
            author_name=_validate_optional_text("author_name", author_name, MAX_AUTHOR_NAME_LENGTH),
            external_published_at=_validate_timestamp(external_published_at),
            headings=_validate_json_list("headings", headings),
            sections=_validate_json_list("sections", sections),
            links=_validate_json_list("links", links),
            structured_metadata=_validate_json_dict("structured_metadata", structured_metadata),
            content_fingerprint=hashlib.sha256(clean_text.encode("utf-8")).hexdigest(),
            fingerprint_version=NORMALIZED_CONTENT_FINGERPRINT_VERSION,
            normalized_at=datetime.now(UTC),
        )
        return self._record(candidate)

    def record_failure(
        self,
        fetch_snapshot_id: uuid.UUID,
        *,
        extractor_name: str,
        extractor_version: str,
        failure_code: NormalizationFailureCode,
        failure_detail: str | None = None,
        parser_version: str | None = None,
    ) -> NormalizedDocument:
        """Record a stable extraction failure against a reproducible payload."""
        snapshot = self._require_eligible_snapshot(fetch_snapshot_id)
        identity = _validate_identity(extractor_name, extractor_version, parser_version)
        if not isinstance(failure_code, NormalizationFailureCode):
            raise InvalidNormalizationInputError("failure_code must be a supported enum value")

        candidate = NormalizedDocument(
            fetch_snapshot_id=snapshot.id,
            extractor_name=identity[0],
            extractor_version=identity[1],
            parser_version=identity[2],
            normalization_status=NormalizationStatus.FAILED,
            failure_code=failure_code,
            failure_detail=_sanitize_failure_detail(failure_detail),
            title=None,
            clean_text=None,
            language=None,
            author_name=None,
            external_published_at=None,
            headings=[],
            sections=[],
            links=[],
            structured_metadata={},
            content_fingerprint=None,
            fingerprint_version=None,
            normalized_at=datetime.now(UTC),
        )
        return self._record(candidate)

    def _require_eligible_snapshot(self, snapshot_id: uuid.UUID) -> FetchSnapshot:
        snapshot = self._snapshots.get_by_id(snapshot_id)
        if snapshot is None:
            raise FetchSnapshotNotFoundError(f"no fetch snapshot with id {snapshot_id}")
        if (
            snapshot.fetch_outcome is not FetchOutcome.SUCCESS
            or not snapshot.raw_payload_ref
            or snapshot.body_sha256 is None
            or snapshot.body_size_bytes is None
        ):
            raise FetchSnapshotNotEligibleError(
                "normalization requires a successful reproducible fetch snapshot"
            )
        return snapshot

    def _record(self, candidate: NormalizedDocument) -> NormalizedDocument:
        existing = self._documents.get_by_snapshot_and_extractor(
            candidate.fetch_snapshot_id,
            candidate.extractor_name,
            candidate.extractor_version,
        )
        if existing is not None:
            return _resolve_existing(existing, candidate)

        try:
            with self._session.begin_nested():
                return self._documents.add(candidate)
        except IntegrityError:
            winner = self._documents.get_by_snapshot_and_extractor(
                candidate.fetch_snapshot_id,
                candidate.extractor_name,
                candidate.extractor_version,
            )
            if winner is not None:
                return _resolve_existing(winner, candidate)
            raise NormalizationPersistenceError("database rejected normalized document") from None
        except SQLAlchemyError:
            raise NormalizationPersistenceError("database rejected normalized document") from None


def _resolve_existing(
    existing: NormalizedDocument, candidate: NormalizedDocument
) -> NormalizedDocument:
    if all(getattr(existing, field) == getattr(candidate, field) for field in _SEMANTIC_FIELDS):
        return existing
    raise NormalizationConflictError(
        "extractor identity already exists with different normalized content"
    )


def _validate_identity(
    extractor_name: str,
    extractor_version: str,
    parser_version: str | None,
) -> tuple[str, str, str | None]:
    return (
        _validate_required_identity("extractor_name", extractor_name, MAX_EXTRACTOR_NAME_LENGTH),
        _validate_required_identity(
            "extractor_version", extractor_version, MAX_EXTRACTOR_VERSION_LENGTH
        ),
        _validate_optional_identity("parser_version", parser_version, MAX_PARSER_VERSION_LENGTH),
    )


def _validate_required_identity(name: str, value: str, limit: int) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise InvalidNormalizationInputError(f"{name} must not be empty")
    if len(cleaned) > limit:
        raise InvalidNormalizationInputError(f"{name} exceeds the persistence limit")
    return cleaned


def _validate_optional_identity(name: str, value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    return _validate_required_identity(name, value, limit)


def _validate_optional_text(name: str, value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    if not value.strip():
        raise InvalidNormalizationInputError(f"{name} must not be blank")
    if len(value) > limit:
        raise InvalidNormalizationInputError(f"{name} exceeds the persistence limit")
    return value


def _validate_timestamp(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise InvalidNormalizationInputError("external_published_at must be timezone-aware")
    return value.astimezone(UTC)


def _sanitize_failure_detail(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = _WHITESPACE.sub(" ", value).strip()
    if not cleaned:
        return None
    if len(cleaned) > MAX_FAILURE_DETAIL_LENGTH:
        raise InvalidNormalizationInputError("failure_detail exceeds the persistence limit")
    return cleaned


def _validate_json_list(name: str, value: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    candidate: list[dict[str, Any]] = [] if value is None else value
    _validate_json(name, candidate, list)
    if any(not isinstance(item, dict) for item in candidate):
        raise InvalidNormalizationInputError(f"{name} entries must be objects")
    return deepcopy(candidate)


def _validate_json_dict(name: str, value: dict[str, Any] | None) -> dict[str, Any]:
    candidate: dict[str, Any] = {} if value is None else value
    _validate_json(name, candidate, dict)
    return deepcopy(candidate)


def _validate_json(
    name: str,
    value: Any,
    expected_root: type[list[Any]] | type[dict[str, Any]],
) -> None:
    if not isinstance(value, expected_root):
        raise InvalidNormalizationInputError(f"{name} has the wrong JSON container type")
    item_count = 0

    def walk(node: Any, depth: int) -> None:
        nonlocal item_count
        if depth > MAX_JSON_DEPTH:
            raise InvalidNormalizationInputError(f"{name} exceeds the JSON depth limit")
        if isinstance(node, dict):
            item_count += len(node)
            for key, child in node.items():
                if not isinstance(key, str):
                    raise InvalidNormalizationInputError(f"{name} JSON keys must be strings")
                if len(key) > MAX_JSON_STRING_LENGTH:
                    raise InvalidNormalizationInputError(f"{name} contains an oversized JSON key")
                walk(child, depth + 1)
        elif isinstance(node, list):
            item_count += len(node)
            for child in node:
                walk(child, depth + 1)
        elif isinstance(node, str):
            if len(node) > MAX_JSON_STRING_LENGTH:
                raise InvalidNormalizationInputError(f"{name} contains an oversized JSON string")
        elif isinstance(node, float):
            if not math.isfinite(node):
                raise InvalidNormalizationInputError(f"{name} contains a non-finite JSON number")
        elif node is not None and not isinstance(node, (bool, int)):
            raise InvalidNormalizationInputError(f"{name} contains a non-JSON value")
        if item_count > MAX_JSON_ITEMS:
            raise InvalidNormalizationInputError(f"{name} exceeds the JSON item limit")

    walk(value, 1)
