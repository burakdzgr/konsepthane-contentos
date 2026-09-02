"""QA report persistence foundation tests (SQLite, real services)."""

import uuid

import pytest
from editorial_harness import TEST_OPERATOR_USERNAME, Harness
from sqlalchemy import func, select
from test_reviews import editing_context

import contentos.qa.models  # noqa: F401  (register tables before create_all)
from contentos.qa.enums import (
    QaActorOrigin,
    QaOutcome,
    QaReportStatus,
    WaivableGateKey,
)
from contentos.qa.errors import QaInputError, QaPackageError, QaPreconditionError
from contentos.qa.models import QaReport
from contentos.qa.repository import QaRepository
from contentos.qa.service import QaPackage, QaService
from contentos.reviews.service import ReviewService
from contentos.workflow.enums import WorkflowActorOrigin, WorkflowState
from contentos.workflow.service import WorkflowService


@pytest.fixture()
def harness() -> Harness:
    return Harness()


def qa_review_context(harness: Harness) -> tuple[object, uuid.UUID, uuid.UUID]:
    """EDITING -> ACTIVE pass review -> OPERATOR accept-review transition to
    QA_REVIEW with the exact pins (the runtime's artifact gate).
    Returns (accepted, draft_id, review_id)."""
    accepted, draft_id, _ = editing_context(harness)
    with harness.session() as session:
        creation = ReviewService(session).create_review(accepted.context.work_item_id, [])
        session.commit()
        review = creation.review
        WorkflowService(session).transition(
            accepted.context.work_item_id,
            WorkflowState.QA_REVIEW,
            actor_origin=WorkflowActorOrigin.OPERATOR,
            reason="inceleme temiz; kalite kontrole geç",
            artifact_refs={
                "editorial_review_id": str(review.id),
                "content_draft_id": str(draft_id),
                "review_verdict": review.verdict.value,
                "content_hash": "0" * 64,
            },
        )
        session.commit()
        return accepted, draft_id, review.id


def sample_gate_results() -> dict:
    return {
        "package_integrity": {"result": "pass"},
        "media_needs": {"result": "unsatisfied", "needs": 1},
    }


class TestPackageResolution:
    def test_resolves_the_exact_pinned_package(self, harness: Harness) -> None:
        accepted, draft_id, review_id = qa_review_context(harness)
        with harness.session() as session:
            package = QaService(session).resolve_package(accepted.context.work_item_id)
            assert package.draft.id == draft_id
            assert package.review.id == review_id
            assert package.brief.id == accepted.context.brief_id

    def test_requires_qa_review_state(self, harness: Harness) -> None:
        accepted, _, _ = editing_context(harness)  # still EDITING
        with harness.session() as session:
            with pytest.raises(QaPreconditionError, match="QA_REVIEW"):
                QaService(session).resolve_package(accepted.context.work_item_id)

    def test_requires_entry_pins(self, harness: Harness) -> None:
        accepted, _, _ = editing_context(harness)
        with harness.session() as session:
            # A structurally legal transition WITHOUT the pins: refuse.
            WorkflowService(session).transition(
                accepted.context.work_item_id,
                WorkflowState.QA_REVIEW,
                actor_origin=WorkflowActorOrigin.OPERATOR,
                reason="pinsiz geçiş (test)",
            )
            session.commit()
            with pytest.raises(QaPreconditionError, match="does not pin"):
                QaService(session).resolve_package(accepted.context.work_item_id)

    def test_missing_work_item_is_typed(self, harness: Harness) -> None:
        with harness.session() as session:
            with pytest.raises(QaPreconditionError, match="no editorial work item"):
                QaService(session).resolve_package(uuid.uuid4())


