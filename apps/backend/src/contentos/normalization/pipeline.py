"""Executable verified-payload-to-NormalizedDocument orchestration."""

import uuid
from collections.abc import Iterable

from sqlalchemy.orm import Session

from contentos.fetching.models import FetchOutcome
from contentos.fetching.snapshot_repository import FetchSnapshotRepository
from contentos.fetching.snapshots import FetchSnapshot
from contentos.normalization.enums import NormalizationFailureCode
from contentos.normalization.extractors import (
    ExtractedDocument,
    ExtractionContext,
    Extractor,
    ExtractorDecodeError,
    ExtractorEmptyContentError,
    ExtractorParseError,
    ExtractorPolicyError,
    ExtractorUnsupportedContentError,
    HtmlExtractor,
    PlainTextExtractor,
)
from contentos.normalization.models import NormalizedDocument
from contentos.normalization.service import (
    FetchSnapshotNotEligibleError,
    FetchSnapshotNotFoundError,
    InvalidNormalizationInputError,
    NormalizationService,
)
from contentos.payloads.errors import (
    InvalidPayloadMetadataError,
    InvalidPayloadReferenceError,
    PayloadBackendError,
    PayloadIntegrityError,
    PayloadNotFoundError,
    PayloadTooLargeError,
)
from contentos.payloads.models import validate_max_bytes
from contentos.payloads.store import RawPayloadReader, read_verified_payload


class NormalizationPipelineError(Exception):
    """Base class for orchestration failures that are not extractor results."""


class NormalizationPipelineIntegrityError(NormalizationPipelineError):
    """Stored bytes violated immutable FetchSnapshot hash/size provenance."""


class NormalizationPipelinePayloadError(NormalizationPipelineError):
    """The injected payload provider could not retrieve the immutable object."""


class NormalizationPipelineConfigurationError(NormalizationPipelineError):
    """Extractor registry configuration is ambiguous or invalid."""


class _UnsupportedMediaExtractor:
    name = "unsupported-media"
    version = "1"
    parser_version = "media-router-v1"
    supported_media_types: frozenset[str] = frozenset()

    def extract(self, payload: bytes, context: ExtractionContext) -> ExtractedDocument:
        del payload, context
        raise ExtractorUnsupportedContentError("snapshot media type is unsupported")


