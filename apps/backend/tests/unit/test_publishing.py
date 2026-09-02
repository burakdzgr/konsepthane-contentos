"""Publication package foundation tests (Phase 7 P1)."""

import uuid
from pathlib import Path

import pytest
from editorial_harness import TEST_OPERATOR_USERNAME, Harness
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_decisions import awaiting_review_context

import contentos.publishing.models  # noqa: F401  (register tables before create_all)
from contentos.auth.models import User
from contentos.decisions.errors import StaleApprovalError
from contentos.drafts.models import ContentDraft
from contentos.media.service import MediaService
from contentos.media.store import MediaStore
from contentos.publishing.assembler import PublicationAssembler
from contentos.publishing.models import PublicationPackage
from contentos.publishing.values import PACKAGE_SCHEMA_VERSION

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"publication-test-image"


@pytest.fixture()
def harness() -> Harness:
    return Harness()


def operator_user(session: Session) -> User:
    return session.execute(select(User).where(User.username == TEST_OPERATOR_USERNAME)).scalar_one()


def approved_context(harness: Harness) -> tuple[object, uuid.UUID]:
    """Full chain to APPROVED via the real reviewer route (media waived
    inside awaiting_review_context's QA run)."""
    accepted, draft_id, _ = awaiting_review_context(harness)
    approve = harness.post(
        f"/internal/editorial/work-items/{accepted.context.work_item_id}/approve",
        {"reason": "paket eksiksiz; onaylıyorum"},
    )
    assert approve.status_code == 200, approve.text
    return accepted, draft_id


