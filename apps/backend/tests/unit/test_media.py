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


class TestMediaApi:
    """Phase 6 M2: operator commands + coverage read model + streaming."""

    def upload(self, harness: Harness, data: bytes, content_type: str, **form: str):
        form_data = {
            "alt_text": "Balon süslemeli parti masası",
            "license_note": "Konsepthane arşivi",
            **form,
        }
        return harness.request(
            "POST",
            "/internal/editorial/media-assets",
            files={"file": ("kapak.png", data, content_type)},
            form_data=form_data,
        )

    def test_upload_registers_and_dedupes(self, harness: Harness) -> None:
        first = self.upload(harness, PNG_BYTES, "image/png")
        assert first.status_code == 200, first.text
        body = first.json()
        assert body["status"] == "registered"
        assert body["content_sha256"] == hashlib.sha256(PNG_BYTES).hexdigest()

        again = self.upload(harness, PNG_BYTES, "image/png")
        assert again.status_code == 200
        assert again.json()["status"] == "already_exists"
        assert again.json()["media_asset_id"] == body["media_asset_id"]

        mismatched = self.upload(harness, JPEG_BYTES, "image/png")
        assert mismatched.status_code == 422
        assert "do not look like image/png" in mismatched.json()["error"]["message"]

    def test_satisfy_coverage_stream_unsatisfy_flow(self, harness: Harness) -> None:
        accepted, _, _ = qa_review_context(harness)
        work_item_id = accepted.context.work_item_id

        uploaded = self.upload(harness, PNG_BYTES, "image/png")
        asset_id = uploaded.json()["media_asset_id"]

        satisfy = harness.post(
            f"/internal/editorial/work-items/{work_item_id}/media-needs/0/satisfy",
            {"media_asset_id": asset_id, "reason": "kapak ihtiyacı karşılandı"},
        )
        assert satisfy.status_code == 200, satisfy.text
        assert satisfy.json()["status"] == "satisfied"

        coverage = harness.get(f"/internal/editorial/work-items/{work_item_id}/media")
        assert coverage.status_code == 200
        page = coverage.json()
        assert page["total_needs"] == 1 and page["satisfied_needs"] == 1
        need = page["needs"][0]
        assert need["satisfaction"]["asset"]["media_type"] == "image/png"
        assert need["satisfaction"]["asset"]["alt_text"] == "Balon süslemeli parti masası"
        assert need["satisfaction"]["satisfied_by"]["username"] == TEST_OPERATOR_USERNAME
        # Leak posture: no store paths, no credential material.
        lowered = coverage.text.lower()
        assert "media-store" not in lowered and "contentos-test-media" not in lowered
        assert "password" not in lowered and "token" not in lowered

        content = harness.get(f"/internal/editorial/media-assets/{asset_id}/content")
        assert content.status_code == 200
        assert content.headers["content-type"].startswith("image/png")
        assert content.content == PNG_BYTES
        missing = harness.get(f"/internal/editorial/media-assets/{uuid.uuid4()}/content")
        assert missing.status_code == 404

        unsatisfy = harness.post(
            f"/internal/editorial/work-items/{work_item_id}/media-needs/0/unsatisfy",
            {"reason": "görsel lisansı şüpheli"},
        )
        assert unsatisfy.status_code == 200
        after = harness.get(f"/internal/editorial/work-items/{work_item_id}/media").json()
        assert after["satisfied_needs"] == 0
        assert after["needs"][0]["satisfaction"] is None
        # History keeps the audited superseded binding visible.
        assert len(after["history"]) == 1
        assert after["history"][0]["status"] == "superseded"

    def test_satisfy_refusals_map_to_bounded_errors(self, harness: Harness) -> None:
        accepted, _, _ = qa_review_context(harness)
        work_item_id = accepted.context.work_item_id
        uploaded = self.upload(harness, PNG_BYTES, "image/png")
        asset_id = uploaded.json()["media_asset_id"]

        unknown_need = harness.post(
            f"/internal/editorial/work-items/{work_item_id}/media-needs/7/satisfy",
            {"media_asset_id": asset_id, "reason": "olmayan ihtiyaç"},
        )
        assert unknown_need.status_code == 422

        unknown_asset = harness.post(
            f"/internal/editorial/work-items/{work_item_id}/media-needs/0/satisfy",
            {"media_asset_id": str(uuid.uuid4()), "reason": "olmayan görsel"},
        )
        assert unknown_asset.status_code == 409

        nothing_to_withdraw = harness.post(
            f"/internal/editorial/work-items/{work_item_id}/media-needs/0/unsatisfy",
            {"reason": "bağ yokken geri çek"},
        )
        assert nothing_to_withdraw.status_code == 409

    def test_frozen_terminal_state_is_a_409(self, harness: Harness) -> None:
        frozen, _, _ = awaiting_review_context(harness)
        uploaded = self.upload(harness, PNG_BYTES, "image/png")
        response = harness.post(
            f"/internal/editorial/work-items/{frozen.context.work_item_id}/media-needs/0/satisfy",
            {"media_asset_id": uploaded.json()["media_asset_id"], "reason": "donmuş paket"},
        )
        assert response.status_code == 409
        assert "terminal review" in response.json()["error"]["message"]

    def test_media_coverage_404_for_unknown_items(self, harness: Harness) -> None:
        assert (
            harness.get(f"/internal/editorial/work-items/{uuid.uuid4()}/media").status_code == 404
        )


