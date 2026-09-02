"""Human decision tests (Phase 5 G3): records, gates, workflow wiring."""

import uuid

import pytest
from editorial_harness import (
    TEST_OPERATOR_USERNAME,
    Harness,
)
from sqlalchemy import select
from test_qa import qa_review_context

import contentos.decisions.models  # noqa: F401  (register tables before create_all)
from contentos.auth.enums import UserRole
from contentos.auth.service import AuthService
from contentos.decisions.enums import DecisionKind
from contentos.decisions.models import HumanDecision
from contentos.decisions.service import DecisionService
from contentos.drafts.models import ContentDraft
from contentos.qa.enums import WaivableGateKey
from contentos.qa.gates import QaGateEngine
from contentos.qa.service import QaService
from contentos.workflow.enums import WorkflowActorOrigin, WorkflowState
from contentos.workflow.models import EditorialWorkflowEvent
from contentos.workflow.service import WorkflowService


@pytest.fixture()
def harness() -> Harness:
    return Harness()


def awaiting_review_context(harness: Harness) -> tuple[object, uuid.UUID, uuid.UUID]:
    """QA_REVIEW package -> waiver -> ready report -> the SYSTEM terminal
    transition with the exact pins (mirroring run_qa_gates TX B).
    Returns (accepted, draft_id, qa_report_id)."""
    accepted, draft_id, _ = qa_review_context(harness)
    with harness.session() as session:
        QaService(session).add_waiver(
            accepted.context.work_item_id,  # type: ignore[attr-defined]
            WaivableGateKey.MEDIA_NEEDS,
            reason="görsel gereksinimi bilinçli olarak ertelendi",
        )
        session.commit()
        result = QaGateEngine(session).run_gates(
            accepted.context.work_item_id  # type: ignore[attr-defined]
        )
        session.commit()
        assert result.outcome.value == "ready_for_human_review"
        WorkflowService(session).transition(
            accepted.context.work_item_id,  # type: ignore[attr-defined]
            WorkflowState.AWAITING_HUMAN_REVIEW,
            actor_origin=WorkflowActorOrigin.SYSTEM,
            reason="qa report passed all hard gates",
            artifact_refs={
                "qa_report_id": str(result.report.id),
                "editorial_review_id": str(result.package.review.id),
                "content_draft_id": str(draft_id),
                "content_hash": result.package.draft.content_hash,
            },
        )
        session.commit()
        return accepted, draft_id, result.report.id