class TestAssembly:
    def test_assembles_the_exact_approved_package_with_the_waived_manifest(
        self, harness: Harness
    ) -> None:
        accepted, draft_id = approved_context(harness)
        work_item_id = accepted.context.work_item_id
        with harness.session() as session:
            user = operator_user(session)
            result = PublicationAssembler(session).assemble(work_item_id, assembled_by=user)
            session.commit()
            assert result.created is True
            package = result.package
            assert package.version == 1
            assert package.payload_schema_version == PACKAGE_SCHEMA_VERSION
            assert package.content_draft_id == draft_id
            draft = session.get(ContentDraft, draft_id)
            assert draft is not None
            # The approved structure VERBATIM, pinned by the approved hash.
            assert package.content_hash == draft.content_hash
            assert package.payload["body"] == draft.body
            assert package.payload["title_proposal"] == draft.title_proposal
            # The conscious media deferral stays visible, never hidden.
            assert package.media_manifest["waived_unmet_indexes"] == [0]
            assert package.media_manifest["needs"] == {}
            assert package.assembled_by_user_id == user.id

            # Idempotent: identical content converges on the same package.
            again = PublicationAssembler(session).assemble(work_item_id, assembled_by=user)
            assert again.created is False
            assert again.package.id == package.id
            assert session.execute(select(PublicationPackage)).scalars().all().__len__() == 1

    def test_manifest_carries_the_bound_assets(self, harness: Harness, tmp_path: Path) -> None:
        from test_qa import qa_review_context

        # Bind the media BEFORE the QA run: QA_REVIEW is inside the media
        # command window, so the gates see genuine satisfied coverage.
        accepted, _, _ = qa_review_context(harness)
        work_item_id = accepted.context.work_item_id

        with harness.session() as session:
            user = operator_user(session)
            service = MediaService(session, MediaStore(tmp_path / "media-store"))
            asset, _ = service.register_upload(
                PNG_BYTES,
                media_type="image/png",
                alt_text="Kapak görseli",
                license_note="Konsepthane arşivi",
                created_by=user,
            )
            session.commit()
            service.satisfy_need(work_item_id, 0, asset.id, user=user, reason="kapak karşılandı")
            session.commit()
            asset_id = str(asset.id)

        from contentos.qa.gates import QaGateEngine
        from contentos.workflow.enums import WorkflowActorOrigin, WorkflowState
        from contentos.workflow.service import WorkflowService

        with harness.session() as session:
            gate_run = QaGateEngine(session).run_gates(work_item_id)
            session.commit()
            assert gate_run.outcome.value == "ready_for_human_review"
            assert gate_run.report.gate_results["media_needs"]["result"] == "satisfied"
            WorkflowService(session).transition(
                work_item_id,
                WorkflowState.AWAITING_HUMAN_REVIEW,
                actor_origin=WorkflowActorOrigin.SYSTEM,
                reason="qa report passed all hard gates",
                artifact_refs={
                    "qa_report_id": str(gate_run.report.id),
                    "editorial_review_id": str(gate_run.package.review.id),
                    "content_draft_id": str(gate_run.package.draft.id),
                    "content_hash": gate_run.package.draft.content_hash,
                },
            )
            session.commit()
        approve = harness.post(
            f"/internal/editorial/work-items/{work_item_id}/approve",
            {"reason": "görselli paket onayı"},
        )
        assert approve.status_code == 200, approve.text

        with harness.session() as session:
            result = PublicationAssembler(session).assemble(
                work_item_id, assembled_by=operator_user(session)
            )
            session.commit()
            manifest = result.package.media_manifest
            assert manifest["waived_unmet_indexes"] == []
            entry = manifest["needs"]["0"]
            assert entry["media_asset_id"] == asset_id
            assert entry["alt_text"] == "Kapak görseli"
            assert entry["license_note"] == "Konsepthane arşivi"
            assert entry["origin"] == "human_upload"

    def test_refuses_outside_approved_and_without_current_approval(self, harness: Harness) -> None:
        accepted, draft_id, _ = awaiting_review_context(harness)
        work_item_id = accepted.context.work_item_id
        with harness.session() as session:
            user = operator_user(session)
            # No approval at all: the guard refuses first.
            with pytest.raises(StaleApprovalError, match="no approval is on record"):
                PublicationAssembler(session).assemble(work_item_id, assembled_by=user)

        approve = harness.post(
            f"/internal/editorial/work-items/{work_item_id}/approve",
            {"reason": "onay"},
        )
        assert approve.status_code == 200
        with harness.session() as session:
            # Simulated drift (SQLite, no trigger): the approval goes stale.
            draft = session.get(ContentDraft, draft_id)
            assert draft is not None
            draft.content_hash = "e" * 64
            session.commit()
            with pytest.raises(StaleApprovalError, match="no longer matches"):
                PublicationAssembler(session).assemble(
                    work_item_id, assembled_by=operator_user(session)
                )
            # A stale approval left ZERO package rows behind.
            assert session.execute(select(PublicationPackage)).scalar_one_or_none() is None

    def test_refuses_unmet_unwaived_media_needs(self, harness: Harness) -> None:
        from test_qa import qa_review_context

        from contentos.workflow.enums import WorkflowActorOrigin, WorkflowState
        from contentos.workflow.service import WorkflowService

        accepted, draft_id, review_id = qa_review_context(harness)
        work_item_id = accepted.context.work_item_id
        # Force the terminal chain WITHOUT a waiver or satisfaction: run the
        # gates (not_ready — media unsatisfied) then a raw transition and a
        # forged approval path is impossible; instead assemble directly in a
        # forced APPROVED state to prove the media gate inside ASSEMBLY.
        from contentos.qa.gates import QaGateEngine

        with harness.session() as session:
            gate_run = QaGateEngine(session).run_gates(work_item_id)
            session.commit()
            assert gate_run.outcome.value == "not_ready"
            service = WorkflowService(session)
            service.transition(
                work_item_id,
                WorkflowState.AWAITING_HUMAN_REVIEW,
                actor_origin=WorkflowActorOrigin.SYSTEM,
                reason="test: zorlanmış geçiş",
                artifact_refs={
                    "qa_report_id": str(gate_run.report.id),
                    "editorial_review_id": str(review_id),
                    "content_draft_id": str(draft_id),
                    "content_hash": gate_run.package.draft.content_hash,
                },
            )
            session.commit()
        approve = harness.post(
            f"/internal/editorial/work-items/{work_item_id}/approve",
            {"reason": "onay denemesi"},
        )
        # The decision layer already refuses a not_ready report: publishing
        # can only ever see approved packages — assembly's own media check
        # is defense in depth behind that gate.
        assert approve.status_code == 409
        assert "ready_for_human_review" in approve.json()["error"]["message"]


