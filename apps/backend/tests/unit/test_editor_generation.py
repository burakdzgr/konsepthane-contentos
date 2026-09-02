"""Editor engine tests (fake provider, no network, SQLite real services)."""

import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from editorial_harness import Harness
from sqlalchemy import func, select
from test_reviews import editing_context

import contentos.reviews.models  # noqa: F401
from contentos.ai.dto import GenerationRequest, ProviderOutputSchema, ProviderResult
from contentos.ai.enums import GenerationPurpose, GenerationStatus, ProviderFailureKind
from contentos.ai.fake import FakeStructuredProvider
from contentos.reviews.enums import (
    FindingDimension,
    FindingOrigin,
    FindingSeverity,
    ReviewVerdict,
)
from contentos.reviews.errors import (
    IncompleteReviewMaterializationError,
    ReviewPreconditionError,
)
from contentos.reviews.generation import EditorEngine
from contentos.reviews.models import EditorialReview
from contentos.reviews.repository import ReviewRepository


@pytest.fixture()
def harness() -> Harness:
    return Harness()


@dataclass
class CapturingFake(FakeStructuredProvider):
    """Fake provider that also captures the request it received."""

    last_request: GenerationRequest | None = None

    def generate(
        self, request: GenerationRequest, output_schema: ProviderOutputSchema
    ) -> ProviderResult:
        self.last_request = request
        return super().generate(request, output_schema)


def review_payload(claim_id: uuid.UUID | None = None, **overrides: Any) -> dict[str, Any]:
    findings: list[dict[str, Any]] = [
        {
            "finding_key": "ton-gevsek",
            "dimension": "clarity_style",
            "severity": "minor",
            "description": "Giriş bölümündeki ton hedef kitle için fazla gevşek.",
            "recommendation": "Cümleleri sadeleştir.",
            "block_id": "giris-1",
            "claim_ref": None,
        }
    ]
    if claim_id is not None:
        findings.append(
            {
                "finding_key": "iddia-cercevesi",
                "dimension": "claim_faithfulness",
                "severity": "major",
                "description": "Metin iddiadan daha kesin konuşuyor.",
                "recommendation": "Kaynak çerçevesine dön.",
                "block_id": "giris-2",
                "claim_ref": str(claim_id),
            }
        )
    payload: dict[str, Any] = {"findings": findings}
    payload.update(overrides)
    return payload


