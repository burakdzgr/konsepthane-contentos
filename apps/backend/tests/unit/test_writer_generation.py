"""Writer engine tests (fake provider, no network, SQLite real services)."""

import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from editorial_harness import Harness
from sqlalchemy import func, select
from test_drafts import AcceptedContext, accepted_context

import contentos.drafts.models  # noqa: F401
from contentos.ai.dto import GenerationRequest, ProviderOutputSchema, ProviderResult
from contentos.ai.enums import GenerationPurpose, GenerationStatus, ProviderFailureKind
from contentos.ai.fake import FakeStructuredProvider
from contentos.drafts.enums import DraftOrigin
from contentos.drafts.errors import (
    DraftGenerationMaterializationError,
    DraftPreconditionError,
    IncompleteDraftMaterializationError,
)
from contentos.drafts.generation import WriterEngine
from contentos.drafts.models import ContentDraft
from contentos.drafts.service import DraftService
from contentos.drafts.values import WRITER_ENGINE_NAME


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


def writer_payload(accepted: AcceptedContext, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "title_proposal": "Evde balon temalı doğum günü planı",
        "sections": [
            {
                "key": "giris",
                "heading": "Neden evde parti?",
                "blocks": [
                    {
                        "block_id": "giris-1",
                        "kind": "paragraph",
                        "text": "Evde parti hem samimi hem bütçe dostudur.",
                        "claim_refs": [],
                        "uncertainty_refs": [],
                    },
                    {
                        "block_id": "giris-2",
                        "kind": "paragraph",
                        "text": "Kaynaklara göre konsept detayları netleştirilmelidir.",
                        "claim_refs": [str(accepted.claim_ids[0])],
                        "uncertainty_refs": [],
                    },
                    {
                        "block_id": "kapsam-notlari",
                        "kind": "callout",
                        "text": (
                            "Bu rehber sınırlı kaynak sinyaline dayanır; eksik "
                            "arama verileri ve yerel farklılıklar belirsizlik "
                            "yaratabilir, çelişen tahminler aralık olarak verilir."
                        ),
                        "claim_refs": [],
                        "uncertainty_refs": list(accepted.handling_ids),
                    },
                ],
            },
            {
                "key": "plan",
                "heading": "Üç saatlik hazırlık planı",
                "blocks": [
                    {
                        "block_id": "plan-1",
                        "kind": "how_to_step",
                        "text": "İlk saat: tema ve alan hazırlığı.",
                        "claim_refs": [],
                        "uncertainty_refs": [],
                    }
                ],
            },
            {
                "key": "butce",
                "heading": "Bütçe dostu öneriler",
                "blocks": [
                    {
                        "block_id": "butce-1",
                        "kind": "paragraph",
                        "text": (
                            "İkinci kaynağın aktardığı bütçe aralığı planlamada esas alınabilir."
                        ),
                        "claim_refs": [str(accepted.claim_ids[1])],
                        "uncertainty_refs": [],
                    }
                ],
            },
        ],
    }
    payload.update(overrides)
    return payload