class TestMediaImageGeneration:
    """Phase 6 M4: AI image generation behind the full ai boundary."""

    def image_payload(self, data: bytes = PNG_BYTES, media_type: str = "image/png") -> dict:
        import base64

        return {
            "image_base64": base64.b64encode(data).decode("ascii"),
            "media_type": media_type,
        }

    def engine(self, session: Session, tmp_path: Path):
        from contentos.media.generation import MediaImageEngine

        return MediaImageEngine(session, MediaStore(tmp_path / "media-store"))

    def test_success_creates_a_provenance_carrying_asset_only(
        self, harness: Harness, tmp_path: Path
    ) -> None:
        from contentos.ai.enums import GenerationPurpose, GenerationStatus
        from contentos.ai.fake import FakeStructuredProvider
        from contentos.media.generation import GENERATED_LICENSE_NOTE
        from contentos.workflow.repository import WorkflowRepository

        accepted, _, _ = qa_review_context(harness)
        work_item_id = accepted.context.work_item_id
        with harness.session() as session:
            user = operator_user(session)
            provider = FakeStructuredProvider(payload=self.image_payload())
            result = self.engine(session, tmp_path).generate(
                work_item_id, 0, requested_by=user, provider=provider
            )
            session.commit()
            assert result.status is GenerationStatus.SUCCEEDED
            assert result.created is True
            asset = result.asset
            assert asset is not None
            assert asset.origin is MediaOrigin.AI_GENERATED
            assert asset.generation_attempt_id == result.attempt.id
            assert asset.license_note == GENERATED_LICENSE_NOTE
            assert asset.created_by_user_id == user.id
            assert asset.alt_text  # deterministic proposal from the need
            assert result.attempt.purpose is GenerationPurpose.MEDIA_IMAGE
            # The stored bytes are exactly the decoded image.
            assert MediaStore(tmp_path / "media-store").read(asset.content_sha256) == PNG_BYTES

            # NO satisfaction and NO workflow effect: a human must bind it.
            service = MediaService(session, MediaStore(tmp_path / "media-store"))
            coverage = service.needs_coverage(work_item_id)
            assert coverage is not None and coverage[0].satisfaction is None
            item = WorkflowRepository(session).get_by_id(work_item_id)
            assert item is not None and item.current_state.value == "qa_review"

    def test_mismatched_bytes_are_a_validation_failure_without_an_asset(
        self, harness: Harness, tmp_path: Path
    ) -> None:
        from contentos.ai.enums import GenerationStatus
        from contentos.ai.fake import FakeStructuredProvider
        from contentos.media.models import MediaAsset

        accepted, _, _ = qa_review_context(harness)
        with harness.session() as session:
            user = operator_user(session)
            provider = FakeStructuredProvider(payload=self.image_payload(JPEG_BYTES, "image/png"))
            result = self.engine(session, tmp_path).generate(
                accepted.context.work_item_id, 0, requested_by=user, provider=provider
            )
            session.commit()
            assert result.status is GenerationStatus.VALIDATION_FAILED
            assert result.asset is None
            assert result.attempt.error_class == "domain_validation"
            assert session.execute(select(MediaAsset)).scalar_one_or_none() is None

    def test_identical_rerun_reuses_attempt_and_resolves_the_asset(
        self, harness: Harness, tmp_path: Path
    ) -> None:
        from contentos.ai.fake import FakeStructuredProvider

        accepted, _, _ = qa_review_context(harness)
        with harness.session() as session:
            user = operator_user(session)
            provider = FakeStructuredProvider(payload=self.image_payload())
            engine = self.engine(session, tmp_path)
            first = engine.generate(
                accepted.context.work_item_id, 0, requested_by=user, provider=provider
            )
            session.commit()
            second = engine.generate(
                accepted.context.work_item_id, 0, requested_by=user, provider=provider
            )
            assert second.created is False
            assert provider.invocations == 1  # no second spend
            assert second.asset is not None
            assert first.asset is not None
            assert second.asset.id == first.asset.id

    def test_generation_respects_the_media_state_bounds(
        self, harness: Harness, tmp_path: Path
    ) -> None:
        from contentos.ai.fake import FakeStructuredProvider

        frozen, _, _ = awaiting_review_context(harness)
        with harness.session() as session:
            user = operator_user(session)
            with pytest.raises(MediaPreconditionError, match="terminal review"):
                self.engine(session, tmp_path).generate(
                    frozen.context.work_item_id,
                    0,
                    requested_by=user,
                    provider=FakeStructuredProvider(payload=self.image_payload()),
                )