class TestEditorGeneration:
    def test_happy_path_findings_and_computed_verdict(self, harness: Harness) -> None:
        accepted, draft_id, claim_id = editing_context(harness)
        with harness.session() as session:
            provider = CapturingFake(payload=review_payload(claim_id))
            result = EditorEngine(session).generate_review(
                accepted.context.work_item_id, provider=provider
            )
            session.commit()

            assert result.status is GenerationStatus.SUCCEEDED
            assert result.attempt.purpose is GenerationPurpose.EDITOR_REVIEW
            assert result.attempt_created and result.review_created
            review = result.review
            assert review is not None
            assert review.content_draft_id == draft_id
            assert review.generation_attempt_id == result.attempt.id
            # A major model finding computes REVISE deterministically.
            assert review.verdict is ReviewVerdict.REVISE
            rows = ReviewRepository(session).list_findings(review.id)
            assert {row.finding_key for row in rows} == {"ton-gevsek", "iddia-cercevesi"}
            assert all(row.origin is FindingOrigin.MODEL_SIGNAL for row in rows)

            refs = result.attempt.input_refs
            assert refs["schema"] == "editor-review/1"
            assert refs["content_draft_id"] == str(draft_id)
            assert refs["engine_name"] == "editor"
            assert refs["verdict_policy"] == "editor-verdict/1"

    def test_empty_findings_is_a_valid_pass(self, harness: Harness) -> None:
        accepted, _, _ = editing_context(harness)
        with harness.session() as session:
            result = EditorEngine(session).generate_review(
                accepted.context.work_item_id,
                provider=FakeStructuredProvider(payload={"findings": []}),
            )
            session.commit()
            assert result.review is not None
            assert result.review.verdict is ReviewVerdict.PASS

    def test_projection_is_bounded_and_leak_free(self, harness: Harness) -> None:
        accepted, _, claim_id = editing_context(harness)
        with harness.session() as session:
            provider = CapturingFake(payload=review_payload(claim_id))
            EditorEngine(session).generate_review(accepted.context.work_item_id, provider=provider)
            session.commit()
            request = provider.last_request
            assert request is not None
            serialized = str(request.input_projection).lower()
            for marker in ("clean_text", "raw_payload", "http", "govdesi", "api_key"):
                assert marker not in serialized
            projection = request.input_projection
            # The draft body under review (flat, depth-bounded) and the
            # provenance identities.
            assert projection["draft_blocks"]
            assert all(block["block_id"] for block in projection["draft_blocks"])
            assert projection["claim_usages"]
            assert projection["uncertainty_discharges"]
            for evidence in projection["evidence_units"]:
                assert uuid.UUID(evidence["research_evidence_id"])
                assert len(evidence["statement"]) <= 500
            # The model judges only against the projection; no verdict field
            # exists anywhere in the instructions contract.
            assert "EDİTÖRSÜN" in request.instructions
            assert "verdict" not in str(request.input_projection)

    def test_same_identity_reuses_without_provider_call(self, harness: Harness) -> None:
        accepted, _, claim_id = editing_context(harness)
        with harness.session() as session:
            provider = CapturingFake(payload=review_payload(claim_id))
            engine = EditorEngine(session)
            first = engine.generate_review(accepted.context.work_item_id, provider=provider)
            session.commit()
            second = engine.generate_review(accepted.context.work_item_id, provider=provider)
            session.commit()
            assert provider.invocations == 1
            assert second.reused is True
            assert first.review is not None and second.review is not None
            assert second.review.id == first.review.id
            assert session.scalar(select(func.count()).select_from(EditorialReview)) == 1

    def test_unknown_anchor_is_validation_failed_with_zero_rows(self, harness: Harness) -> None:
        accepted, _, _ = editing_context(harness)
        bad = review_payload()
        bad["findings"][0]["block_id"] = "hayalet-blok"
        with harness.session() as session:
            result = EditorEngine(session).generate_review(
                accepted.context.work_item_id, provider=FakeStructuredProvider(payload=bad)
            )
            session.commit()
            assert result.status is GenerationStatus.VALIDATION_FAILED
            assert result.attempt.error_class == "domain_validation"
            assert result.review is None
            assert session.scalar(select(func.count()).select_from(EditorialReview)) == 0

    def test_forged_drift_key_is_validation_failed(self, harness: Harness) -> None:
        accepted, _, _ = editing_context(harness)
        bad = review_payload()
        bad["findings"][0]["finding_key"] = "drift-sahte"
        with harness.session() as session:
            result = EditorEngine(session).generate_review(
                accepted.context.work_item_id, provider=FakeStructuredProvider(payload=bad)
            )
            session.commit()
            assert result.status is GenerationStatus.VALIDATION_FAILED
            assert session.scalar(select(func.count()).select_from(EditorialReview)) == 0

    def test_verdict_smuggling_is_schema_rejected(self, harness: Harness) -> None:
        accepted, _, _ = editing_context(harness)
        with harness.session() as session:
            result = EditorEngine(session).generate_review(
                accepted.context.work_item_id,
                provider=FakeStructuredProvider(payload={"findings": [], "verdict": "pass"}),
            )
            session.commit()
            assert result.status is GenerationStatus.VALIDATION_FAILED
            assert result.review is None

    def test_provider_timeout_is_a_durable_failed_attempt(self, harness: Harness) -> None:
        accepted, _, _ = editing_context(harness)
        with harness.session() as session:
            result = EditorEngine(session).generate_review(
                accepted.context.work_item_id,
                provider=FakeStructuredProvider(
                    failure=ProviderFailureKind.TIMEOUT, failure_class="deadline"
                ),
            )
            session.commit()
            assert result.status is GenerationStatus.TIMEOUT
            assert result.review is None

    def test_preconditions_cost_zero_provider_calls(self, harness: Harness) -> None:
        from test_drafts import accepted_context

        accepted = accepted_context(harness)  # work item stays DRAFTING
        with harness.session() as session:
            provider = FakeStructuredProvider(payload={"findings": []})
            with pytest.raises(ReviewPreconditionError, match="EDITING"):
                EditorEngine(session).generate_review(
                    accepted.context.work_item_id, provider=provider
                )
            assert provider.invocations == 0

    def test_rework_regeneration_receives_review_findings(self, harness: Harness) -> None:
        """The Editor loop closes: a revise review pinned in the rework
        entry travels to the Writer projection as bounded findings."""
        from test_writer_generation import writer_payload

        from contentos.drafts.generation import WriterEngine
        from contentos.reviews.service import ReviewService
        from contentos.reviews.values import ReviewFindingInput
        from contentos.workflow.enums import WorkflowActorOrigin, WorkflowState
        from contentos.workflow.service import WorkflowService

        accepted, _, claim_id = editing_context(harness)
        with harness.session() as session:
            creation = ReviewService(session).create_review(
                accepted.context.work_item_id,
                [
                    ReviewFindingInput(
                        finding_key="iddia-cercevesi",
                        dimension=FindingDimension.CLAIM_FAITHFULNESS,
                        severity=FindingSeverity.BLOCKING,
                        origin=FindingOrigin.MODEL_SIGNAL,
                        description="Metin iddiadan daha kesin konuşuyor.",
                        recommendation="Kaynak çerçevesine dön.",
                        block_id="giris-2",
                        brief_claim_id=claim_id,
                    )
                ],
            )
            session.commit()
            service = WorkflowService(session)
            service.transition(
                accepted.context.work_item_id,
                WorkflowState.CHANGES_REQUESTED,
                actor_origin=WorkflowActorOrigin.OPERATOR,
                reason="inceleme revize istedi",
                artifact_refs={"editorial_review_id": str(creation.review.id)},
                responsible_state=WorkflowState.DRAFTING,
            )
            service.transition(
                accepted.context.work_item_id,
                WorkflowState.DRAFTING,
                actor_origin=WorkflowActorOrigin.OPERATOR,
                reason="yazara yönlendirildi",
            )
            session.commit()

            from test_writer_generation import (
                CapturingFake as WriterCapturingFake,
            )

            provider = WriterCapturingFake(payload=writer_payload(accepted))
            result = WriterEngine(session).generate_draft(
                accepted.context.brief_id,
                provider=provider,
                retry_number=1,
                supersede_reason="editör bulgularıyla yeniden üretim",
            )
            session.commit()
            assert result.draft is not None and result.draft.version == 2
            request = provider.last_request
            assert request is not None
            findings = request.input_projection["editorial_findings"]
            assert len(findings) == 1
            assert findings[0]["finding_key"] == "iddia-cercevesi"
            assert findings[0]["block_id"] == "giris-2"
            assert findings[0]["brief_claim_id"] == str(claim_id)
            assert request.input_refs["rework_review_id"] == str(creation.review.id)

    def test_incomplete_materialization_recovers_with_next_retry(
        self, harness: Harness, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from contentos.reviews.errors import (
            ReviewConflictError,
            ReviewGenerationMaterializationError,
        )
        from contentos.reviews.service import ReviewService

        accepted, _, claim_id = editing_context(harness)
        with harness.session() as session:
            engine = EditorEngine(session)
            provider = CapturingFake(payload=review_payload(claim_id))

            def broken(*args: Any, **kwargs: Any) -> Any:
                raise ReviewConflictError("simulated persistence rejection")

            monkeypatch.setattr(ReviewService, "create_review", broken)
            with pytest.raises(ReviewGenerationMaterializationError):
                engine.generate_review(accepted.context.work_item_id, provider=provider)
            # The completed attempt keeps its REAL status and stays durable.
            session.commit()
            monkeypatch.undo()

            # Same retry cannot silently regenerate: raw output was never kept.
            with pytest.raises(IncompleteReviewMaterializationError, match="retry_number"):
                engine.generate_review(accepted.context.work_item_id, provider=provider)
            assert provider.invocations == 1

            # Explicit recovery: a NEW attempt with retry_number + 1.
            recovered = engine.generate_review(
                accepted.context.work_item_id, provider=provider, retry_number=1
            )
            session.commit()
            assert recovered.status is GenerationStatus.SUCCEEDED
            assert recovered.review is not None
            assert provider.invocations == 2
