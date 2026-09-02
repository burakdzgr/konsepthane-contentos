"""AI image generation for media needs (Phase 6 M4).

The whole contentos.ai boundary applies: purpose-tagged attempts with
safe metadata only, no prompts or raw payloads persisted, failures are
durable attempt facts — never editorial decisions. The IMAGE ITSELF is
the durable deliverable: on success the bytes are stored
content-addressed and a MediaAsset row carries the attempt provenance,
the NAMED commissioning human, and the fixed `generated_in_house`
licensing posture. Generation NEVER satisfies a need and NEVER touches
the workflow — a human must bind the asset explicitly (ADR 0004).
"""

import base64
import binascii
import hashlib
import uuid
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from contentos.ai.dto import GenerationRequest
from contentos.ai.enums import GenerationPurpose, GenerationStatus
from contentos.ai.models import AiGenerationAttempt
from contentos.ai.protocol import StructuredGenerationProvider
from contentos.ai.service import StructuredGenerationService
from contentos.ai.validation import StructuredOutputSpec
from contentos.auth.models import User
from contentos.media.dimensions import extract_dimensions
from contentos.media.enums import MediaOrigin
from contentos.media.models import MediaAsset
from contentos.media.service import MAX_MEDIA_BYTES, MediaService
from contentos.media.store import MediaStore

MEDIA_IMAGE_SCHEMA_NAME = "media-image"
MEDIA_IMAGE_SCHEMA_VERSION = "1"
MEDIA_IMAGE_TEMPLATE_NAME = "media-image"
MEDIA_IMAGE_TEMPLATE_VERSION = "1"

GENERATED_LICENSE_NOTE = (
    "AI ile kurum içinde üretildi (generated in-house); üçüncü taraf lisansı yok."
)

# ~10 MiB of raw bytes is ~14M base64 characters.
_MAX_IMAGE_BASE64_LENGTH = 14_000_000

_MAGIC_BY_TYPE: dict[str, bytes] = {
    "image/png": b"\x89PNG\r\n\x1a\n",
    "image/jpeg": b"\xff\xd8\xff",
    "image/webp": b"RIFF",
}

MEDIA_IMAGE_INSTRUCTIONS = (
    "Konsepthane için TEK bir görsel üret. Girdi projeksiyonundaki "
    "media_need alanı görselin rolünü, amacını ve kısıtlarını tanımlar; "
    "locale/market ve çalışma başlığı bağlamdır. Marka adı, okunabilir "
    "metin, logo veya filigran KOYMA. Çıktıyı şemaya uygun döndür: "
    "image_base64 (görselin base64 içeriği) ve media_type."
)


class MediaImageV1(BaseModel):
    """The bounded media-image envelope: the image is the deliverable."""

    model_config = ConfigDict(extra="forbid")

    image_base64: str = Field(min_length=8, max_length=_MAX_IMAGE_BASE64_LENGTH)
    media_type: Literal["image/png", "image/jpeg", "image/webp"]


def _decode_image(payload: MediaImageV1) -> bytes | None:
    try:
        return base64.b64decode(payload.image_base64, validate=True)
    except (binascii.Error, ValueError):
        return None


def validate_media_image(payload: MediaImageV1) -> str | None:
    """Domain validation: the bytes must BE the declared image type and
    fit the store bound — a provider's word is never trusted."""
    data = _decode_image(payload)
    if data is None:
        return "image_base64 is not valid base64"
    if not data:
        return "the decoded image is empty"
    if len(data) > MAX_MEDIA_BYTES:
        return f"the decoded image exceeds the {MAX_MEDIA_BYTES} byte limit"
    if not data.startswith(_MAGIC_BY_TYPE[payload.media_type]):
        return f"the decoded bytes do not look like {payload.media_type}"
    if payload.media_type == "image/webp" and data[8:12] != b"WEBP":
        return "the decoded bytes do not look like image/webp"
    return None


MEDIA_IMAGE_SPEC = StructuredOutputSpec(
    schema_name=MEDIA_IMAGE_SCHEMA_NAME,
    schema_version=MEDIA_IMAGE_SCHEMA_VERSION,
    model_type=MediaImageV1,
    domain_validator=validate_media_image,
)