class TestGenerateImageCommand:
    def test_generate_image_queues_the_exact_task_with_the_named_human(
        self, harness: Harness
    ) -> None:
        accepted, _, _ = qa_review_context(harness)
        work_item_id = accepted.context.work_item_id
        response = harness.post(
            f"/internal/editorial/work-items/{work_item_id}/media-needs/0/generate-image"
        )
        assert response.status_code == 200, response.text
        assert response.json() == {
            "status": "queued",
            "task": "generate_media_image",
            "entity_id": str(work_item_id),
        }
        [(task_name, payload, _)] = harness.dispatcher.calls
        assert task_name == "generate_media_image"
        assert payload["work_item_id"] == str(work_item_id)
        assert payload["need_index"] == 0
        with harness.session() as session:
            assert payload["requested_by_user_id"] == str(operator_user(session).id)

    def test_generate_image_refuses_frozen_states_and_unknown_needs(self, harness: Harness) -> None:
        frozen, _, _ = awaiting_review_context(harness)
        frozen_response = harness.post(
            f"/internal/editorial/work-items/{frozen.context.work_item_id}"
            "/media-needs/0/generate-image"
        )
        assert frozen_response.status_code == 409
        assert harness.dispatcher.calls == []

        active, _, _ = qa_review_context(harness)
        unknown_need = harness.post(
            f"/internal/editorial/work-items/{active.context.work_item_id}"
            "/media-needs/9/generate-image"
        )
        assert unknown_need.status_code == 422
        assert harness.dispatcher.calls == []