class TestApprove:
    def test_approve_records_and_advances_with_the_named_actor(self, harness: Harness) -> None:
        accepted, draft_id, report_id = awaiting_review_context(harness)
        response = harness.post(
            f"/internal/editorial/work-items/{accepted.context.work_item_id}/approve",
            {"reason": "paket eksiksiz; onaylıyorum"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "decided"
        assert body["decision"] == "approved"
        assert body["work_item_state"] == "approved"
        assert body["reviewer_username"] == TEST_OPERATOR_USERNAME

        with harness.session() as session:
            decision = session.execute(select(HumanDecision)).scalar_one()
            assert decision.decision is DecisionKind.APPROVED
            assert str(decision.qa_report_id) == str(report_id)
            assert str(decision.content_draft_id) == str(draft_id)
            assert decision.reason == "paket eksiksiz; onaylıyorum"
            event = (
                session.execute(
                    select(EditorialWorkflowEvent)
                    .where(EditorialWorkflowEvent.work_item_id == accepted.context.work_item_id)
                    .order_by(EditorialWorkflowEvent.id.desc())
                )
                .scalars()
                .first()
            )
            assert event is not None
            assert event.to_state is WorkflowState.APPROVED
            assert event.artifact_refs["human_decision_id"] == str(decision.id)
            assert event.artifact_refs["content_hash"] == decision.content_hash
            # The NAMED authenticated human is recorded on the event.
            assert event.actor_user_id == decision.reviewer_user_id

            status = DecisionService(session).approval_status(accepted.context.work_item_id)
            assert status.approved is True and status.current is True

    def test_changed_package_cannot_ride_an_old_qa_pass(self, harness: Harness) -> None:
        accepted, draft_id, _ = awaiting_review_context(harness)
        with harness.session() as session:
            # Simulate a mutated package (SQLite has no immutability trigger).
            draft = session.get(ContentDraft, draft_id)
            assert draft is not None
            draft.content_hash = "f" * 64
            session.commit()
        response = harness.post(
            f"/internal/editorial/work-items/{accepted.context.work_item_id}/approve",
            {"reason": "değişen paketi onaylamayı deniyorum"},
        )
        assert response.status_code == 409
        assert "hash mismatch" in response.json()["error"]["message"]
        with harness.session() as session:
            assert session.execute(select(HumanDecision)).scalar_one_or_none() is None

    def test_wrong_state_is_a_409(self, harness: Harness) -> None:
        accepted, _, _ = qa_review_context(harness)  # still QA_REVIEW
        response = harness.post(
            f"/internal/editorial/work-items/{accepted.context.work_item_id}/approve",
            {"reason": "erken onay"},
        )
        assert response.status_code == 409


class TestRoutedDecisions:
    def test_request_changes_routes_via_the_bounded_choice(self, harness: Harness) -> None:
        accepted, _, _ = awaiting_review_context(harness)
        response = harness.post(
            f"/internal/editorial/work-items/{accepted.context.work_item_id}/request-changes",
            {"reason": "başlık yeniden çalışılmalı", "responsible_state": "qa_review"},
        )
        assert response.status_code == 200
        assert response.json()["work_item_state"] == "changes_requested"
        resolve = harness.post(
            f"/internal/editorial/work-items/{accepted.context.work_item_id}"
            "/resolve-changes-requested",
            {"reason": "kalite kontrole geri yönlendirildi"},
        )
        assert resolve.status_code == 200
        assert resolve.json()["current_state"] == "qa_review"

    def test_reject_package_records_the_human_rejection(self, harness: Harness) -> None:
        accepted, _, _ = awaiting_review_context(harness)
        response = harness.post(
            f"/internal/editorial/work-items/{accepted.context.work_item_id}/reject-package",
            {"reason": "editoryal olarak yayımlanamaz"},
        )
        assert response.status_code == 200
        assert response.json()["work_item_state"] == "rejected"
        with harness.session() as session:
            decision = session.execute(select(HumanDecision)).scalar_one()
            assert decision.decision is DecisionKind.REJECTED

    def test_revoke_approval_references_never_edits(self, harness: Harness) -> None:
        accepted, _, _ = awaiting_review_context(harness)
        approve = harness.post(
            f"/internal/editorial/work-items/{accepted.context.work_item_id}/approve",
            {"reason": "onay"},
        )
        assert approve.status_code == 200
        approval_id = approve.json()["human_decision_id"]

        revoke = harness.post(
            f"/internal/editorial/work-items/{accepted.context.work_item_id}/revoke-approval",
            {"reason": "yeni bilgi geldi; geri çekiyorum", "responsible_state": "editing"},
        )
        assert revoke.status_code == 200
        assert revoke.json()["decision"] == "approval_revoked"
        assert revoke.json()["work_item_state"] == "changes_requested"
        with harness.session() as session:
            decisions = DecisionService(session).list_decisions(accepted.context.work_item_id)
            assert [d.decision.value for d in decisions] == [
                "approved",
                "approval_revoked",
            ]
            assert str(decisions[1].revokes_decision_id) == approval_id
            status = DecisionService(session).approval_status(accepted.context.work_item_id)
            assert status.approved is False

    def test_revoke_without_an_approval_conflicts(self, harness: Harness) -> None:
        accepted, _, _ = awaiting_review_context(harness)
        # Force APPROVED without a decision record (test-only shortcut).
        with harness.session() as session:
            WorkflowService(session).transition(
                accepted.context.work_item_id,
                WorkflowState.APPROVED,
                actor_origin=WorkflowActorOrigin.OPERATOR,
                reason="kayıtsız onay (test)",
            )
            session.commit()
        response = harness.post(
            f"/internal/editorial/work-items/{accepted.context.work_item_id}/revoke-approval",
            {"reason": "geri çek"},
        )
        assert response.status_code == 409


class TestRoleSeparation:
    def login_as(self, harness: Harness, username: str, password: str) -> str:
        response = harness.post(
            "/internal/auth/login", {"username": username, "password": password}
        )
        assert response.status_code == 200
        return response.json()["token"]

    def test_operator_only_user_cannot_decide(self, harness: Harness) -> None:
        accepted, _, _ = awaiting_review_context(harness)
        with harness.session() as session:
            AuthService(session).provision_user(
                "pure.operator",
                display_name="Sadece Operatör",
                password="a-long-operator-password",
                roles=[UserRole.OPERATOR],
                reason="rol testi",
            )
            session.commit()
        token = self.login_as(harness, "pure.operator", "a-long-operator-password")
        response = harness.post(
            f"/internal/editorial/work-items/{accepted.context.work_item_id}/approve",
            {"reason": "yetkisiz onay"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403
        with harness.session() as session:
            assert session.execute(select(HumanDecision)).scalar_one_or_none() is None

    def test_reviewer_only_user_can_decide_but_not_drive(self, harness: Harness) -> None:
        accepted, _, _ = awaiting_review_context(harness)
        with harness.session() as session:
            AuthService(session).provision_user(
                "pure.reviewer2",
                display_name="Sadece Hakem",
                password="a-long-reviewer-password",
                roles=[UserRole.REVIEWER],
                reason="rol testi",
            )
            session.commit()
        token = self.login_as(harness, "pure.reviewer2", "a-long-reviewer-password")
        headers = {"Authorization": f"Bearer {token}"}
        pipeline = harness.request("GET", "/internal/editorial/work-items", headers=headers)
        assert pipeline.status_code == 403
        decide = harness.post(
            f"/internal/editorial/work-items/{accepted.context.work_item_id}/approve",
            {"reason": "hakem onayı"},
            headers=headers,
        )
        assert decide.status_code == 200
        assert decide.json()["reviewer_username"] == "pure.reviewer2"