class NormalizationPipeline:
    """Verify one immutable snapshot, extract deterministically, and flush a result."""

    def __init__(
        self,
        session: Session,
        reader: RawPayloadReader,
        *,
        max_payload_bytes: int,
        extractors: Iterable[Extractor] | None = None,
    ) -> None:
        self._snapshots = FetchSnapshotRepository(session)
        self._normalization = NormalizationService(session)
        self._reader = reader
        self._max_payload_bytes = validate_max_bytes(max_payload_bytes)
        configured = tuple(extractors or (HtmlExtractor(), PlainTextExtractor()))
        self._extractors = _build_registry(configured)
        self._unsupported = _UnsupportedMediaExtractor()

    def normalize_snapshot(
        self,
        fetch_snapshot_id: uuid.UUID,
        *,
        extractor: Extractor | None = None,
    ) -> NormalizedDocument:
        """Execute the complete verified normalization path without committing."""
        snapshot = self._require_eligible_snapshot(fetch_snapshot_id)
        media_type = _media_type(snapshot.content_type)
        selected = extractor or self._extractors.get(media_type) or self._unsupported

        assert snapshot.body_size_bytes is not None
        if snapshot.body_size_bytes > self._max_payload_bytes:
            return self._record_failure(
                snapshot,
                selected,
                NormalizationFailureCode.POLICY_REJECTED,
                "snapshot payload exceeds the configured normalization limit",
            )

        payload = self._read_verified(snapshot)
        context = ExtractionContext(
            media_type=media_type,
            content_type=snapshot.content_type,
            base_url=snapshot.final_url or snapshot.requested_url,
        )
        if media_type not in selected.supported_media_types:
            return self._record_failure(
                snapshot,
                selected,
                NormalizationFailureCode.UNSUPPORTED_CONTENT,
                "snapshot media type is unsupported",
            )

        try:
            document = selected.extract(payload, context)
        except ExtractorUnsupportedContentError as error:
            return self._record_expected_failure(
                snapshot, selected, NormalizationFailureCode.UNSUPPORTED_CONTENT, error
            )
        except ExtractorDecodeError as error:
            return self._record_expected_failure(
                snapshot, selected, NormalizationFailureCode.DECODE_ERROR, error
            )
        except ExtractorParseError as error:
            return self._record_expected_failure(
                snapshot, selected, NormalizationFailureCode.PARSE_ERROR, error
            )
        except ExtractorEmptyContentError as error:
            return self._record_expected_failure(
                snapshot, selected, NormalizationFailureCode.EMPTY_CONTENT, error
            )
        except ExtractorPolicyError as error:
            return self._record_expected_failure(
                snapshot, selected, NormalizationFailureCode.POLICY_REJECTED, error
            )
        except Exception:
            return self._record_failure(
                snapshot,
                selected,
                NormalizationFailureCode.EXTRACTOR_ERROR,
                "extractor failed unexpectedly",
            )

        try:
            return self._normalization.record_success(
                snapshot.id,
                extractor_name=selected.name,
                extractor_version=selected.version,
                parser_version=document.parser_version,
                title=document.title,
                clean_text=document.clean_text,
                language=document.language,
                author_name=document.author_name,
                external_published_at=document.external_published_at,
                headings=[
                    {"level": heading.level, "text": heading.text} for heading in document.headings
                ],
                sections=[
                    {
                        "level": section.level,
                        "heading": section.heading,
                        "text": section.text,
                    }
                    for section in document.sections
                ],
                links=[
                    {"href": link.href, "url": link.url, "text": link.text}
                    for link in document.links
                ],
                structured_metadata=document.structured_metadata,
            )
        except InvalidNormalizationInputError:
            return self._record_failure(
                snapshot,
                selected,
                NormalizationFailureCode.EXTRACTOR_ERROR,
                "extractor output violated the normalization contract",
            )

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

    def _read_verified(self, snapshot: FetchSnapshot) -> bytes:
        assert snapshot.raw_payload_ref is not None
        assert snapshot.body_sha256 is not None
        assert snapshot.body_size_bytes is not None
        try:
            return read_verified_payload(
                self._reader,
                snapshot.raw_payload_ref,
                expected_sha256=snapshot.body_sha256,
                expected_size_bytes=snapshot.body_size_bytes,
                max_bytes=self._max_payload_bytes,
            )
        except (PayloadIntegrityError, PayloadTooLargeError) as error:
            raise NormalizationPipelineIntegrityError(
                "raw payload violated FetchSnapshot provenance"
            ) from error
        except (InvalidPayloadReferenceError, InvalidPayloadMetadataError) as error:
            raise NormalizationPipelineIntegrityError(
                "FetchSnapshot contains invalid payload provenance"
            ) from error
        except (PayloadNotFoundError, PayloadBackendError) as error:
            raise NormalizationPipelinePayloadError("raw payload could not be retrieved") from error

    def _record_expected_failure(
        self,
        snapshot: FetchSnapshot,
        extractor: Extractor,
        code: NormalizationFailureCode,
        error: Exception,
    ) -> NormalizedDocument:
        return self._record_failure(snapshot, extractor, code, str(error))

    def _record_failure(
        self,
        snapshot: FetchSnapshot,
        extractor: Extractor,
        code: NormalizationFailureCode,
        detail: str,
    ) -> NormalizedDocument:
        return self._normalization.record_failure(
            snapshot.id,
            extractor_name=extractor.name,
            extractor_version=extractor.version,
            parser_version=extractor.parser_version,
            failure_code=code,
            failure_detail=detail,
        )


def _build_registry(extractors: tuple[Extractor, ...]) -> dict[str, Extractor]:
    registry: dict[str, Extractor] = {}
    for extractor in extractors:
        if not extractor.name.strip() or not extractor.version.strip():
            raise NormalizationPipelineConfigurationError(
                "extractor name and version must be non-empty"
            )
        for media_type in extractor.supported_media_types:
            normalized = media_type.strip().casefold()
            if not normalized or normalized in registry:
                raise NormalizationPipelineConfigurationError(
                    "extractor media-type registry is ambiguous"
                )
            registry[normalized] = extractor
    return registry


def _media_type(content_type: str | None) -> str:
    return content_type.split(";", 1)[0].strip().casefold() if content_type else ""
