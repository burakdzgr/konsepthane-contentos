"""Editorial control API tests (SQLite, real services, fake dispatchers)."""

import uuid

import pytest
from editorial_harness import (
    NOW,
    Context,
    FailingEditorialDispatcher,
    Harness,
    seed_briefing,
    seed_commissioned,
    seed_documents,
    seed_draft_brief,
    seed_ready_pack,
    seed_scored,
    seed_selected_idea,
)
from sqlalchemy import func, select

from contentos.briefs.enums import BriefStatus
from contentos.briefs.models import BriefStatusEvent, ContentBrief
from contentos.duplicates.enums import DuplicateDecisionOutcome
from contentos.duplicates.models import DuplicateDecision
from contentos.evidence_packs.enums import (
    ContradictionResolutionStatus,
    EvidencePackSufficiency,
)
from contentos.evidence_packs.models import EvidenceContradiction, EvidencePack
from contentos.ideas.models import IdeaSelectionEvent
from contentos.opportunities.enums import OpportunityDisposition, ScoreEligibility
from contentos.opportunities.repository import OpportunityRepository
from contentos.workflow.enums import WorkflowActorOrigin, WorkflowState
from contentos.workflow.models import EditorialWorkflowEvent, EditorialWorkItem
from contentos.workflow.service import WorkflowService


@pytest.fixture()
def harness() -> Harness:
    return Harness()


def workflow_event_count(harness: Harness, work_item_id: uuid.UUID) -> int:
    with harness.session() as session:
        return int(
            session.scalar(
                select(func.count())
                .select_from(EditorialWorkflowEvent)
                .where(EditorialWorkflowEvent.work_item_id == work_item_id)
            )
            or 0
        )


def work_item_state(harness: Harness, work_item_id: uuid.UUID) -> WorkflowState:
    with harness.session() as session:
        item = session.get(EditorialWorkItem, work_item_id)
        assert item is not None
        return item.current_state


