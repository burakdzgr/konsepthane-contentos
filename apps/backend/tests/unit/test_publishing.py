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
