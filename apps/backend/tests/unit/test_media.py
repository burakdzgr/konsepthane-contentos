"""Media foundation tests (Phase 6 M1): store, assets, satisfactions."""

import hashlib
import uuid
from pathlib import Path

import pytest
from editorial_harness import TEST_OPERATOR_USERNAME, Harness
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_decisions import awaiting_review_context
from test_qa import qa_review_context

import contentos.media.models  # noqa: F401  (register tables before create_all)
from contentos.auth.models import User
from contentos.media.enums import MediaOrigin, SatisfactionStatus
from contentos.media.errors import (
    MediaConflictError,
    MediaInputError,
    MediaPreconditionError,
)
from contentos.media.models import MediaSatisfactionEvent
from contentos.media.service import MAX_MEDIA_BYTES, MediaService
from contentos.media.store import MediaStore, MediaStoreError

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"deterministic-test-image-content"
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"deterministic-test-jpeg-content"
WEBP_BYTES = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"vp8-content"


@pytest.fixture()
def harness() -> Harness:
    return Harness()


def operator_user(session: Session) -> User:
    return session.execute(select(User).where(User.username == TEST_OPERATOR_USERNAME)).scalar_one()


def media_service(session: Session, tmp_path: Path) -> MediaService:
    return MediaService(session, MediaStore(tmp_path / "media-store"))


class TestMediaStore:
    def test_put_is_content_addressed_and_idempotent(self, tmp_path: Path) -> None:
        store = MediaStore(tmp_path)
        digest = store.put(PNG_BYTES)
        assert digest == hashlib.sha256(PNG_BYTES).hexdigest()
        assert store.exists(digest)
        assert store.put(PNG_BYTES) == digest  # second put is a no-op
        assert store.read(digest) == PNG_BYTES

    def test_read_verifies_integrity_and_rejects_bad_keys(self, tmp_path: Path) -> None:
        store = MediaStore(tmp_path)
        digest = store.put(PNG_BYTES)
        # Corrupt the stored bytes behind the store's back.
        path = tmp_path / digest[:2] / digest[2:4] / digest
        path.write_bytes(b"tampered")
        with pytest.raises(MediaStoreError, match="integrity"):
            store.read(digest)
        with pytest.raises(MediaStoreError, match="sha256"):
            store.exists("../../etc/passwd")


class TestRegisterUpload:
    def test_upload_persists_provenance_and_dedupes_by_hash(
        self, harness: Harness, tmp_path: Path
    ) -> None:
        with harness.session() as session:
            service = media_service(session, tmp_path)
            user = operator_user(session)
            asset, created = service.register_upload(
                PNG_BYTES,
                media_type="image/png",
                alt_text="Balon süslemeli parti masası",
                license_note="Konsepthane arşivi; kullanım hakkı bizde",
                created_by=user,
            )
            session.commit()
            assert created is True
            assert asset.origin is MediaOrigin.HUMAN_UPLOAD
            assert asset.content_sha256 == hashlib.sha256(PNG_BYTES).hexdigest()
            assert asset.byte_size == len(PNG_BYTES)
            assert asset.created_by_user_id == user.id
            assert asset.generation_attempt_id is None
            assert service.read_asset_bytes(asset) == PNG_BYTES

            again, created_again = service.register_upload(
                PNG_BYTES,
                media_type="image/png",
                alt_text="farklı metin — ilk kayıt geçerli kalır",
                license_note="yine arşiv",
                created_by=user,
            )
            assert created_again is False
            assert again.id == asset.id
            assert again.alt_text == "Balon süslemeli parti masası"

    def test_upload_refuses_bad_inputs(self, harness: Harness, tmp_path: Path) -> None:
        with harness.session() as session:
            service = media_service(session, tmp_path)
            user = operator_user(session)
            with pytest.raises(MediaInputError, match="empty"):
                service.register_upload(
                    b"",
                    media_type="image/png",
                    alt_text="a",
                    license_note="b",
                    created_by=user,
                )
            with pytest.raises(MediaInputError, match="byte limit"):
                service.register_upload(
                    b"\x89PNG\r\n\x1a\n" + b"0" * MAX_MEDIA_BYTES,
                    media_type="image/png",
                    alt_text="a",
                    license_note="b",
                    created_by=user,
                )
            # The declared type must match the actual bytes.
            with pytest.raises(MediaInputError, match="do not look like image/png"):
                service.register_upload(
                    JPEG_BYTES,
                    media_type="image/png",
                    alt_text="a",
                    license_note="b",
                    created_by=user,
                )
            with pytest.raises(MediaInputError, match="media_type must be one of"):
                service.register_upload(
                    PNG_BYTES,
                    media_type="image/svg+xml",
                    alt_text="a",
                    license_note="b",
                    created_by=user,
                )
            # Accessibility and licensing are not optional.
            with pytest.raises(MediaInputError, match="alt_text"):
                service.register_upload(
                    PNG_BYTES,
                    media_type="image/png",
                    alt_text="   ",
                    license_note="b",
                    created_by=user,
                )
            with pytest.raises(MediaInputError, match="license_note"):
                service.register_upload(
                    WEBP_BYTES,
                    media_type="image/webp",
                    alt_text="a",
                    license_note="",
                    created_by=user,
                )


