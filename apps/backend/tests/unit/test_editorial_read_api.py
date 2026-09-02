"""Editorial read API tests (SQLite, real services, real FastAPI app)."""

import json
import uuid

import pytest
from editorial_harness import Context, Harness, seed_full, seed_scored
from sqlalchemy import func, select

from contentos.workflow.models import EditorialWorkflowEvent

FORBIDDEN_STRINGS = (
    "raw_payload_ref",
    "clean_text",
    "input_projection",
    "instructions",
    "database_url",
    "api_key",
    "api-secret",
    "authorization",
    "redis://",
    "postgresql+psycopg://",
    "govdesi",  # seeded raw HTML body marker: must never surface
)


@pytest.fixture()
def harness() -> Harness:
    return Harness()


def assert_no_leak(payload: object) -> None:
    serialized = json.dumps(payload, ensure_ascii=False).lower()
    for marker in FORBIDDEN_STRINGS:
        assert marker not in serialized, f"leaked marker: {marker}"


class TestWorkQueue:
    def test_list_row_projection(self, harness: Harness) -> None:
        with harness.session() as session:
            context = seed_full(session)
        response = harness.get("/internal/editorial/work-items")
        assert response.status_code == 200
        page = response.json()
        assert page["total"] == 1
        [row] = page["items"]
        assert row["work_item_id"] == str(context.work_item_id)
        assert row["current_state"] == "briefing"
        assert row["opportunity_id"] == str(context.opportunity_id)
        assert row["disposition"] == "commissioned"
        assert row["score_id"] == str(context.score_id)
        assert row["score_eligibility"] == "commissionable"
        assert row["score_engine_name"]
        assert isinstance(row["score_missing_signals"], list)
        assert row["selected_idea_id"] == str(context.selected_idea_id)
        assert row["selected_idea_title"]
        assert row["selected_idea_originality"] == "passed"
        assert row["latest_pack_id"] == str(context.pack_id)
        assert row["latest_pack_sufficiency"] == "ready"
        assert row["latest_analysis_id"] == str(context.analysis_id)
        assert row["latest_brief_id"] == str(context.brief_id)
        assert row["latest_brief_status"] == "draft"
        assert_no_leak(page)

    def test_absent_artifacts_are_absent(self, harness: Harness) -> None:
        with harness.session() as session:
            context = Context()
            seed_scored(session, context)
        [row] = harness.get("/internal/editorial/work-items").json()["items"]
        assert row["selected_idea_id"] is None
        assert row["latest_pack_id"] is None
        assert row["latest_analysis_id"] is None
        assert row["latest_brief_id"] is None
        assert row["disposition"] == "open"

    def test_state_filter_and_pagination(self, harness: Harness) -> None:
        with harness.session() as session:
            seed_full(session)
            context = Context()
            seed_scored(session, context)
        briefing = harness.get("/internal/editorial/work-items?workflow_state=briefing").json()
        assert briefing["total"] == 1
        assert briefing["items"][0]["current_state"] == "briefing"
        scoring = harness.get("/internal/editorial/work-items?workflow_state=idea_scoring").json()
        assert scoring["total"] == 1
        first_page = harness.get("/internal/editorial/work-items?limit=1&offset=0").json()
        second_page = harness.get("/internal/editorial/work-items?limit=1&offset=1").json()
        assert first_page["total"] == 2 and second_page["total"] == 2
        assert len(first_page["items"]) == 1 and len(second_page["items"]) == 1
        assert first_page["items"][0]["work_item_id"] != second_page["items"][0]["work_item_id"]

    def test_disposition_filter(self, harness: Harness) -> None:
        with harness.session() as session:
            seed_full(session)
            context = Context()
            seed_scored(session, context)
        page = harness.get(
            "/internal/editorial/work-items?opportunity_disposition=commissioned"
        ).json()
        assert page["total"] == 1
        assert page["items"][0]["disposition"] == "commissioned"

    def test_reads_have_no_side_effects(self, harness: Harness) -> None:
        with harness.session() as session:
            context = seed_full(session)
            events_before = session.scalar(select(func.count()).select_from(EditorialWorkflowEvent))
        harness.get("/internal/editorial/work-items")
        harness.get(f"/internal/editorial/work-items/{context.work_item_id}")
        harness.get(f"/internal/editorial/opportunities/{context.opportunity_id}/eligible-evidence")
        with harness.session() as session:
            events_after = session.scalar(select(func.count()).select_from(EditorialWorkflowEvent))
        assert events_after == events_before