class TestGenerateMediaImageTask:
    """The 10th editorial task, end to end through the eager worker."""

    def worker_app(self, harness: Harness, tmp_path: Path, provider):
        from contentos.core.config import Environment, LogLevel, Settings
        from contentos.queue.celery import create_celery_app
        from contentos.worker.editorial_tasks import register_editorial_pipeline_tasks
        from contentos.worker.runtime import WorkerRuntime

        settings = Settings(
            environment=Environment.TEST,
            service_name="ContentOS Media Task Test",
            application_version="1.0.0-test",
            log_level=LogLevel.INFO,
            api_docs_enabled=False,
            celery_task_always_eager=True,
            celery_broker_connection_retry_on_startup=False,
        )
        runtime = WorkerRuntime(
            settings,
            session_factory=harness.session_factory,
            image_generation_provider_factory=lambda: provider,
            media_store=MediaStore(tmp_path / "media-store"),
        )
        app = create_celery_app(settings)
        register_editorial_pipeline_tasks(app, runtime)
        return app

    def test_task_produces_an_asset_and_nothing_else(
        self, harness: Harness, tmp_path: Path
    ) -> None:
        import base64

        from contentos.ai.fake import FakeStructuredProvider
        from contentos.media.models import MediaAsset
        from contentos.worker.editorial_tasks import GENERATE_MEDIA_IMAGE_TASK
        from contentos.workflow.repository import WorkflowRepository

        accepted, _, _ = qa_review_context(harness)
        with harness.session() as session:
            user_id = str(operator_user(session).id)
        provider = FakeStructuredProvider(
            payload={
                "image_base64": base64.b64encode(PNG_BYTES).decode("ascii"),
                "media_type": "image/png",
            }
        )
        app = self.worker_app(harness, tmp_path, provider)
        result = (
            app.tasks[GENERATE_MEDIA_IMAGE_TASK]
            .apply(
                kwargs={
                    "work_item_id": str(accepted.context.work_item_id),
                    "need_index": 0,
                    "requested_by_user_id": user_id,
                }
            )
            .get()
        )
        assert result["status"] == "completed", result
        assert result["media_asset_id"] is not None
        with harness.session() as session:
            asset = session.get(MediaAsset, uuid.UUID(result["media_asset_id"]))
            assert asset is not None
            assert str(asset.created_by_user_id) == user_id
            item = WorkflowRepository(session).get_by_id(accepted.context.work_item_id)
            assert item is not None and item.current_state.value == "qa_review"

    def test_task_reports_preconditions_truthfully_without_effects(
        self, harness: Harness, tmp_path: Path
    ) -> None:
        from contentos.ai.fake import FakeStructuredProvider
        from contentos.worker.editorial_tasks import GENERATE_MEDIA_IMAGE_TASK

        frozen, _, _ = awaiting_review_context(harness)
        with harness.session() as session:
            user_id = str(operator_user(session).id)
        app = self.worker_app(harness, tmp_path, FakeStructuredProvider(payload={}))
        result = (
            app.tasks[GENERATE_MEDIA_IMAGE_TASK]
            .apply(
                kwargs={
                    "work_item_id": str(frozen.context.work_item_id),
                    "need_index": 0,
                    "requested_by_user_id": user_id,
                }
            )
            .get()
        )
        assert result["status"] == "precondition_failed"
        assert "terminal review" in result["detail"]

        unknown_user = (
            app.tasks[GENERATE_MEDIA_IMAGE_TASK]
            .apply(
                kwargs={
                    "work_item_id": str(frozen.context.work_item_id),
                    "need_index": 0,
                    "requested_by_user_id": str(uuid.uuid4()),
                }
            )
            .get()
        )
        assert unknown_user["status"] == "precondition_failed"
        assert "active user" in unknown_user["detail"]


class TestMediaHistoryCap:
    def test_history_truncates_truthfully(
        self, harness: Harness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import contentos.api.read_models.media as media_module

        accepted, _, _ = qa_review_context(harness)
        work_item_id = accepted.context.work_item_id
        with harness.session() as session:
            user = operator_user(session)
            service = MediaService(session, MediaStore(tmp_path / "media-store"))
            asset, _ = service.register_upload(
                PNG_BYTES,
                media_type="image/png",
                alt_text="Kapak",
                license_note="Arşiv",
                created_by=user,
            )
            session.commit()
            service.satisfy_need(work_item_id, 0, asset.id, user=user, reason="bağla")
            session.commit()
            service.unsatisfy_need(work_item_id, 0, user=user, reason="çöz")
            session.commit()
        monkeypatch.setattr(media_module, "MAX_MEDIA_HISTORY", 0)
        page = harness.get(f"/internal/editorial/work-items/{work_item_id}/media").json()
        assert page["history"] == []
        assert page["total_history"] == 1
        assert page["history_truncated"] is True