class TestSatisfactions:
    def upload_asset(self, service: MediaService, session: Session) -> uuid.UUID:
        asset, _ = service.register_upload(
            PNG_BYTES,
            media_type="image/png",
            alt_text="Kapak görseli adayı",
            license_note="Konsepthane arşivi",
            created_by=operator_user(session),
        )
        session.commit()
        return asset.id

    def test_satisfy_replace_unsatisfy_lifecycle(self, harness: Harness, tmp_path: Path) -> None:
        accepted, _, _ = qa_review_context(harness)  # QA_REVIEW: in bounds
        work_item_id = accepted.context.work_item_id
        with harness.session() as session:
            service = media_service(session, tmp_path)
            user = operator_user(session)
            asset_id = self.upload_asset(service, session)

            satisfaction = service.satisfy_need(
                work_item_id,
                0,
                asset_id,
                user=user,
                reason="kapak ihtiyacını arşiv görseli karşılıyor",
            )
            session.commit()
            assert satisfaction.status is SatisfactionStatus.ACTIVE
            assert satisfaction.satisfied_by_user_id == user.id

            # Idempotent for the same asset: no new row.
            same = service.satisfy_need(work_item_id, 0, asset_id, user=user, reason="aynı görsel")
            assert same.id == satisfaction.id

            # Replacing supersedes with the pointer set and an audit event.
            second_asset, _ = service.register_upload(
                JPEG_BYTES,
                media_type="image/jpeg",
                alt_text="Daha iyi kapak görseli",
                license_note="Konsepthane arşivi",
                created_by=user,
            )
            session.commit()
            replacement = service.satisfy_need(
                work_item_id,
                0,
                second_asset.id,
                user=user,
                reason="daha uygun görsel bulundu",
            )
            session.commit()
            assert replacement.id != satisfaction.id
            assert satisfaction.status is SatisfactionStatus.SUPERSEDED
            assert satisfaction.superseded_by_satisfaction_id == replacement.id

            coverage = service.needs_coverage(work_item_id)
            assert coverage is not None and len(coverage) == 1
            assert coverage[0].satisfaction is not None
            assert coverage[0].satisfaction.id == replacement.id

            # Unsatisfy: the need becomes honestly unsatisfied again.
            withdrawn = service.unsatisfy_need(
                work_item_id, 0, user=user, reason="görsel lisansı şüpheli çıktı"
            )
            session.commit()
            assert withdrawn.id == replacement.id
            assert withdrawn.status is SatisfactionStatus.SUPERSEDED
            assert withdrawn.superseded_by_satisfaction_id is None
            coverage = service.needs_coverage(work_item_id)
            assert coverage is not None and coverage[0].satisfaction is None

            events = list(
                session.execute(
                    select(MediaSatisfactionEvent).order_by(MediaSatisfactionEvent.id)
                ).scalars()
            )
            assert [(event.from_status.value, event.to_status.value) for event in events] == [
                ("active", "superseded"),
                ("active", "superseded"),
            ]
            assert all(event.actor_user_id == user.id for event in events)
            assert events[0].replacement_satisfaction_id == replacement.id
            assert events[1].replacement_satisfaction_id is None

            with pytest.raises(MediaConflictError, match="no active satisfaction"):
                service.unsatisfy_need(work_item_id, 0, user=user, reason="tekrar")

    def test_satisfy_refuses_unknown_needs_and_frozen_states(
        self, harness: Harness, tmp_path: Path
    ) -> None:
        accepted, _, _ = qa_review_context(harness)
        work_item_id = accepted.context.work_item_id
        with harness.session() as session:
            service = media_service(session, tmp_path)
            user = operator_user(session)
            asset_id = self.upload_asset(service, session)
            with pytest.raises(MediaInputError, match="does not exist"):
                service.satisfy_need(work_item_id, 5, asset_id, user=user, reason="olmayan ihtiyaç")
            with pytest.raises(MediaPreconditionError, match="no media asset"):
                service.satisfy_need(
                    work_item_id, 0, uuid.uuid4(), user=user, reason="olmayan görsel"
                )

        frozen, _, _ = awaiting_review_context(harness)  # terminal review: frozen
        with harness.session() as session:
            service = media_service(session, tmp_path)
            user = operator_user(session)
            asset_id = self.upload_asset(service, session)
            with pytest.raises(MediaPreconditionError, match="terminal review"):
                service.satisfy_need(
                    frozen.context.work_item_id,
                    0,
                    asset_id,
                    user=user,
                    reason="donmuş pakete görsel",
                )

    def test_coverage_is_none_for_unknown_items(self, harness: Harness, tmp_path: Path) -> None:
        with harness.session() as session:
            service = media_service(session, tmp_path)
            assert service.needs_coverage(uuid.uuid4()) is None