class TestWorkItemDetail:
    def test_not_found(self, harness: Harness) -> None:
        response = harness.get(f"/internal/editorial/work-items/{uuid.uuid4()}")
        assert response.status_code == 404

    def test_full_detail_projection(self, harness: Harness) -> None:
        with harness.session() as session:
            context = seed_full(session)
        response = harness.get(f"/internal/editorial/work-items/{context.work_item_id}")
        assert response.status_code == 200
        detail = response.json()
        assert_no_leak(detail)

        # Workflow: current projection + monotonic history.
        assert detail["work_item"]["current_state"] == "briefing"
        events = detail["workflow_events"]
        assert detail["total_workflow_events"] == len(events) == 4
        assert detail["workflow_events_truncated"] is False
        event_ids = [event["id"] for event in events]
        assert event_ids == sorted(event_ids, reverse=True)
        to_states = [event["to_state"] for event in reversed(events)]
        assert to_states == ["idea_scoring", "evidence_building", "seo_research", "briefing"]
        commissioning = next(e for e in events if e["to_state"] == "evidence_building")
        assert commissioning["actor_origin"] == "operator"
        assert commissioning["artifact_refs"]["opportunity_score_id"] == str(context.score_id)

        # Opportunity + research inputs with provenance.
        assert detail["opportunity"]["disposition"] == "commissioned"
        assert detail["opportunity"]["promotion_root_document_id"] == str(context.document_ids[0])
        inputs = detail["research_inputs"]
        assert len(inputs) == 2
        assert {entry["duplicate_outcome"] for entry in inputs} == {"unique"}
        assert all(entry["source_slug"] for entry in inputs)
        assert all(entry["trust_tier"] == "general" for entry in inputs)
        assert inputs[0]["document_title"]

        # Scores: effective marked, components explain, UNKNOWN stays UNKNOWN.
        assert detail["total_scores"] == 1
        [score] = detail["scores"]
        assert score["id"] == str(context.score_id)
        assert score["effective"] is True
        assert score["engine_name"] and score["engine_version"]
        assert score["weights_snapshot"] and score["threshold_snapshot"]
        assert score["input_snapshot"]
        components = {entry["component"]: entry for entry in score["components"]}
        assert len(components) == 12  # every component is reported
        unknown = [entry for entry in components.values() if entry["availability"] == "unknown"]
        assert unknown, "v1 always has UNKNOWN components"
        assert all(entry["value"] is None for entry in unknown)  # never rendered as 0

        # Ideas + selection.
        assert detail["total_ideas"] == 3
        assert detail["effective_selected_idea_id"] == str(context.selected_idea_id)
        selected = next(i for i in detail["ideas"] if i["id"] == str(context.selected_idea_id))
        assert selected["effective_selected"] is True
        assert selected["origin"] == "model_assisted"
        assert selected["generation_attempt_id"] is not None
        assert selected["originality_status"] == "passed"
        assert selected["planning_dimensions"]["dimensions"]["theme"] == "balon teması"
        [selection_event] = detail["selection_events"]
        assert selection_event["idea_id"] == str(context.selected_idea_id)
        assert selection_event["action"] == "selected"

        # Packs: members, roles, contradictions, sufficiency detail.
        assert detail["total_evidence_packs"] == 1
        [pack] = detail["evidence_packs"]
        assert pack["id"] == str(context.pack_id)
        assert pack["sufficiency"] == "ready"
        assert pack["idea_id"] == str(context.selected_idea_id)
        assert pack["assembler_name"] and pack["policy_snapshot"]
        assert len(pack["items"]) == 3
        roles = {item["role"] for item in pack["items"]}
        assert roles == {"key_fact", "supporting"}
        assert all(item["statement"] for item in pack["items"])
        [contradiction] = pack["contradictions"]
        assert contradiction["id"] == str(context.contradiction_id)
        assert contradiction["resolution_status"] == "unresolved"
        assert contradiction["severity"] == "material"

        # Intent: exact signals + honest missing signals + cannibalization.
        assert detail["total_intent_analyses"] == 1
        [analysis] = detail["intent_analyses"]
        assert analysis["id"] == str(context.analysis_id)
        assert analysis["engine_name"] and analysis["synthesis_attempt_id"]
        [known] = analysis["known_signals"]
        assert known["id"] == str(context.signal_id)
        assert known["signal_type"] == "manual_intent_note"
        assert known["observed_at"] and known["recorded_at"]
        assert analysis["missing_signals"]  # UNKNOWN != ZERO
        assert analysis["cannibalization_status"] == "not_checked"

        # Briefs: contract + claim map with exact evidence links.
        assert detail["total_briefs"] == 1
        [brief] = detail["briefs"]
        assert brief["id"] == str(context.brief_id)
        assert brief["status"] == "draft"
        assert brief["engine_name"] == "brief-composer"
        assert brief["composition_attempt_id"] is not None
        assert brief["structure_guard_result"]
        assert brief["uncertainty_notes"]
        claims = {claim["claim_key"]: claim for claim in brief["claims"]}
        assert claims["konsept-detaylari"]["evidence_ids"] == [str(context.evidence_ids[0])]
        assert claims["butce-araligi"]["evidence_ids"] == [str(context.evidence_ids[2])]
        assert brief["status_events"] == []

        # AI attempts: safe metadata for all three linked attempts.
        purposes = {attempt["purpose"] for attempt in detail["ai_attempts"]}
        assert purposes == {"idea_candidates", "intent_synthesis", "brief_composition"}
        for attempt in detail["ai_attempts"]:
            assert attempt["provider"] == "fake"
            assert attempt["status"] == "succeeded"
            assert attempt["input_hash"]
            assert set(attempt.keys()) == {
                "id",
                "purpose",
                "provider",
                "model_name",
                "model_version",
                "schema_name",
                "schema_version",
                "template_name",
                "template_version",
                "input_hash",
                "input_refs",
                "status",
                "error_class",
                "retry_number",
                "usage",
                "created_at",
            }

    def test_blocked_detail_shows_reason_and_resume_target(self, harness: Harness) -> None:
        from contentos.workflow.enums import WorkflowActorOrigin, WorkflowState
        from contentos.workflow.service import WorkflowService

        with harness.session() as session:
            context = Context()
            seed_scored(session, context)
            WorkflowService(session).transition(
                context.work_item_id,
                WorkflowState.BLOCKED,
                actor_origin=WorkflowActorOrigin.SYSTEM,
                reason="skor girdileri eksik: sinyal envanteri yok",
            )
            session.commit()
        detail = harness.get(f"/internal/editorial/work-items/{context.work_item_id}").json()
        assert detail["work_item"]["current_state"] == "blocked"
        assert "sinyal envanteri" in detail["work_item"]["blocked_reason"]
        assert detail["work_item"]["blocked_resume_state"] == "idea_scoring"