class TestReportPersistence:
    def persisted(
        self, harness: Harness, outcome: QaOutcome = QaOutcome.NOT_READY
    ) -> tuple[object, QaPackage, uuid.UUID]:
        accepted, _, _ = qa_review_context(harness)
        with harness.session() as session:
            service = QaService(session)
            package = service.resolve_package(accepted.context.work_item_id)
            persistence = service.persist_report(
                package,
                outcome=outcome,
                gate_results=sample_gate_results(),
                gate_policy_snapshot={"version": "qa-gates/1"},
            )
            session.commit()
            assert persistence.created is True
            return accepted, package, persistence.report.id

    def test_report_pins_the_package_and_snapshots(self, harness: Harness) -> None:
        accepted, package, report_id = self.persisted(harness)
        with harness.session() as session:
            report = QaRepository(session).get_report(report_id)
            assert report is not None
            assert report.version == 1
            assert report.status is QaReportStatus.ACTIVE
            assert report.outcome is QaOutcome.NOT_READY
            assert report.content_draft_id == package.draft.id
            assert report.editorial_review_id == package.review.id
            assert report.content_brief_id == package.brief.id
            assert report.engine_name == "qa"
            assert report.gate_policy_snapshot == {"version": "qa-gates/1"}
            assert report.gate_results["media_needs"]["result"] == "unsatisfied"

    def test_identical_rerun_is_idempotent(self, harness: Harness) -> None:
        accepted, package, report_id = self.persisted(harness)
        with harness.session() as session:
            service = QaService(session)
            again = service.persist_report(
                service.resolve_package(accepted.context.work_item_id),
                outcome=QaOutcome.NOT_READY,
                gate_results=sample_gate_results(),
                gate_policy_snapshot={"version": "qa-gates/1"},
            )
            session.commit()
            assert again.created is False
            assert again.report.id == report_id
            assert session.scalar(select(func.count()).select_from(QaReport)) == 1

    def test_changed_rerun_supersedes_with_system_audit(self, harness: Harness) -> None:
        accepted, package, report_id = self.persisted(harness)
        with harness.session() as session:
            service = QaService(session)
            changed = dict(sample_gate_results())
            changed["media_needs"] = {"result": "waived_by_human", "needs": 1}
            second = service.persist_report(
                service.resolve_package(accepted.context.work_item_id),
                outcome=QaOutcome.READY_FOR_HUMAN_REVIEW,
                gate_results=changed,
                gate_policy_snapshot={"version": "qa-gates/1"},
            )
            session.commit()
            assert second.created is True
            assert second.report.version == 2
            assert second.superseded_report_id == report_id
            repo = QaRepository(session)
            old = repo.get_report(report_id)
            assert old is not None
            assert old.status is QaReportStatus.SUPERSEDED
            assert old.superseded_by_report_id == second.report.id
            events = repo.list_status_events(report_id)
            assert len(events) == 1
            assert events[0].actor_origin is QaActorOrigin.SYSTEM
            assert events[0].replacement_report_id == second.report.id


class TestWaivers:
    def test_waiver_requires_qa_review_and_reason(self, harness: Harness) -> None:
        accepted, _, _ = editing_context(harness)
        with harness.session() as session:
            with pytest.raises(QaPreconditionError, match="QA_REVIEW"):
                QaService(session).add_waiver(
                    accepted.context.work_item_id,
                    WaivableGateKey.MEDIA_NEEDS,
                    reason="erken feragat",
                )

    def test_waiver_is_audited_and_listed(self, harness: Harness) -> None:
        accepted, _, _ = qa_review_context(harness)
        with harness.session() as session:
            service = QaService(session)
            with pytest.raises(QaInputError, match="reason"):
                service.add_waiver(
                    accepted.context.work_item_id,
                    WaivableGateKey.MEDIA_NEEDS,
                    reason="   ",
                )
            waiver = service.add_waiver(
                accepted.context.work_item_id,
                WaivableGateKey.MEDIA_NEEDS,
                reason="görsel gereksinimi bilinçli olarak ertelendi",
                request_id="qa-waiver-1",
            )
            session.commit()
            waivers = QaRepository(session).list_waivers(accepted.context.work_item_id)
            assert [row.id for row in waivers] == [waiver.id]
            assert waivers[0].gate_key is WaivableGateKey.MEDIA_NEEDS
            assert waivers[0].request_id == "qa-waiver-1"


class TestRepositorySurface:
    def test_repository_exposes_no_mutation_or_delete_surface(self) -> None:
        exposed = {name for name in dir(QaRepository) if not name.startswith("_")}
        assert exposed == {
            "insert_report",
            "append_waiver",
            "append_status_event",
            "get_report",
            "get_active_report",
            "list_by_work_item",
            "next_version",
            "list_waivers",
            "list_status_events",
        }

    def test_outcome_vocabulary_has_no_approval_or_failure_label(self) -> None:
        assert {outcome.value for outcome in QaOutcome} == {
            "ready_for_human_review",
            "not_ready",
        }