class TestScheduling:
    """P2: humans schedule, gated on the current approval + the package."""

    def assembled(self, harness: Harness) -> tuple[uuid.UUID, str]:
        accepted, _ = approved_context(harness)
        work_item_id = accepted.context.work_item_id
        response = harness.post(
            f"/internal/editorial/work-items/{work_item_id}/assemble-publication-package"
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "assembled"
        return work_item_id, response.json()["publication_package_id"]

    def test_schedule_pins_the_package_and_the_named_actor(self, harness: Harness) -> None:
        from contentos.workflow.models import EditorialWorkflowEvent

        work_item_id, package_id = self.assembled(harness)
        response = harness.post(
            f"/internal/editorial/work-items/{work_item_id}/schedule-publication",
            {"publication_package_id": package_id, "reason": "yayın planına alındı"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["current_state"] == "scheduled"
        with harness.session() as session:
            event = (
                session.execute(
                    select(EditorialWorkflowEvent)
                    .where(EditorialWorkflowEvent.work_item_id == work_item_id)
                    .order_by(EditorialWorkflowEvent.id.desc())
                )
                .scalars()
                .first()
            )
            assert event is not None
            assert event.to_state.value == "scheduled"
            assert event.artifact_refs["publication_package_id"] == package_id
            assert event.artifact_refs["human_decision_id"]
            assert event.artifact_refs["package_hash"]
            assert event.actor_user_id is not None  # the named human scheduler

    def test_schedule_refusals(self, harness: Harness) -> None:
        work_item_id, package_id = self.assembled(harness)

        unknown = harness.post(
            f"/internal/editorial/work-items/{work_item_id}/schedule-publication",
            {"publication_package_id": str(uuid.uuid4()), "reason": "yanlış paket"},
        )
        assert unknown.status_code == 409

        ok = harness.post(
            f"/internal/editorial/work-items/{work_item_id}/schedule-publication",
            {"publication_package_id": package_id, "reason": "planla"},
        )
        assert ok.status_code == 200
        again = harness.post(
            f"/internal/editorial/work-items/{work_item_id}/schedule-publication",
            {"publication_package_id": package_id, "reason": "tekrar planla"},
        )
        assert again.status_code == 409  # SCHEDULED is not APPROVED

    def test_schedule_refuses_a_stale_approval(self, harness: Harness) -> None:
        work_item_id, package_id = self.assembled(harness)
        with harness.session() as session:
            draft = session.execute(select(ContentDraft)).scalars().first()
            assert draft is not None
            draft.content_hash = "e" * 64  # simulated drift (SQLite, no trigger)
            session.commit()
        response = harness.post(
            f"/internal/editorial/work-items/{work_item_id}/schedule-publication",
            {"publication_package_id": package_id, "reason": "bayat onayla planla"},
        )
        assert response.status_code == 409
        assert "no longer matches" in response.json()["error"]["message"]


class TestExpiryResolution:
    """P2: the derived route out of APPROVAL_EXPIRED."""

    def expired_context(self, harness: Harness) -> uuid.UUID:
        from contentos.decisions.service import DecisionService

        scheduler = TestScheduling()
        work_item_id, package_id = scheduler.assembled(harness)
        ok = harness.post(
            f"/internal/editorial/work-items/{work_item_id}/schedule-publication",
            {"publication_package_id": package_id, "reason": "planla"},
        )
        assert ok.status_code == 200
        with harness.session() as session:
            draft = session.execute(select(ContentDraft)).scalars().first()
            assert draft is not None
            draft.content_hash = "d" * 64  # drift: the approval goes stale
            session.commit()
            DecisionService(session).expire_stale_approval(
                work_item_id, reason="onaylanan içerik artık aktif taslak değil"
            )
            session.commit()
        return work_item_id

    def test_routes_back_to_awaiting_when_the_report_still_covers(self, harness: Harness) -> None:
        work_item_id = self.expired_context(harness)
        response = harness.post(
            f"/internal/editorial/work-items/{work_item_id}/resolve-approval-expired",
            {"reason": "paket yeniden insan incelemesine dönsün"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["current_state"] == "awaiting_human_review"

        # The re-entry pins are real: a fresh approval works immediately.
        approve = harness.post(
            f"/internal/editorial/work-items/{work_item_id}/approve",
            {"reason": "güncel içerik yeniden onaylandı"},
        )
        assert approve.status_code == 200, approve.text

    def test_routes_to_qa_review_when_the_report_no_longer_covers(self, harness: Harness) -> None:
        from contentos.qa.enums import QaReportStatus
        from contentos.qa.models import QaReport

        work_item_id = self.expired_context(harness)
        with harness.session() as session:
            report = session.execute(select(QaReport)).scalars().first()
            assert report is not None
            report.status = QaReportStatus.SUPERSEDED  # test knob (no trigger)
            session.commit()
        response = harness.post(
            f"/internal/editorial/work-items/{work_item_id}/resolve-approval-expired",
            {"reason": "rapor artık geçerli değil; kalite kontrole dön"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["current_state"] == "qa_review"

    def test_resolution_requires_the_expired_state(self, harness: Harness) -> None:
        accepted, _ = approved_context(harness)
        response = harness.post(
            f"/internal/editorial/work-items/{accepted.context.work_item_id}"
            "/resolve-approval-expired",
            {"reason": "erken çözüm denemesi"},
        )
        assert response.status_code == 409


class TestPublishTask:
    """P3: the governed dispatch behind the transport boundary."""

    def worker_app(self, harness: Harness, transport=None):
        from contentos.core.config import Environment, LogLevel, Settings
        from contentos.queue.celery import create_celery_app
        from contentos.worker.editorial_tasks import register_editorial_pipeline_tasks
        from contentos.worker.runtime import WorkerRuntime

        settings = Settings(
            environment=Environment.TEST,
            service_name="ContentOS Publish Task Test",
            application_version="1.0.0-test",
            log_level=LogLevel.INFO,
            api_docs_enabled=False,
            celery_task_always_eager=True,
            celery_broker_connection_retry_on_startup=False,
        )
        runtime = WorkerRuntime(
            settings,
            session_factory=harness.session_factory,
            publishing_transport_factory=((lambda: transport) if transport is not None else None),
        )
        app = create_celery_app(settings)
        register_editorial_pipeline_tasks(app, runtime)
        return app

    def scheduled(self, harness: Harness) -> tuple[uuid.UUID, str]:
        scheduler = TestScheduling()
        work_item_id, package_id = scheduler.assembled(harness)
        ok = harness.post(
            f"/internal/editorial/work-items/{work_item_id}/schedule-publication",
            {"publication_package_id": package_id, "reason": "yayin planina alindi"},
        )
        assert ok.status_code == 200
        return work_item_id, package_id

    def run(self, app, work_item_id: uuid.UUID) -> dict:
        from contentos.worker.editorial_tasks import PUBLISH_PACKAGE_TASK

        return (
            app.tasks[PUBLISH_PACKAGE_TASK].apply(kwargs={"work_item_id": str(work_item_id)}).get()
        )

    def test_successful_dispatch_publishes_with_pins_and_idempotency(
        self, harness: Harness
    ) -> None:
        from contentos.publishing.models import PublicationAttempt
        from contentos.publishing.transport import FakePublishingTransport, TransportOutcome
        from contentos.workflow.models import EditorialWorkflowEvent
        from contentos.workflow.repository import WorkflowRepository

        work_item_id, package_id = self.scheduled(harness)
        transport = FakePublishingTransport(
            outcome=TransportOutcome(
                status="succeeded", remote_publication_ref="konsepthane-pub-42"
            )
        )
        app = self.worker_app(harness, transport)
        result = self.run(app, work_item_id)
        assert result["status"] == "completed", result
        assert result["remote_publication_ref"] == "konsepthane-pub-42"

        with harness.session() as session:
            item = WorkflowRepository(session).get_by_id(work_item_id)
            assert item is not None and item.current_state.value == "published"
            attempt = session.execute(select(PublicationAttempt)).scalar_one()
            assert attempt.status == "succeeded"
            assert attempt.remote_publication_ref == "konsepthane-pub-42"
            assert attempt.idempotency_key.startswith("contentos-pub-")
            assert transport.calls[0]["idempotency_key"] == attempt.idempotency_key
            event = (
                session.execute(
                    select(EditorialWorkflowEvent)
                    .where(EditorialWorkflowEvent.work_item_id == work_item_id)
                    .order_by(EditorialWorkflowEvent.id.desc())
                )
                .scalars()
                .first()
            )
            assert event is not None and event.to_state.value == "published"
            assert event.artifact_refs["publication_package_id"] == package_id
            assert event.artifact_refs["remote_publication_ref"] == "konsepthane-pub-42"

        # Redelivery: reused, no second dispatch, no new attempt.
        again = self.run(app, work_item_id)
        assert again["status"] == "reused"
        assert len(transport.calls) == 1
        with harness.session() as session:
            assert len(session.execute(select(PublicationAttempt)).scalars().all()) == 1

    def test_stale_approval_expires_instead_of_publishing(self, harness: Harness) -> None:
        from contentos.publishing.models import PublicationAttempt
        from contentos.publishing.transport import FakePublishingTransport
        from contentos.workflow.repository import WorkflowRepository

        work_item_id, _ = self.scheduled(harness)
        with harness.session() as session:
            draft = session.execute(select(ContentDraft)).scalars().first()
            assert draft is not None
            draft.content_hash = "d" * 64  # drift: the approval goes stale
            session.commit()
        transport = FakePublishingTransport()
        app = self.worker_app(harness, transport)
        result = self.run(app, work_item_id)
        assert result["status"] == "approval_expired"
        assert transport.calls == []  # nothing was dispatched
        with harness.session() as session:
            item = WorkflowRepository(session).get_by_id(work_item_id)
            assert item is not None and item.current_state.value == "approval_expired"
            assert session.execute(select(PublicationAttempt)).scalar_one_or_none() is None

    def test_terminal_rejection_blocks_never_rejects(self, harness: Harness) -> None:
        from contentos.publishing.models import PublicationAttempt
        from contentos.publishing.transport import FakePublishingTransport, TransportOutcome
        from contentos.workflow.repository import WorkflowRepository

        work_item_id, _ = self.scheduled(harness)
        transport = FakePublishingTransport(
            outcome=TransportOutcome(
                status="rejected_by_api", error_class="publishing_api_rejected_422"
            )
        )
        app = self.worker_app(harness, transport)
        result = self.run(app, work_item_id)
        assert result["status"] == "publish_failed"
        with harness.session() as session:
            item = WorkflowRepository(session).get_by_id(work_item_id)
            assert item is not None
            # Execution failure is NEVER an editorial decision.
            assert item.current_state.value == "blocked"
            assert item.rejected_reason is None
            assert "publishing_api_rejected_422" in (item.blocked_reason or "")
            attempt = session.execute(select(PublicationAttempt)).scalar_one()
            assert attempt.status == "rejected_by_api"
            assert attempt.remote_publication_ref is None

    def test_unconfigured_transport_is_a_truthful_noop(self, harness: Harness) -> None:
        from contentos.workflow.repository import WorkflowRepository

        work_item_id, _ = self.scheduled(harness)
        app = self.worker_app(harness, transport=None)  # no factory, no settings
        result = self.run(app, work_item_id)
        assert result["status"] == "transport_unconfigured"
        assert "CONTENTOS_PUBLISHING_API_URL" in result["detail"]
        with harness.session() as session:
            item = WorkflowRepository(session).get_by_id(work_item_id)
            assert item is not None and item.current_state.value == "scheduled"

    def test_publish_command_queues_only_from_publishing_states(self, harness: Harness) -> None:
        work_item_id, _ = self.scheduled(harness)
        before = len(harness.dispatcher.calls)
        response = harness.post(f"/internal/editorial/work-items/{work_item_id}/publish")
        assert response.status_code == 200
        assert response.json() == {
            "status": "queued",
            "task": "publish_package",
            "entity_id": str(work_item_id),
        }
        new_calls = harness.dispatcher.calls[before:]
        assert len(new_calls) == 1 and new_calls[0][0] == "publish_package"

        accepted, _ = approved_context(harness)
        early = harness.post(
            f"/internal/editorial/work-items/{accepted.context.work_item_id}/publish"
        )
        assert early.status_code == 409