class TestEligibleEvidence:
    def test_page_and_bounds(self, harness: Harness) -> None:
        with harness.session() as session:
            context = seed_full(session)
        response = harness.get(
            f"/internal/editorial/opportunities/{context.opportunity_id}/eligible-evidence"
        )
        assert response.status_code == 200
        page = response.json()
        assert page["total"] == 3
        assert {entry["id"] for entry in page["items"]} == {
            str(evidence_id) for evidence_id in context.evidence_ids
        }
        for entry in page["items"]:
            assert entry["statement"]
            assert entry["source_slug"]
            assert entry["trust_tier"] == "general"
            assert "excerpt" not in entry
        assert_no_leak(page)
        second = harness.get(
            f"/internal/editorial/opportunities/{context.opportunity_id}"
            "/eligible-evidence?limit=2&offset=2"
        ).json()
        assert second["total"] == 3
        assert len(second["items"]) == 1

    def test_unknown_opportunity_404(self, harness: Harness) -> None:
        response = harness.get(
            f"/internal/editorial/opportunities/{uuid.uuid4()}/eligible-evidence"
        )
        assert response.status_code == 404


class TestDraftReads:
    """Phase 4 Task 7: draft versions, body, provenance chain, attempts."""

    def test_generated_draft_list_and_detail(self, harness: Harness) -> None:
        from test_drafts import accepted_context
        from test_writer_generation import writer_payload

        from contentos.ai.fake import FakeStructuredProvider
        from contentos.drafts.generation import WriterEngine

        accepted = accepted_context(harness)
        with harness.session() as session:
            result = WriterEngine(session).generate_draft(
                accepted.context.brief_id,
                provider=FakeStructuredProvider(payload=writer_payload(accepted)),
            )
            session.commit()
            assert result.draft is not None
            draft_id = result.draft.id

        listing = harness.get(
            f"/internal/editorial/work-items/{accepted.context.work_item_id}/drafts"
        )
        assert listing.status_code == 200
        page = listing.json()
        assert page["total"] == 1
        [row] = page["drafts"]
        assert row["id"] == str(draft_id)
        assert row["origin"] == "writer_engine"
        assert row["status"] == "active"
        assert row["uncertainty_coverage_status"] == "evaluated"
        assert row["originality_outcome"] == "passed"
        assert_no_leak(page)

        detail_response = harness.get(f"/internal/editorial/drafts/{draft_id}")
        assert detail_response.status_code == 200
        detail = detail_response.json()
        assert detail["draft"]["id"] == str(draft_id)
        assert detail["body"]["sections"]
        section_keys = {section["key"] for section in detail["body"]["sections"]}
        assert {"giris", "plan", "butce"} <= section_keys

        # The claim -> evidence provenance chain resolves with identities.
        usages = detail["claim_usages"]
        assert usages
        for usage in usages:
            assert usage["claim_key"]
            assert usage["claim_kind"]
            assert usage["block_id"]
        assert any(usage["research_evidence_ids"] for usage in usages)

        # Writer attempt metadata is present, without projections/prompts.
        attempts = detail["generation_attempts"]
        assert len(attempts) == 1
        assert attempts[0]["purpose"] == "writer_draft"
        assert attempts[0]["status"] == "succeeded"
        assert_no_leak(detail)

    def test_failed_attempt_visible_without_draft_rows(self, harness: Harness) -> None:
        from test_drafts import accepted_context
        from test_writer_generation import writer_payload

        from contentos.ai.fake import FakeStructuredProvider
        from contentos.drafts.generation import WriterEngine

        accepted = accepted_context(harness)
        bad = writer_payload(accepted)
        bad["sections"][0]["blocks"][1]["claim_refs"] = [str(uuid.uuid4())]
        with harness.session() as session:
            failed = WriterEngine(session).generate_draft(
                accepted.context.brief_id, provider=FakeStructuredProvider(payload=bad)
            )
            session.commit()
            assert failed.draft is None
            second = WriterEngine(session).generate_draft(
                accepted.context.brief_id,
                provider=FakeStructuredProvider(payload=writer_payload(accepted)),
                retry_number=1,
            )
            session.commit()
            assert second.draft is not None
            draft_id = second.draft.id

        detail = harness.get(f"/internal/editorial/drafts/{draft_id}").json()
        # BOTH attempts surface truthfully: the failure is never hidden.
        statuses = {entry["status"] for entry in detail["generation_attempts"]}
        assert statuses == {"validation_failed", "succeeded"}
        failed_entry = next(
            entry
            for entry in detail["generation_attempts"]
            if entry["status"] == "validation_failed"
        )
        assert failed_entry["error_class"] == "domain_validation"
        assert_no_leak(detail)

    def test_superseded_versions_stay_visible(self, harness: Harness) -> None:
        from test_drafts import accepted_context
        from test_writer_generation import writer_payload

        from contentos.ai.fake import FakeStructuredProvider
        from contentos.drafts.generation import WriterEngine

        accepted = accepted_context(harness)
        with harness.session() as session:
            engine = WriterEngine(session)
            first = engine.generate_draft(
                accepted.context.brief_id,
                provider=FakeStructuredProvider(payload=writer_payload(accepted)),
            )
            session.commit()
            second = engine.generate_draft(
                accepted.context.brief_id,
                provider=FakeStructuredProvider(
                    payload=writer_payload(accepted, title_proposal="Yenilenmiş balon teması planı")
                ),
                retry_number=1,
                supersede_reason="operatör yeniden üretim istedi",
            )
            session.commit()
            assert first.draft is not None and second.draft is not None
            first_id, second_id = first.draft.id, second.draft.id

        page = harness.get(
            f"/internal/editorial/work-items/{accepted.context.work_item_id}/drafts"
        ).json()
        assert page["total"] == 2
        assert [row["version"] for row in page["drafts"]] == [2, 1]
        by_id = {row["id"]: row for row in page["drafts"]}
        assert by_id[str(first_id)]["status"] == "superseded"
        assert by_id[str(first_id)]["superseded_by_draft_id"] == str(second_id)
        assert by_id[str(second_id)]["status"] == "active"

        detail = harness.get(f"/internal/editorial/drafts/{first_id}").json()
        events = detail["status_events"]
        assert len(events) == 1
        assert events[0]["from_status"] == "active"
        assert events[0]["to_status"] == "superseded"
        assert events[0]["reason"] == "operatör yeniden üretim istedi"
        assert events[0]["replacement_draft_id"] == str(second_id)

    def test_unknown_ids_404(self, harness: Harness) -> None:
        assert (
            harness.get(f"/internal/editorial/work-items/{uuid.uuid4()}/drafts").status_code == 404
        )
        assert harness.get(f"/internal/editorial/drafts/{uuid.uuid4()}").status_code == 404