class TestGateEngine:
    """Task 17: the deterministic gate engine (media gate v2 in M3)."""

    def run(self, harness: Harness, work_item_id: uuid.UUID):
        from contentos.qa.gates import QaGateEngine

        with harness.session() as session:
            result = QaGateEngine(session).run_gates(work_item_id)
            session.commit()
            return result

    def test_default_run_is_not_ready_with_truthful_media_gate(self, harness: Harness) -> None:
        accepted, draft_id, review_id = qa_review_context(harness)
        result = self.run(harness, accepted.context.work_item_id)

        assert result.outcome is QaOutcome.NOT_READY
        gates = result.report.gate_results
        # The harness brief HAS media needs and nothing can evaluate them:
        # the gate blocks truthfully instead of silently passing.
        assert gates["media_needs"]["result"] == "unsatisfied"
        assert gates["media_needs"]["needs"] >= 1
        # v2: the EXACT unmet indexes, never a count that hides which.
        assert gates["media_needs"]["unmet_indexes"] == [0]
        # Everything provable passes and is recorded explicitly.
        assert gates["package_integrity"]["result"] == "pass"
        assert gates["provenance_chain"]["result"] == "pass"
        assert gates["provenance_chain"]["evidence_links"] >= 1
        assert gates["writer_envelope"]["result"] == "pass"
        assert gates["content_safety"]["result"] == "pass"
        assert gates["editorial_review_currency"]["result"] == "pass"
        # Link needs are reported, non-blocking.
        assert gates["internal_link_needs"]["result"] == "pending"
        assert gates["internal_link_needs"]["blocking"] is False
        assert result.report.gate_policy_snapshot["version"] == "qa-gates/2"
        assert result.report.content_draft_id == draft_id
        assert result.report.editorial_review_id == review_id

    def test_waiver_consumption_yields_ready(self, harness: Harness) -> None:
        accepted, _, _ = qa_review_context(harness)
        first = self.run(harness, accepted.context.work_item_id)
        assert first.outcome is QaOutcome.NOT_READY

        with harness.session() as session:
            waiver = QaService(session).add_waiver(
                accepted.context.work_item_id,
                WaivableGateKey.MEDIA_NEEDS,
                reason="görsel gereksinimi bilinçli olarak ertelendi",
            )
            session.commit()
            waiver_id = str(waiver.id)

        second = self.run(harness, accepted.context.work_item_id)
        assert second.outcome is QaOutcome.READY_FOR_HUMAN_REVIEW
        media = second.report.gate_results["media_needs"]
        assert media["result"] == "waived_by_human"
        assert media["waiver_ids"] == [waiver_id]
        assert media["needs"] >= 1  # the needs stay visible
        assert media["unmet_indexes"] == [0]  # the waiver hides nothing
        assert second.report.version == 2
        with harness.session() as session:
            old = QaRepository(session).get_report(first.report.id)
            assert old is not None and old.status is QaReportStatus.SUPERSEDED

    def test_satisfied_needs_yield_ready_without_a_waiver(self, harness: Harness) -> None:
        import tempfile
        from pathlib import Path

        from sqlalchemy import select as _select

        from contentos.auth.models import User
        from contentos.media.service import MediaService
        from contentos.media.store import MediaStore

        accepted, _, _ = qa_review_context(harness)
        first = self.run(harness, accepted.context.work_item_id)
        assert first.outcome is QaOutcome.NOT_READY
        assert first.report.gate_policy_snapshot["version"] == "qa-gates/2"

        with harness.session() as session:
            user = session.execute(
                _select(User).where(User.username == TEST_OPERATOR_USERNAME)
            ).scalar_one()
            service = MediaService(
                session, MediaStore(Path(tempfile.mkdtemp(prefix="contentos-qa-media-")))
            )
            asset, _ = service.register_upload(
                b"\x89PNG\r\n\x1a\n" + b"qa-gate-test-image",
                media_type="image/png",
                alt_text="Kapak görseli",
                license_note="Konsepthane arşivi",
                created_by=user,
            )
            session.commit()
            service.satisfy_need(
                accepted.context.work_item_id,
                0,
                asset.id,
                user=user,
                reason="kapak ihtiyacı gerçek görselle karşılandı",
            )
            session.commit()

        second = self.run(harness, accepted.context.work_item_id)
        assert second.outcome is QaOutcome.READY_FOR_HUMAN_REVIEW
        media = second.report.gate_results["media_needs"]
        assert media["result"] == "satisfied"
        assert media["satisfied"] == media["needs"] == 1
        # The superseded first report keeps its own recorded truth.
        with harness.session() as session:
            old = QaRepository(session).get_report(first.report.id)
            assert old is not None
            assert old.gate_results["media_needs"]["result"] == "unsatisfied"
            assert old.gate_policy_snapshot["version"] == "qa-gates/2"

    def test_old_reports_stay_under_their_recorded_policy_version(self, harness: Harness) -> None:
        accepted, draft_id, review_id = qa_review_context(harness)
        with harness.session() as session:
            service = QaService(session)
            package = service.resolve_package(accepted.context.work_item_id)
            # A historical report recorded under qa-gates/1 (pre-M3).
            service.persist_report(
                package,
                outcome=QaOutcome.NOT_READY,
                gate_results={"media_needs": {"result": "unsatisfied", "needs": 1}},
                gate_policy_snapshot={"version": "qa-gates/1"},
            )
            session.commit()

        result = self.run(harness, accepted.context.work_item_id)
        assert result.report.gate_policy_snapshot["version"] == "qa-gates/2"
        with harness.session() as session:
            reports = QaRepository(session).list_by_work_item(accepted.context.work_item_id)
            versions = {report.gate_policy_snapshot["version"]: report.status for report in reports}
            # The v1 report survives untouched under its own version.
            assert versions["qa-gates/1"] is QaReportStatus.SUPERSEDED
            assert versions["qa-gates/2"] is QaReportStatus.ACTIVE

    def test_identical_rerun_reuses_the_report(self, harness: Harness) -> None:
        accepted, _, _ = qa_review_context(harness)
        first = self.run(harness, accepted.context.work_item_id)
        second = self.run(harness, accepted.context.work_item_id)
        assert second.created is False
        assert second.report.id == first.report.id

    def test_broken_provenance_fails_closed(self, harness: Harness) -> None:
        from contentos.briefs.models import BriefClaimEvidence

        accepted, _, _ = qa_review_context(harness)
        with harness.session() as session:
            # SQLite harness has no append-only trigger: simulate corrupted
            # durable provenance by removing the used claim's evidence links.
            for link in session.execute(select(BriefClaimEvidence)).scalars().all():
                if link.claim_id == accepted.claim_ids[0]:  # type: ignore[attr-defined]
                    session.delete(link)
            session.commit()

        result = self.run(harness, accepted.context.work_item_id)
        assert result.outcome is QaOutcome.NOT_READY
        chain = result.report.gate_results["provenance_chain"]
        assert chain["result"] == "fail"
        assert str(accepted.claim_ids[0]) in chain["broken_claims"]  # type: ignore[attr-defined]

    def test_unsafe_content_fails_closed(self, harness: Harness) -> None:
        from contentos.drafts.models import ContentDraft

        accepted, draft_id, _ = qa_review_context(harness)
        with harness.session() as session:
            draft = session.get(ContentDraft, draft_id)
            assert draft is not None
            body = {
                "sections": [
                    {**section, "blocks": [dict(block) for block in section["blocks"]]}
                    for section in draft.body["sections"]
                ]
            }
            body["sections"][0]["blocks"][0]["text"] = "Ayrıntı için https://ornek.com"
            draft.body = body
            session.commit()

        result = self.run(harness, accepted.context.work_item_id)
        assert result.outcome is QaOutcome.NOT_READY
        safety = result.report.gate_results["content_safety"]
        assert safety["result"] == "fail"
        assert "giris-1" in safety["unsafe_anchors"]

    def test_stale_review_scope_fails_currency(self, harness: Harness) -> None:
        from contentos.reviews.models import EditorialReview

        accepted, _, review_id = qa_review_context(harness)
        with harness.session() as session:
            review = session.get(EditorialReview, review_id)
            assert review is not None
            review.review_scope = {
                **review.review_scope,
                "draft_content_hash": "f" * 64,
            }
            session.commit()

        result = self.run(harness, accepted.context.work_item_id)
        assert result.outcome is QaOutcome.NOT_READY
        currency = result.report.gate_results["editorial_review_currency"]
        assert currency["result"] == "fail"
        assert currency["checks"]["scope_draft_hash_current"] is False