class TestWriterGeneration:
    def test_happy_path(self, harness: Harness) -> None:
        accepted = accepted_context(harness)
        with harness.session() as session:
            provider = CapturingFake(payload=writer_payload(accepted))
            result = WriterEngine(session).generate_draft(
                accepted.context.brief_id, provider=provider
            )
            session.commit()

            assert result.status is GenerationStatus.SUCCEEDED
            assert result.attempt.purpose is GenerationPurpose.WRITER_DRAFT
            assert result.attempt_created and result.draft_created
            draft = result.draft
            assert draft is not None
            assert draft.origin is DraftOrigin.WRITER_ENGINE
            assert draft.engine_name == WRITER_ENGINE_NAME
            assert draft.generation_attempt_id == result.attempt.id
            assert draft.manual_input_hash is None
            assert draft.title_proposal == "Evde balon temalı doğum günü planı"
            assert draft.uncertainty_coverage["status"] == "evaluated"
            assert draft.originality_result["outcome"] == "passed"

            refs = result.attempt.input_refs
            assert refs["schema"] == "writer-draft/1"
            assert refs["content_brief_id"] == str(accepted.context.brief_id)
            assert refs["engine_name"] == "writer"
            assert refs["validation_policy"] == "writer-validation/1"

    def test_projection_is_bounded_and_leak_free(self, harness: Harness) -> None:
        accepted = accepted_context(harness)
        with harness.session() as session:
            provider = CapturingFake(payload=writer_payload(accepted))
            WriterEngine(session).generate_draft(accepted.context.brief_id, provider=provider)
            session.commit()
            request = provider.last_request
            assert request is not None
            projection = request.input_projection
            serialized = str(projection).lower()
            for marker in ("clean_text", "raw_payload", "http", "govdesi", "api_key"):
                assert marker not in serialized
            # Every evidence-derived datum keeps its ResearchEvidence id.
            assert projection["evidence_units"]
            for evidence in projection["evidence_units"]:
                assert uuid.UUID(evidence["research_evidence_id"])
                assert len(evidence["statement"]) <= 500
            for claim in projection["claims"]:
                assert all(uuid.UUID(ref) for ref in claim["evidence_ids"]) or True
            # The manifest travels with the projection; instructions are the
            # versioned template and never persisted on the attempt.
            assert projection["required_handling"]
            assert "YAZARSIN" in request.instructions

    def test_same_identity_reuses_without_provider_call(self, harness: Harness) -> None:
        accepted = accepted_context(harness)
        with harness.session() as session:
            provider = CapturingFake(payload=writer_payload(accepted))
            engine = WriterEngine(session)
            first = engine.generate_draft(accepted.context.brief_id, provider=provider)
            session.commit()
            second = engine.generate_draft(accepted.context.brief_id, provider=provider)
            session.commit()
            assert provider.invocations == 1
            assert second.reused is True
            assert second.draft is not None and first.draft is not None
            assert second.draft.id == first.draft.id
            assert session.scalar(select(func.count()).select_from(ContentDraft)) == 1

    def test_explicit_retry_produces_new_version(self, harness: Harness) -> None:
        accepted = accepted_context(harness)
        with harness.session() as session:
            engine = WriterEngine(session)
            first = engine.generate_draft(
                accepted.context.brief_id,
                provider=CapturingFake(payload=writer_payload(accepted)),
            )
            session.commit()
            second = engine.generate_draft(
                accepted.context.brief_id,
                provider=CapturingFake(
                    payload=writer_payload(accepted, title_proposal="Yenilenmiş balon teması planı")
                ),
                retry_number=1,
                supersede_reason="operatör yeniden üretim istedi",
            )
            session.commit()
            assert second.attempt.id != first.attempt.id
            assert second.attempt.retry_number == 1
            assert second.draft is not None and second.draft.version == 2
            assert first.draft is not None
            old = session.get(ContentDraft, first.draft.id)
            assert old is not None and old.superseded_by_draft_id == second.draft.id

    def test_unknown_claim_ref_is_validation_failed(self, harness: Harness) -> None:
        accepted = accepted_context(harness)
        bad = writer_payload(accepted)
        bad["sections"][0]["blocks"][1]["claim_refs"] = [str(uuid.uuid4())]
        with harness.session() as session:
            result = WriterEngine(session).generate_draft(
                accepted.context.brief_id, provider=FakeStructuredProvider(payload=bad)
            )
            session.commit()
            assert result.status is GenerationStatus.VALIDATION_FAILED
            assert result.attempt.error_class == "domain_validation"
            assert result.draft is None
            assert session.scalar(select(func.count()).select_from(ContentDraft)) == 0

    def test_missing_handling_coverage_is_validation_failed(self, harness: Harness) -> None:
        accepted = accepted_context(harness)
        bad = writer_payload(accepted)
        bad["sections"][0]["blocks"][2]["uncertainty_refs"] = []
        with harness.session() as session:
            result = WriterEngine(session).generate_draft(
                accepted.context.brief_id, provider=FakeStructuredProvider(payload=bad)
            )
            session.commit()
            assert result.status is GenerationStatus.VALIDATION_FAILED
            assert result.attempt.error_class == "domain_validation"
            assert session.scalar(select(func.count()).select_from(ContentDraft)) == 0

    def test_provider_timeout_is_a_durable_failed_attempt(self, harness: Harness) -> None:
        accepted = accepted_context(harness)
        with harness.session() as session:
            result = WriterEngine(session).generate_draft(
                accepted.context.brief_id,
                provider=FakeStructuredProvider(
                    failure=ProviderFailureKind.TIMEOUT, failure_class="deadline"
                ),
            )
            session.commit()
            assert result.status is GenerationStatus.TIMEOUT
            assert result.draft is None

    def test_preconditions_cost_zero_provider_calls(self, harness: Harness) -> None:
        from editorial_harness import Context, seed_draft_brief

        with harness.session() as session:
            context = Context()
            seed_draft_brief(session, context)  # brief stays DRAFT
            session.commit()
            provider = FakeStructuredProvider(payload={})
            with pytest.raises(DraftPreconditionError, match="accepted"):
                WriterEngine(session).generate_draft(context.brief_id, provider=provider)
            assert provider.invocations == 0

    def test_incomplete_materialization_recovers_with_next_retry(
        self, harness: Harness, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        accepted = accepted_context(harness)
        with harness.session() as session:
            engine = WriterEngine(session)
            provider = CapturingFake(payload=writer_payload(accepted))

            from contentos.drafts.errors import DraftConflictError

            def broken(*args: Any, **kwargs: Any) -> Any:
                raise DraftConflictError("simulated persistence rejection")

            monkeypatch.setattr(DraftService, "create_generated_draft", broken)
            with pytest.raises(DraftGenerationMaterializationError):
                engine.generate_draft(accepted.context.brief_id, provider=provider)
            # The completed attempt keeps its REAL status and stays durable.
            session.commit()
            monkeypatch.undo()

            # Same retry cannot silently regenerate: raw output was never kept.
            with pytest.raises(IncompleteDraftMaterializationError, match="retry_number"):
                engine.generate_draft(accepted.context.brief_id, provider=provider)
            assert provider.invocations == 1

            # Explicit recovery: a NEW attempt with retry_number + 1.
            recovered = engine.generate_draft(
                accepted.context.brief_id, provider=provider, retry_number=1
            )
            session.commit()
            assert recovered.status is GenerationStatus.SUCCEEDED
            assert recovered.draft is not None
            assert provider.invocations == 2