class TestReviewReads:
    """Phase 4 Task 14: review versions, findings, integrity, attempts."""

    def reviewed(self, harness: Harness) -> tuple[object, str, str]:
        """EDITING work item with one engine-generated review (one finding)."""
        from test_reviews import editing_context

        from contentos.ai.fake import FakeStructuredProvider
        from contentos.reviews.generation import EditorEngine

        accepted, draft_id, claim_id = editing_context(harness)
        with harness.session() as session:
            result = EditorEngine(session).generate_review(
                accepted.context.work_item_id,
                provider=FakeStructuredProvider(
                    payload={
                        "findings": [
                            {
                                "finding_key": "iddia-cercevesi",
                                "dimension": "claim_faithfulness",
                                "severity": "major",
                                "description": "Metin iddiadan daha kesin konuşuyor.",
                                "recommendation": "Kaynak çerçevesine dön.",
                                "block_id": "giris-2",
                                "claim_ref": str(claim_id),
                            }
                        ]
                    }
                ),
            )
            session.commit()
            assert result.review is not None
            return accepted, str(result.review.id), str(draft_id)

    def test_review_list_and_detail(self, harness: Harness) -> None:
        accepted, review_id, draft_id = self.reviewed(harness)

        listing = harness.get(
            f"/internal/editorial/work-items/{accepted.context.work_item_id}/reviews"  # type: ignore[attr-defined]
        )
        assert listing.status_code == 200
        page = listing.json()
        assert page["total"] == 1
        [row] = page["reviews"]
        assert row["id"] == review_id
        assert row["verdict"] == "revise"  # a major finding computes revise
        assert row["status"] == "active"
        assert row["content_draft_id"] == draft_id
        assert row["finding_counts"] == {"blocking": 0, "major": 1, "minor": 0}
        assert row["writer_envelope_recomputed"] is True
        assert_no_leak(page)

        detail_response = harness.get(f"/internal/editorial/reviews/{review_id}")
        assert detail_response.status_code == 200
        detail = detail_response.json()
        assert detail["review"]["id"] == review_id
        envelope = detail["integrity_gate_result"]["writer_envelope"]
        assert envelope == {
            "structure_contract": "ok",
            "claim_ref_integrity": "ok",
            "handling_coverage": "ok",
        }
        assert detail["verdict_policy_snapshot"]["version"] == "editor-verdict/1"
        assert detail["review_scope"]["content_draft_id"] == draft_id

        [finding] = detail["findings"]
        assert finding["finding_key"] == "iddia-cercevesi"
        assert finding["origin"] == "model_signal"
        assert finding["block_id"] == "giris-2"
        # The claim anchor resolves to its brief claim identity.
        assert finding["claim_key"] == "konsept-detaylari"
        assert finding["claim_kind"] == "factual"

        attempts = detail["generation_attempts"]
        assert len(attempts) == 1
        assert attempts[0]["purpose"] == "editor_review"
        assert attempts[0]["status"] == "succeeded"
        assert_no_leak(detail)

    def test_superseded_reviews_stay_visible_with_audit(self, harness: Harness) -> None:
        from contentos.reviews.service import ReviewService

        accepted, review_id, _ = self.reviewed(harness)
        with harness.session() as session:
            second = ReviewService(session).create_review(
                accepted.context.work_item_id,  # type: ignore[attr-defined]
                [],
                supersede_reason="bulgular giderildi sayıldı (test)",
            )
            session.commit()
            second_id = str(second.review.id)

        page = harness.get(
            f"/internal/editorial/work-items/{accepted.context.work_item_id}/reviews"  # type: ignore[attr-defined]
        ).json()
        assert page["total"] == 2
        assert [row["version"] for row in page["reviews"]] == [2, 1]
        by_id = {row["id"]: row for row in page["reviews"]}
        assert by_id[review_id]["status"] == "superseded"
        assert by_id[review_id]["superseded_by_review_id"] == second_id
        assert by_id[second_id]["verdict"] == "pass"

        detail = harness.get(f"/internal/editorial/reviews/{review_id}").json()
        [event] = detail["status_events"]
        assert event["from_status"] == "active"
        assert event["to_status"] == "superseded"
        assert event["replacement_review_id"] == second_id
        assert event["reason"] == "bulgular giderildi sayıldı (test)"

    def test_unknown_review_ids_404(self, harness: Harness) -> None:
        assert (
            harness.get(f"/internal/editorial/work-items/{uuid.uuid4()}/reviews").status_code == 404
        )
        assert harness.get(f"/internal/editorial/reviews/{uuid.uuid4()}").status_code == 404