class TestPackageGates:
    def test_revise_review_pin_is_a_package_error(self, harness: Harness) -> None:
        from contentos.reviews.enums import (
            FindingDimension,
            FindingOrigin,
            FindingSeverity,
        )
        from contentos.reviews.values import ReviewFindingInput

        accepted, draft_id, _ = editing_context(harness)
        with harness.session() as session:
            creation = ReviewService(session).create_review(
                accepted.context.work_item_id,
                [
                    ReviewFindingInput(
                        finding_key="iddia-abartili",
                        dimension=FindingDimension.CLAIM_FAITHFULNESS,
                        severity=FindingSeverity.BLOCKING,
                        origin=FindingOrigin.MODEL_SIGNAL,
                        description="Metin iddiadan daha kesin konuşuyor.",
                        block_id="giris-2",
                    )
                ],
            )
            session.commit()
            # Force the structurally legal transition with a revise pin (the
            # API refuses this; the domain must also fail closed).
            WorkflowService(session).transition(
                accepted.context.work_item_id,
                WorkflowState.QA_REVIEW,
                actor_origin=WorkflowActorOrigin.OPERATOR,
                reason="revize kararına rağmen geçiş (test)",
                artifact_refs={
                    "editorial_review_id": str(creation.review.id),
                    "content_draft_id": str(draft_id),
                },
            )
            session.commit()
            with pytest.raises(QaPackageError, match="not 'pass'"):
                QaService(session).resolve_package(accepted.context.work_item_id)