class TestCommission:
    def test_happy_then_idempotent(self, harness: Harness) -> None:
        with harness.session() as session:
            context = Context()
            seed_scored(session, context)
        response = harness.post(
            f"/internal/editorial/opportunities/{context.opportunity_id}/commission",
            {"reason": "güçlü skor, komisyon"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "commissioned"
        assert body["disposition"] == "commissioned"
        assert body["work_item_state"] == "evidence_building"
        assert body["opportunity_score_id"] == str(context.score_id)
        events_after = workflow_event_count(harness, context.work_item_id)
        assert events_after == 2  # creation + one commissioning event

        repeat = harness.post(
            f"/internal/editorial/opportunities/{context.opportunity_id}/commission",
            {"reason": "tekrar"},
        )
        assert repeat.status_code == 200
        assert repeat.json()["status"] == "already_commissioned"
        assert workflow_event_count(harness, context.work_item_id) == events_after

    def test_gate_fails_closed(self, harness: Harness) -> None:
        with harness.session() as session:
            context = Context()
            seed_scored(session, context, eligibility=ScoreEligibility.NEEDS_OPERATOR_REVIEW)
        response = harness.post(
            f"/internal/editorial/opportunities/{context.opportunity_id}/commission",
            {"reason": "denemek istiyorum"},
        )
        assert response.status_code == 409
        assert "needs_operator_review" in response.json()["error"]["message"]
        assert work_item_state(harness, context.work_item_id) is WorkflowState.IDEA_SCORING

    def test_not_found(self, harness: Harness) -> None:
        response = harness.post(
            f"/internal/editorial/opportunities/{uuid.uuid4()}/commission",
            {"reason": "yok"},
        )
        assert response.status_code == 404


class TestReject:
    def test_happy_path(self, harness: Harness) -> None:
        with harness.session() as session:
            context = Context()
            seed_scored(session, context)
        response = harness.post(
            f"/internal/editorial/opportunities/{context.opportunity_id}/reject",
            {"reason": "editoryal olarak uygun değil"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "rejected"
        assert body["disposition"] == "rejected"
        assert body["work_item_state"] == "rejected"
        with harness.session() as session:
            opportunity = OpportunityRepository(session).get_by_id(context.opportunity_id)
            assert opportunity is not None
            assert opportunity.disposition is OpportunityDisposition.REJECTED
            assert opportunity.disposition_reason == "editoryal olarak uygun değil"
            item = session.get(EditorialWorkItem, context.work_item_id)
            assert item is not None
            assert item.rejected_reason == "editoryal olarak uygun değil"

    def test_commissioned_cannot_be_rejected(self, harness: Harness) -> None:
        with harness.session() as session:
            context = Context()
            seed_commissioned(session, context)
        response = harness.post(
            f"/internal/editorial/opportunities/{context.opportunity_id}/reject",
            {"reason": "geç kaldım"},
        )
        assert response.status_code == 409


class TestQueueCommands:
    def test_promote_queues_exact_task(self, harness: Harness) -> None:
        with harness.session() as session:
            document_ids = seed_documents(session)
        response = harness.post(
            f"/internal/editorial/research/{document_ids[0]}/promote",
            headers={"X-Request-ID": "operator-req-14"},
        )
        assert response.status_code == 200
        assert response.json() == {
            "status": "queued",
            "task": "promote_research",
            "entity_id": str(document_ids[0]),
        }
        [(task, payload, request_id)] = harness.dispatcher.calls
        assert task == "promote_research"
        assert payload == {"normalized_document_id": str(document_ids[0])}
        assert request_id == "operator-req-14"

    def test_promote_unknown_document_404(self, harness: Harness) -> None:
        response = harness.post(f"/internal/editorial/research/{uuid.uuid4()}/promote")
        assert response.status_code == 404
        assert harness.dispatcher.calls == []

    def test_queue_failure_is_503_without_transport_detail(self) -> None:
        harness = Harness(dispatcher=FailingEditorialDispatcher())
        with harness.session() as session:
            document_ids = seed_documents(session)
        response = harness.post(f"/internal/editorial/research/{document_ids[0]}/promote")
        assert response.status_code == 503
        envelope = response.json()["error"]
        assert "redis" not in envelope["message"].lower()
        assert "queued" not in envelope["message"].lower()

    def test_evaluate_queues_exact_task(self, harness: Harness) -> None:
        with harness.session() as session:
            context = Context()
            seed_scored(session, context)
        response = harness.post(
            f"/internal/editorial/opportunities/{context.opportunity_id}/evaluate"
        )
        assert response.status_code == 200
        [(task, payload, _)] = harness.dispatcher.calls
        assert task == "evaluate_opportunity"
        assert payload == {"opportunity_id": str(context.opportunity_id)}

    def test_generate_ideas_bounds_and_queue(self, harness: Harness) -> None:
        with harness.session() as session:
            context = Context()
            seed_commissioned(session, context)
        rejected = harness.post(
            f"/internal/editorial/opportunities/{context.opportunity_id}/generate-ideas",
            {"candidate_count": 99},
        )
        assert rejected.status_code == 422
        assert harness.dispatcher.calls == []
        response = harness.post(
            f"/internal/editorial/opportunities/{context.opportunity_id}/generate-ideas",
            {"candidate_count": 4, "retry_number": 1},
        )
        assert response.status_code == 200
        [(task, payload, _)] = harness.dispatcher.calls
        assert task == "generate_idea_candidates"
        assert payload == {
            "opportunity_id": str(context.opportunity_id),
            "candidate_count": 4,
            "retry_number": 1,
        }

    def test_build_pack_exact_json_safe_command(self, harness: Harness) -> None:
        with harness.session() as session:
            context = Context()
            seed_selected_idea(session, context)
        selections = [
            {
                "research_evidence_id": str(context.evidence_ids[0]),
                "role": "key_fact",
                "claim_cluster": "detaylar",
                "display_note": None,
            },
            {
                "research_evidence_id": str(context.evidence_ids[2]),
                "role": "supporting",
                "claim_cluster": "butce",
                "display_note": "kaynak bütçe aralığı",
            },
        ]
        response = harness.post(
            f"/internal/editorial/opportunities/{context.opportunity_id}/evidence-packs/build",
            {"idea_id": str(context.selected_idea_id), "selections": selections},
        )
        assert response.status_code == 200
        assert response.json()["task"] == "build_evidence_pack"
        [(task, payload, _)] = harness.dispatcher.calls
        assert task == "build_evidence_pack"
        assert payload == {
            "opportunity_id": str(context.opportunity_id),
            "idea_id": str(context.selected_idea_id),
            "selections": selections,
            "contradictions": None,
        }
        # No pack row was inserted by the API itself.
        with harness.session() as session:
            packs = session.scalar(select(func.count()).select_from(EvidencePack))
            assert packs == 0

    def test_build_pack_malformed_command_422_no_publish(self, harness: Harness) -> None:
        with harness.session() as session:
            context = Context()
            seed_selected_idea(session, context)
        response = harness.post(
            f"/internal/editorial/opportunities/{context.opportunity_id}/evidence-packs/build",
            {
                "idea_id": str(context.selected_idea_id),
                "selections": [{"research_evidence_id": "not-a-uuid", "role": "wizardry"}],
            },
        )
        assert response.status_code == 422
        assert harness.dispatcher.calls == []

    def test_analyze_intent_requires_seo_research_and_pins(self, harness: Harness) -> None:
        with harness.session() as session:
            context = Context()
            seed_selected_idea(session, context)  # still EVIDENCE_BUILDING
        early = harness.post(
            f"/internal/editorial/opportunities/{context.opportunity_id}/analyze-search-intent",
            {"idea_id": str(context.selected_idea_id), "evidence_pack_id": str(uuid.uuid4())},
        )
        assert early.status_code == 409
        assert harness.dispatcher.calls == []

        with harness.session() as session:
            ready = Context()
            seed_ready_pack(session, ready)
        signal_id = str(uuid.uuid4())
        response = harness.post(
            f"/internal/editorial/opportunities/{ready.opportunity_id}/analyze-search-intent",
            {
                "idea_id": str(ready.selected_idea_id),
                "evidence_pack_id": str(ready.pack_id),
                "search_signal_ids": [signal_id],
                "retry_number": 0,
            },
        )
        assert response.status_code == 200
        task, payload, request_id = harness.dispatcher.calls[-1]
        assert task == "analyze_search_intent"
        assert payload == {
            "opportunity_id": str(ready.opportunity_id),
            "idea_id": str(ready.selected_idea_id),
            "evidence_pack_id": str(ready.pack_id),
            "signal_ids": [signal_id],
            "retry_number": 0,
        }
        # The middleware's server-side correlation id always propagates.
        assert isinstance(request_id, str) and request_id

    def test_compose_brief_queues_and_never_transitions(self, harness: Harness) -> None:
        with harness.session() as session:
            context = Context()
            seed_briefing(session, context)
        response = harness.post(
            f"/internal/editorial/work-items/{context.work_item_id}/compose-brief",
            {
                "idea_id": str(context.selected_idea_id),
                "evidence_pack_id": str(context.pack_id),
                "search_intent_analysis_id": str(context.analysis_id),
                "retry_number": 0,
            },
        )
        assert response.status_code == 200
        [(task, payload, _)] = harness.dispatcher.calls
        assert task == "compose_content_brief"
        assert payload == {
            "work_item_id": str(context.work_item_id),
            "idea_id": str(context.selected_idea_id),
            "evidence_pack_id": str(context.pack_id),
            "search_intent_analysis_id": str(context.analysis_id),
            "retry_number": 0,
            "supersede_reason": None,
        }
        # Queuing composed nothing and moved nothing.
        assert work_item_state(harness, context.work_item_id) is WorkflowState.BRIEFING
        with harness.session() as session:
            assert session.scalar(select(func.count()).select_from(ContentBrief)) == 0


class TestIdeaCommands:
    def test_select_then_deselect(self, harness: Harness) -> None:
        with harness.session() as session:
            context = Context()
            seed_selected_idea(session, context)
        other_idea = context.idea_ids[1]
        events_before = workflow_event_count(harness, context.work_item_id)
        response = harness.post(
            f"/internal/editorial/ideas/{other_idea}/select",
            {"reason": "daha net açı"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "selected"
        assert response.json()["idea_id"] == str(other_idea)

        deselect = harness.post(
            f"/internal/editorial/ideas/{other_idea}/deselect",
            {"reason": "yeniden değerlendirme"},
        )
        assert deselect.status_code == 200
        assert deselect.json()["status"] == "deselected"
        with harness.session() as session:
            latest = session.execute(
                select(IdeaSelectionEvent).order_by(IdeaSelectionEvent.id.desc()).limit(1)
            ).scalar_one()
            assert latest.action.value == "deselected"
        # Selection commands never mutate workflow state.
        assert workflow_event_count(harness, context.work_item_id) == events_before

    def test_deselect_non_effective_conflict(self, harness: Harness) -> None:
        with harness.session() as session:
            context = Context()
            seed_selected_idea(session, context)
        response = harness.post(
            f"/internal/editorial/ideas/{context.idea_ids[1]}/deselect",
            {"reason": "bu seçili değil"},
        )
        assert response.status_code == 409


class TestContradictionAndReassembly:
    def test_resolution_keeps_old_pack_sufficiency(self, harness: Harness) -> None:
        with harness.session() as session:
            context = Context()
            seed_ready_pack(session, context)
            sufficiency_before = session.get(EvidencePack, context.pack_id).sufficiency
        response = harness.post(
            f"/internal/editorial/contradictions/{context.contradiction_id}/resolve",
            {
                "resolution_status": "resolved_cautious_wording",
                "reason": "iki süre tahmini de aralık olarak verilecek",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["resolution_status"] == "resolved_cautious_wording"
        assert "unchanged" in body["note"]
        with harness.session() as session:
            contradiction = session.get(EvidenceContradiction, context.contradiction_id)
            assert contradiction is not None
            assert (
                contradiction.resolution_status
                is ContradictionResolutionStatus.RESOLVED_CAUTIOUS_WORDING
            )
            assert contradiction.resolved_by is not None
            assert contradiction.resolved_at is not None
            assert contradiction.resolution_reason
            pack = session.get(EvidencePack, context.pack_id)
            assert pack is not None
            assert pack.sufficiency is sufficiency_before  # NEVER retroactive

    def test_unresolved_is_not_an_accepted_status(self, harness: Harness) -> None:
        with harness.session() as session:
            context = Context()
            seed_ready_pack(session, context)
        response = harness.post(
            f"/internal/editorial/contradictions/{context.contradiction_id}/resolve",
            {"resolution_status": "unresolved", "reason": "çözemedim"},
        )
        assert response.status_code == 422

    def test_reassemble_creates_new_version_old_untouched(self, harness: Harness) -> None:
        with harness.session() as session:
            context = Context()
            seed_ready_pack(session, context)
        resolve = harness.post(
            f"/internal/editorial/contradictions/{context.contradiction_id}/resolve",
            {
                "resolution_status": "resolved_editorial_judgment",
                "reason": "kaynaklardan biri açıkça güncel",
            },
        )
        assert resolve.status_code == 200
        response = harness.post(f"/internal/editorial/evidence-packs/{context.pack_id}/reassemble")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "reassembled"
        assert body["evidence_pack_id"] != str(context.pack_id)
        assert body["version"] == 2
        assert body["sufficiency"] == "ready"
        assert "does not advance" in body["note"]
        with harness.session() as session:
            old_pack = session.get(EvidencePack, context.pack_id)
            assert old_pack is not None
            assert old_pack.sufficiency is EvidencePackSufficiency.READY
            assert old_pack.version == 1
        # Reassembly never advances workflow by itself.
        assert work_item_state(harness, context.work_item_id) is WorkflowState.SEO_RESEARCH


class TestBlockResolution:
    def blocked_context(self, harness: Harness) -> Context:
        with harness.session() as session:
            context = Context()
            seed_selected_idea(session, context)
            WorkflowService(session).transition(
                context.work_item_id,
                WorkflowState.BLOCKED,
                actor_origin=WorkflowActorOrigin.SYSTEM,
                reason="kanıt paketi yetersiz: eksikler var",
            )
            session.commit()
        return context

    def test_resolve_block_derives_target_from_history(self, harness: Harness) -> None:
        context = self.blocked_context(harness)
        response = harness.post(
            f"/internal/editorial/work-items/{context.work_item_id}/resolve-block",
            {"reason": "eksik kanıt tamamlandı"},
        )
        assert response.status_code == 200
        assert response.json()["current_state"] == "evidence_building"

    def test_resolve_block_rejects_caller_target(self, harness: Harness) -> None:
        context = self.blocked_context(harness)
        response = harness.post(
            f"/internal/editorial/work-items/{context.work_item_id}/resolve-block",
            {"reason": "hedefi ben seçeyim", "target_state": "briefing"},
        )
        assert response.status_code == 422  # extra=forbid: no caller target exists

    def test_resolve_block_requires_blocked(self, harness: Harness) -> None:
        with harness.session() as session:
            context = Context()
            seed_selected_idea(session, context)
        response = harness.post(
            f"/internal/editorial/work-items/{context.work_item_id}/resolve-block",
            {"reason": "blok yok"},
        )
        assert response.status_code == 409

    def test_reject_blocked(self, harness: Harness) -> None:
        context = self.blocked_context(harness)
        response = harness.post(
            f"/internal/editorial/work-items/{context.work_item_id}/reject-blocked",
            {"reason": "kanıt bulunamıyor, vazgeçildi"},
        )
        assert response.status_code == 200
        assert response.json()["current_state"] == "rejected"


class TestBriefAcceptance:
    def test_accept_for_drafting(self, harness: Harness) -> None:
        with harness.session() as session:
            context = Context()
            seed_draft_brief(session, context)
        events_before = workflow_event_count(harness, context.work_item_id)
        response = harness.post(
            f"/internal/editorial/briefs/{context.brief_id}/accept",
            {"reason": "kapsam ve kanıt haritası eksiksiz"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "accepted"
        assert body["brief_status"] == "accepted_for_drafting"
        assert body["work_item_state"] == "drafting"
        with harness.session() as session:
            brief = session.get(ContentBrief, context.brief_id)
            assert brief is not None
            assert brief.status is BriefStatus.ACCEPTED_FOR_DRAFTING
            status_events = session.scalar(select(func.count()).select_from(BriefStatusEvent))
            assert status_events == 1
        assert workflow_event_count(harness, context.work_item_id) == events_before + 1

        repeat = harness.post(
            f"/internal/editorial/briefs/{context.brief_id}/accept",
            {"reason": "tekrar"},
        )
        assert repeat.status_code == 200
        assert repeat.json()["status"] == "already_accepted"

    def test_acceptance_gate_conflict(self, harness: Harness) -> None:
        with harness.session() as session:
            context = Context()
            seed_draft_brief(session, context)
            # Selection moved on: the pinned idea is no longer effective.
            from contentos.ideas.service import IdeaService

            IdeaService(session).select_idea(context.idea_ids[1], reason="yeni tercih")
            session.commit()
        response = harness.post(
            f"/internal/editorial/briefs/{context.brief_id}/accept",
            {"reason": "yine de kabul"},
        )
        assert response.status_code == 409


class TestDuplicateReopen:
    def seed_duplicate_root(self, harness: Harness) -> uuid.UUID:
        with harness.session() as session:
            document_ids = seed_documents(session)
            # SQLite-only knob: a newer DUPLICATE decision on the support doc.
            session.add(
                DuplicateDecision(
                    normalized_document_id=document_ids[1],
                    engine_name="duplicate-engine",
                    engine_version="2",
                    decision=DuplicateDecisionOutcome.DUPLICATE,
                    signals={},
                    thresholds={},
                    matches=[{"normalized_document_id": str(document_ids[0])}],
                    rationale_codes=["near_exact"],
                    evaluated_at=NOW.replace(hour=13),
                )
            )
            session.commit()
        return document_ids[1]

    def test_reopen_duplicate(self, harness: Harness) -> None:
        document_id = self.seed_duplicate_root(harness)
        response = harness.post(
            f"/internal/editorial/research/{document_id}/reopen-duplicate",
            {
                "reason": "kaynak aynı ama bizim açımız farklı",
                "distinct_angle": "Bütçe odaklı, tamamen pratik bir kontrol listesi açısı.",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "created"
        assert body["duplicate_outcome"] == "duplicate"
        with harness.session() as session:
            # The DUPLICATE decision itself is untouched.
            decision = session.execute(
                select(DuplicateDecision).where(
                    DuplicateDecision.normalized_document_id == document_id,
                    DuplicateDecision.decision == DuplicateDecisionOutcome.DUPLICATE,
                )
            ).scalar_one()
            assert decision.decision is DuplicateDecisionOutcome.DUPLICATE
            item = session.get(EditorialWorkItem, uuid.UUID(body["work_item_id"]))
            assert item is not None
            assert item.origin.value == "operator"
            assert item.current_state is WorkflowState.IDEA_SCORING
        # Reopen never auto-evaluates: no scoring task was queued.
        assert harness.dispatcher.calls == []

    def test_missing_body_fields_422(self, harness: Harness) -> None:
        document_id = self.seed_duplicate_root(harness)
        response = harness.post(
            f"/internal/editorial/research/{document_id}/reopen-duplicate",
            {"reason": "gerekçe var ama açı yok"},
        )
        assert response.status_code == 422


class TestNoGenericEndpoints:
    def test_no_generic_action_routes(self, harness: Harness) -> None:
        paths = set(harness.app.openapi()["paths"])
        assert paths
        for path in paths:
            for banned in ("/action", "/execute", "/state", "/transition", "/command"):
                assert banned not in path, path

    def test_no_publication_command(self, harness: Harness) -> None:
        paths = set(harness.app.openapi()["paths"])
        assert paths
        for path in paths:
            for banned in ("publish", "schedule", "pinterest", "release", "approve"):
                assert banned not in path.lower(), path