class TestQaReportReads:
    """Phase 4 Task 19: QA report versions, gates, waivers, audit."""

    def with_report(self, harness: Harness) -> tuple[object, str]:
        from test_qa import qa_review_context

        from contentos.qa.gates import QaGateEngine

        accepted, _, _ = qa_review_context(harness)
        with harness.session() as session:
            result = QaGateEngine(session).run_gates(accepted.context.work_item_id)
            session.commit()
            return accepted, str(result.report.id)

    def test_report_list_and_detail_render_truthful_gates(self, harness: Harness) -> None:
        accepted, report_id = self.with_report(harness)
        listing = harness.get(
            f"/internal/editorial/work-items/{accepted.context.work_item_id}/qa-reports"
        )
        assert listing.status_code == 200
        page = listing.json()
        assert page["total"] == 1
        [row] = page["reports"]
        assert row["id"] == report_id
        assert row["outcome"] == "not_ready"
        assert row["status"] == "active"
        # The truthful media gate is never softened into a pass.
        assert row["gate_summary"]["media_needs"] == "unsatisfied"
        assert row["gate_summary"]["provenance_chain"] == "pass"
        assert row["gate_summary"]["internal_link_needs"] == "pending"
        assert page["waivers"] == []
        assert_no_leak(page)

        detail = harness.get(f"/internal/editorial/qa-reports/{report_id}").json()
        assert detail["report"]["id"] == report_id
        assert detail["gate_results"]["media_needs"]["needs"] >= 1
        assert detail["gate_policy_snapshot"]["version"] == "qa-gates/2"
        assert detail["gate_policy_snapshot"]["waivable_gates"] == ["media_needs"]
        assert detail["status_events"] == []
        assert_no_leak(detail)

    def test_waiver_and_supersession_stay_visible(self, harness: Harness) -> None:
        from contentos.qa.enums import WaivableGateKey
        from contentos.qa.gates import QaGateEngine
        from contentos.qa.service import QaService

        accepted, first_report_id = self.with_report(harness)
        with harness.session() as session:
            QaService(session).add_waiver(
                accepted.context.work_item_id,  # type: ignore[attr-defined]
                WaivableGateKey.MEDIA_NEEDS,
                reason="görsel gereksinimi bilinçli olarak ertelendi",
            )
            session.commit()
            second = QaGateEngine(session).run_gates(
                accepted.context.work_item_id  # type: ignore[attr-defined]
            )
            session.commit()
            second_id = str(second.report.id)

        page = harness.get(
            f"/internal/editorial/work-items/{accepted.context.work_item_id}/qa-reports"  # type: ignore[attr-defined]
        ).json()
        assert page["total"] == 2
        by_id = {row["id"]: row for row in page["reports"]}
        assert by_id[second_id]["outcome"] == "ready_for_human_review"
        assert by_id[second_id]["gate_summary"]["media_needs"] == "waived_by_human"
        assert by_id[first_report_id]["status"] == "superseded"
        [waiver] = page["waivers"]
        assert waiver["gate_key"] == "media_needs"
        assert waiver["reason"] == "görsel gereksinimi bilinçli olarak ertelendi"

        detail = harness.get(f"/internal/editorial/qa-reports/{first_report_id}").json()
        [event] = detail["status_events"]
        assert event["actor_origin"] == "system"
        assert event["replacement_report_id"] == second_id

    def test_unknown_ids_404(self, harness: Harness) -> None:
        assert (
            harness.get(f"/internal/editorial/work-items/{uuid.uuid4()}/qa-reports").status_code
            == 404
        )
        assert harness.get(f"/internal/editorial/qa-reports/{uuid.uuid4()}").status_code == 404