@dataclass(frozen=True, slots=True)
class MediaImageResult:
    """One generation execution outcome. `asset` is present only when a
    SUCCEEDED attempt has a durable asset (newly created, or resolved
    from a previous identical attempt / identical bytes)."""

    attempt: AiGenerationAttempt
    status: GenerationStatus
    asset: MediaAsset | None
    created: bool


class MediaImageEngine:
    """Transport-neutral engine; flushes only — the caller commits."""

    def __init__(self, session: Session, store: MediaStore) -> None:
        self._session = session
        self._store = store
        self._media = MediaService(session, store)

    def generate(
        self,
        work_item_id: uuid.UUID,
        need_index: int,
        *,
        requested_by: User,
        provider: StructuredGenerationProvider,
        retry_number: int = 0,
        request_id: str | None = None,
    ) -> MediaImageResult:
        brief, need = self._media.resolve_need(work_item_id, need_index)
        request = GenerationRequest(
            purpose=GenerationPurpose.MEDIA_IMAGE,
            schema_name=MEDIA_IMAGE_SCHEMA_NAME,
            schema_version=MEDIA_IMAGE_SCHEMA_VERSION,
            template_name=MEDIA_IMAGE_TEMPLATE_NAME,
            template_version=MEDIA_IMAGE_TEMPLATE_VERSION,
            input_refs={
                "work_item_id": str(work_item_id),
                "content_brief_id": str(brief.id),
                "need_index": need_index,
            },
            input_projection={
                "media_need": need,
                "locale": brief.locale,
                "market": brief.market,
                "original_angle": brief.original_angle,
            },
            retry_number=retry_number,
            instructions=MEDIA_IMAGE_INSTRUCTIONS,
        )
        execution = StructuredGenerationService(self._session).execute(
            request, MEDIA_IMAGE_SPEC, provider
        )

        if not execution.created:
            # Idempotent reuse: raw output is never persisted, so the only
            # honest materialization is the asset already linked to that
            # exact attempt (if the original run created one).
            asset = self._asset_for_attempt(execution.attempt.id)
            return MediaImageResult(
                attempt=execution.attempt,
                status=execution.status,
                asset=asset,
                created=False,
            )
        if execution.status is not GenerationStatus.SUCCEEDED or execution.payload is None:
            return MediaImageResult(
                attempt=execution.attempt,
                status=execution.status,
                asset=None,
                created=True,
            )

        payload = execution.payload
        data = _decode_image(payload)
        assert data is not None  # domain validation already proved it
        digest_asset = self._asset_for_content(data)
        if digest_asset is not None:
            # Identical bytes already exist as an asset: converge honestly
            # (content addressing makes a duplicate row impossible anyway).
            return MediaImageResult(
                attempt=execution.attempt,
                status=execution.status,
                asset=digest_asset,
                created=True,
            )
        digest = self._store.put(data)
        alt_text = str(need.get("purpose") or need.get("role") or "").strip()
        width, height = extract_dimensions(data, payload.media_type)
        asset = MediaAsset(
            origin=MediaOrigin.AI_GENERATED,
            content_sha256=digest,
            byte_size=len(data),
            media_type=payload.media_type,
            width=width,
            height=height,
            title=None,
            # A deterministic proposal from the durable need; the human can
            # replace the asset (new upload) if better alt text is needed.
            alt_text=alt_text or "AI ile üretilen görsel",
            license_note=GENERATED_LICENSE_NOTE,
            source_attribution=None,
            generation_attempt_id=execution.attempt.id,
            created_by_user_id=requested_by.id,
            request_id=request_id,
        )
        self._session.add(asset)
        self._session.flush()
        return MediaImageResult(
            attempt=execution.attempt,
            status=execution.status,
            asset=asset,
            created=True,
        )

    def _asset_for_attempt(self, attempt_id: uuid.UUID) -> MediaAsset | None:
        return self._session.execute(
            select(MediaAsset).where(MediaAsset.generation_attempt_id == attempt_id)
        ).scalar_one_or_none()

    def _asset_for_content(self, data: bytes) -> MediaAsset | None:
        digest = hashlib.sha256(data).hexdigest()
        return self._session.execute(
            select(MediaAsset).where(MediaAsset.content_sha256 == digest)
        ).scalar_one_or_none()
