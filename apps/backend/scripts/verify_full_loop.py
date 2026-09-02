"""End-to-end real-infrastructure verification of the FULL ContentOS loop.

Runs against REAL PostgreSQL (pgvector) + REAL Redis, addressed by the
standard CONTENTOS_* environment variables. Proves, in one process:

1. the complete migration chain 0001 -> head on a fresh database;
2. Phase 2/3 seeded through the REAL domain services (OFFICIAL sources
   -> discovery -> fetch -> normalization -> evidence -> promotion ->
   genuine commissionable score -> commissioning -> idea -> READY pack
   -> intent -> composed brief -> human acceptance);
3. Phase 4: writer -> editor -> QA (waiver) -> AWAITING_HUMAN_REVIEW;
4. Phase 5: a NAMED reviewer approval -> APPROVED with pins + actor;
5. Phase 7: assemble -> schedule -> publish over the REAL broker with
   the deterministic fake transport -> PUBLISHED with the durable
   attempt, idempotency key round-trip, and redelivery reuse;
6. ADR 0007: every claim usage of the published draft resolves
   Draft -> Usage -> Claim -> Evidence -> Document -> Snapshot -> Source.

Exit code 0 means every step held; any assertion failure is a real
regression. CI runs this in the separate real-infrastructure lane.
"""

# ruff: noqa: E402
import subprocess
import sys
import uuid

from sqlalchemy import select

from contentos.briefs.service import BriefService
from contentos.core.config import Settings
from contentos.db.session import create_database_engine, create_session_factory

sys.path.insert(0, "tests/unit")
from editorial_harness import (  # noqa: E402
    NOW,
    brief_payload,
    idea_batch_payload,
    intent_payload,
)

import contentos.media.models  # noqa: E402, F401
from contentos.ai.fake import FakeStructuredProvider  # noqa: E402
from contentos.auth.enums import UserRole  # noqa: E402
from contentos.auth.models import User  # noqa: E402
from contentos.auth.service import AuthService  # noqa: E402
from contentos.briefs.composition import BriefCompositionEngine  # noqa: E402
from contentos.briefs.repository import BriefRepository  # noqa: E402
from contentos.discovery.service import DiscoveryService  # noqa: E402
from contentos.duplicates.service import DuplicateDecisionService  # noqa: E402
from contentos.evidence_packs.enums import EvidenceItemRole  # noqa: E402
from contentos.evidence_packs.service import (  # noqa: E402
    EvidencePackService,
    EvidenceSelection,
)
from contentos.fetching.models import (  # noqa: E402
    FetchOutcome,
    FetchResult,
    RetryClassification,
    RobotsDecision,
)
from contentos.fetching.snapshot_service import FetchSnapshotService  # noqa: E402
from contentos.ideas.generation import IdeaGenerationEngine  # noqa: E402
from contentos.ideas.service import IdeaService  # noqa: E402
from contentos.normalization.service import NormalizationService  # noqa: E402
from contentos.opportunities.enums import (  # noqa: E402
    OpportunityActor,
    ResearchInputRole,
    ScoreEligibility,
)
from contentos.opportunities.models import OpportunityResearchInput  # noqa: E402
from contentos.opportunities.repository import OpportunityRepository  # noqa: E402
from contentos.opportunities.scoring_service import OpportunityScoringService  # noqa: E402
from contentos.opportunities.service import (  # noqa: E402
    OpportunityCommissioningService,
    ResearchPromotionService,
)
from contentos.payloads.postgres import PostgresRawPayloadStore  # noqa: E402
from contentos.research.enums import EvidenceType, ExtractionMethod  # noqa: E402
from contentos.research.service import ResearchEvidenceService  # noqa: E402
from contentos.search_intent.service import SearchIntentService  # noqa: E402
from contentos.sources.enums import SourceKind, TrustTier  # noqa: E402
from contentos.sources.service import SourceRegistryService  # noqa: E402
from contentos.workflow.enums import WorkflowActorOrigin, WorkflowState  # noqa: E402
from contentos.workflow.service import WorkflowService  # noqa: E402


def alembic(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", "run", "alembic", *args], capture_output=True, text=True, check=False
    )


settings = Settings()
engine = create_database_engine(settings)
session_factory = create_session_factory(engine)

upgrade = alembic("upgrade", "head")
assert upgrade.returncode == 0, upgrade.stderr[-2000:]
print("OK migration chain 0001 -> head on real PostgreSQL")


class Context:
    work_item_id: uuid.UUID
    brief_id: uuid.UUID


# ---- 1) Seed a full Phase 3 chain with a REAL commissionable score.
context = Context()
token = uuid.uuid4().hex[:8]
texts = [
    f"Belediye {token} etkinlik takvimi acik alan kutlamalarini duzenliyor.",
    f"Gida rehberi {token} ikram guvenligi kurallarini aciklıyor.",
    f"Saglik kurumu {token} havalandirma onerilerini yayimladi.",
    f"Tuketici rehberi {token} malzeme butcelemesini karsilastiriyor.",
]
with session_factory() as session:
    store = PostgresRawPayloadStore(session, max_payload_bytes=settings.fetch_max_body_bytes)
    document_ids: list[uuid.UUID] = []
    for index, doc_text in enumerate(texts):
        slug = f"kaynak-{index}-{token}"
        source = SourceRegistryService(session).register_source(
            slug=slug,
            name=f"Kaynak {index} {token}",
            kind=SourceKind.MANUAL,
            base_url=f"https://{slug}.example.test/",
            trust_tier=TrustTier.OFFICIAL,
        )
        discoveries = DiscoveryService(session)
        item = discoveries.discover_manual(source.id, f"https://{slug}.example.test/rehber")
        discoveries.accept_item(item.id)
        body = f"<html><p>{doc_text}</p></html>".encode()
        stored = store.put(body)
        snapshot = FetchSnapshotService(session).record_fetch_result(
            item.id,
            FetchResult(
                requested_url=item.canonical_url,
                outcome=FetchOutcome.SUCCESS,
                retry=RetryClassification.NOT_APPLICABLE,
                robots_decision=RobotsDecision.ALLOWED,
                fetched_at=NOW.replace(year=2026, month=9, day=2),
                duration_ms=2.0,
                final_url=item.canonical_url,
                status_code=200,
                content_type="text/html; charset=utf-8",
                body=body,
            ),
            raw_payload_ref=stored.ref.value,
        )
        document = NormalizationService(session).record_success(
            snapshot.id,
            extractor_name="html-basic",
            extractor_version="1",
            clean_text=f"{doc_text} Ayrintili ozgun metin {token}.",
            title=f"Rehber: {doc_text[:40]}",
            headings=(
                [
                    {"level": 2, "text": "Parti temasını seçmek"},
                    {"level": 2, "text": "Davetiye ve misafir listesi"},
                    {"level": 2, "text": "Süsleme fikirleri"},
                    {"level": 2, "text": "Pasta ve ikramlar"},
                ]
                if index == 0
                else [{"level": 2, "text": f"Bolum {index}"}]
            ),
        )
        document_ids.append(document.id)
    session.commit()
    decision_ids = []
    for document_id in document_ids:
        decision = DuplicateDecisionService(session).evaluate_and_record(document_id)
        decision_ids.append(decision.id)
    session.commit()

    promo = ResearchPromotionService(session).promote_research(document_ids[0])
    session.commit()
    context.work_item_id = promo.work_item_id
    opportunity_id = promo.opportunity_id
    repo = OpportunityRepository(session)
    for document_id, decision_id in zip(document_ids[1:], decision_ids[1:], strict=True):
        repo.insert_research_input(
            OpportunityResearchInput(
                opportunity_id=opportunity_id,
                normalized_document_id=document_id,
                duplicate_decision_id=decision_id,
                role=ResearchInputRole.SUPPORTING,
                added_by=OpportunityActor.OPERATOR,
                note=None,
                added_at=NOW,
            )
        )
    session.commit()
    evidence_ids: list[uuid.UUID] = []
    for document_id, statement in (
        (document_ids[0], "Takvim, acik alan kutlama saatlerini belirtiyor."),
        (document_ids[0], "Takvim, basvuru kosullarini siraliyor."),
        (document_ids[1], "Rehber, ikram saklama surelerini veriyor."),
        (document_ids[2], "Kurum, havalandirma araliklarini oneriyor."),
        (document_ids[3], "Rehber, malzeme fiyat araliklarini karsilastiriyor."),
        (document_ids[3], "Rehber, toplam butce kalemlerini listeliyor."),
    ):
        evidence = ResearchEvidenceService(session).record_evidence(
            document_id,
            evidence_type=EvidenceType.OBSERVATION,
            statement=statement,
            extraction_method=ExtractionMethod.MACHINE,
            source_locator="structured_metadata.author",
        )
        evidence_ids.append(evidence.id)
    session.commit()

    evaluation = OpportunityScoringService(session).evaluate_opportunity(opportunity_id)
    session.commit()
    assert evaluation.score.eligibility is ScoreEligibility.COMMISSIONABLE
    OpportunityCommissioningService(session).commission_opportunity(
        opportunity_id, reason="gerçek güçlü skor"
    )
    session.commit()

    execution = IdeaGenerationEngine(session).generate_candidates(
        opportunity_id, provider=FakeStructuredProvider(payload=idea_batch_payload())
    )
    session.commit()
    idea_id = execution.ideas[0].id
    IdeaService(session).select_idea(idea_id, reason="tek aday")
    session.commit()

    assembly = EvidencePackService(session).assemble_pack(
        opportunity_id,
        [
            EvidenceSelection(evidence_ids[0], EvidenceItemRole.KEY_FACT, "takvim"),
            EvidenceSelection(evidence_ids[2], EvidenceItemRole.KEY_FACT, "ikram"),
            EvidenceSelection(evidence_ids[3], EvidenceItemRole.SUPPORTING, "saglik"),
            EvidenceSelection(evidence_ids[4], EvidenceItemRole.SUPPORTING, "butce"),
        ],
        idea_id=idea_id,
    )
    session.commit()
    WorkflowService(session).transition(
        context.work_item_id,
        WorkflowState.SEO_RESEARCH,
        actor_origin=WorkflowActorOrigin.SYSTEM,
        reason="pack READY",
        artifact_refs={"evidence_pack_id": str(assembly.pack.id)},
    )
    session.commit()
    intent = SearchIntentService(session).synthesize(
        opportunity_id,
        idea_id=idea_id,
        provider=FakeStructuredProvider(payload=intent_payload()),
    )
    session.commit()
    WorkflowService(session).transition(
        context.work_item_id,
        WorkflowState.BRIEFING,
        actor_origin=WorkflowActorOrigin.SYSTEM,
        reason="intent hazır",
        artifact_refs={"search_intent_analysis_id": str(intent.analysis.id)},
    )
    session.commit()
    composed = BriefCompositionEngine(session).compose(
        context.work_item_id,
        idea_id=idea_id,
        evidence_pack_id=assembly.pack.id,
        search_intent_analysis_id=intent.analysis.id,
        provider=FakeStructuredProvider(payload=brief_payload(evidence_ids)),
    )
    session.commit()
    context.brief_id = composed.brief.id
    BriefService(session).accept_for_drafting(context.brief_id, reason="kapsam eksiksiz")
    session.commit()
print("OK seeded Phase 3 chain to DRAFTING (accepted brief with media needs)")

# ---- 2) Writer + Editor (eager) -> QA_REVIEW -> waiver -> AWAITING -> APPROVED.
from types import SimpleNamespace

from contentos.ai.fake import FakeStructuredProvider as _Fake
from contentos.briefs.enums import BriefClaimKind
from contentos.drafts.policies import build_required_handling_manifest
from contentos.evidence_packs.repository import EvidencePackRepository
from contentos.qa.enums import WaivableGateKey
from contentos.qa.gates import QaGateEngine
from contentos.qa.service import QaService
from contentos.queue.celery import create_celery_app
from contentos.reviews.repository import ReviewRepository
from contentos.worker.editorial_tasks import (
    GENERATE_EDITOR_REVIEW_TASK,
    GENERATE_WRITER_DRAFT_TASK,
    register_editorial_pipeline_tasks,
)
from contentos.worker.runtime import WorkerRuntime

sys.path.insert(0, "tests/unit")
from test_writer_generation import writer_payload  # noqa: E402

eager = Settings(celery_task_always_eager=True)
provider_holder = {"provider": _Fake()}
runtime = WorkerRuntime(
    eager,
    session_factory=session_factory,
    structured_generation_provider_factory=lambda: provider_holder["provider"],
)


class RecordingWorkerDispatcher:
    def __init__(self):
        self.calls = []

    def enqueue(self, task_name, payload, *, request_id=None):
        self.calls.append((task_name, payload))


worker_app = create_celery_app(eager)
register_editorial_pipeline_tasks(worker_app, runtime, dispatcher=RecordingWorkerDispatcher())

with session_factory() as session:
    briefs = BriefRepository(session)
    brief = briefs.get_brief(context.brief_id)
    packs = EvidencePackRepository(session)
    pack = packs.get_pack(brief.evidence_pack_id)
    manifest = build_required_handling_manifest(
        brief, pack, packs.list_contradictions(pack.id), briefs.list_claims(brief.id)
    )
    by_kind = {c.claim_kind: c.id for c in briefs.list_claims(brief.id)}
    accepted = SimpleNamespace(
        claim_ids=[by_kind[BriefClaimKind.FACTUAL], by_kind[BriefClaimKind.SOURCE_ASSERTION]],
        handling_ids=tuple(e.handling_id for e in manifest),
    )

provider_holder["provider"] = _Fake(payload=writer_payload(accepted))
writer = (
    worker_app.tasks[GENERATE_WRITER_DRAFT_TASK]
    .apply(kwargs={"content_brief_id": str(context.brief_id)})
    .get()
)
assert writer["status"] == "completed", writer
provider_holder["provider"] = _Fake(payload={"findings": []})
editor = (
    worker_app.tasks[GENERATE_EDITOR_REVIEW_TASK]
    .apply(kwargs={"work_item_id": str(context.work_item_id)})
    .get()
)
assert editor["review_verdict"] == "pass", editor
with session_factory() as session:
    review = ReviewRepository(session).get_active_review(context.work_item_id)
    WorkflowService(session).transition(
        context.work_item_id,
        WorkflowState.QA_REVIEW,
        actor_origin=WorkflowActorOrigin.OPERATOR,
        reason="inceleme temiz; kalite kontrole gec",
        artifact_refs={
            "editorial_review_id": str(review.id),
            "content_draft_id": writer["content_draft_id"],
            "review_verdict": review.verdict.value,
            "content_hash": "0" * 64,
        },
    )
    session.commit()
    QaService(session).add_waiver(
        context.work_item_id,
        WaivableGateKey.MEDIA_NEEDS,
        reason="gorsel gereksinimi bilincli ertelendi",
    )
    session.commit()
    gate_run = QaGateEngine(session).run_gates(context.work_item_id)
    session.commit()
    assert gate_run.outcome.value == "ready_for_human_review"
    WorkflowService(session).transition(
        context.work_item_id,
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
print("OK package to AWAITING_HUMAN_REVIEW on PG (writer/editor/QA via real services)")

from contentos.decisions.service import DecisionService, decision_artifact_refs

with session_factory() as session:
    reviewer = AuthService(session).provision_user(
        f"pub-reviewer-{token}",
        display_name="PG Publishing Reviewer",
        password="a-long-reviewer-password",
        roles=[UserRole.REVIEWER],
        reason="p1 dogrulamasi",
    )
    session.commit()
    approval = DecisionService(session).record_approval(
        context.work_item_id, reviewer=reviewer, reason="paket eksiksiz; onayliyorum"
    )
    session.commit()
    WorkflowService(session).transition(
        context.work_item_id,
        WorkflowState.APPROVED,
        actor_origin=WorkflowActorOrigin.OPERATOR,
        reason=approval.reason,
        artifact_refs=decision_artifact_refs(approval),
        actor_user_id=reviewer.id,
    )
    session.commit()
print("OK named approval -> APPROVED on PG")

# ---- P3: schedule -> publish over the REAL broker with the fake transport.
import base64
import json

import redis as redis_lib

from contentos.publishing.assembler import PublicationAssembler
from contentos.publishing.models import PublicationAttempt
from contentos.publishing.service import PublishingService
from contentos.publishing.transport import FakePublishingTransport, TransportOutcome
from contentos.worker.editorial_tasks import PUBLISH_PACKAGE_TASK
from contentos.workflow.repository import WorkflowRepository as _WRepo  # noqa: E402

with session_factory() as session:
    reviewer = session.execute(
        select(User).where(User.username == f"pub-reviewer-{token}")
    ).scalar_one()
    assembly = PublicationAssembler(session).assemble(context.work_item_id, assembled_by=reviewer)
    session.commit()
    package_id = assembly.package.id
    PublishingService(session).schedule_publication(
        context.work_item_id,
        package_id,
        reason="yayin planina alindi",
        actor_user_id=reviewer.id,
    )
    session.commit()
    item = _WRepo(session).get_by_id(context.work_item_id)
    assert item.current_state.value == "scheduled"
print("OK package assembled + scheduled on PG with the named human")

transport = FakePublishingTransport(
    outcome=TransportOutcome(status="succeeded", remote_publication_ref="konsepthane-pub-verify-1")
)
publish_runtime = WorkerRuntime(
    eager,
    session_factory=session_factory,
    publishing_transport_factory=lambda: transport,
)
publish_app = create_celery_app(eager)
register_editorial_pipeline_tasks(
    publish_app, publish_runtime, dispatcher=RecordingWorkerDispatcher()
)

redis_client = redis_lib.Redis.from_url(eager.redis_broker_url.get_secret_value())
publish_app.send_task(
    PUBLISH_PACKAGE_TASK,
    kwargs={"work_item_id": str(context.work_item_id)},
    headers={"request_id": "publish-verify-1"},
)
raw = redis_client.lpop("contentos.default")
assert raw is not None
envelope = json.loads(raw)
assert envelope["headers"]["task"] == PUBLISH_PACKAGE_TASK
assert envelope["headers"]["request_id"] == "publish-verify-1"
assert "redis://" not in json.dumps(envelope)
args, kwargs, _ = json.loads(base64.b64decode(envelope["body"]))

result = publish_app.tasks[PUBLISH_PACKAGE_TASK].apply(kwargs=kwargs).get()
assert result["status"] == "completed", result
assert result["remote_publication_ref"] == "konsepthane-pub-verify-1"
with session_factory() as session:
    item = _WRepo(session).get_by_id(context.work_item_id)
    assert item.current_state.value == "published"
    attempt = session.execute(select(PublicationAttempt)).scalar_one()
    assert attempt.status == "succeeded"
    assert attempt.idempotency_key == transport.calls[0]["idempotency_key"]
    events = _WRepo(session).list_events(context.work_item_id)
    assert events[-1].to_state.value == "published"
    assert events[-1].artifact_refs["publication_package_id"] == str(package_id)
    assert events[-1].artifact_refs["remote_publication_ref"] == "konsepthane-pub-verify-1"
print("OK publish task via real broker: durable attempt -> SYSTEM PUBLISHED with pins")

redelivered = publish_app.tasks[PUBLISH_PACKAGE_TASK].apply(kwargs=kwargs).get()
assert redelivered["status"] == "reused"
assert len(transport.calls) == 1
with session_factory() as session:
    assert len(session.execute(select(PublicationAttempt)).scalars().all()) == 1
redis_client.close()
print("OK publish redelivery reused the durable result; one dispatch total")

# ---- ADR 0007: the provenance walk from the PUBLISHED package. --------------
from contentos.briefs.models import BriefClaim, BriefClaimEvidence
from contentos.drafts.models import DraftClaimUsage  # noqa: F401
from contentos.drafts.repository import DraftRepository
from contentos.fetching.snapshots import FetchSnapshot
from contentos.normalization.models import NormalizedDocument
from contentos.publishing.models import PublicationPackage
from contentos.research.models import ResearchEvidence
from contentos.sources.models import Source

with session_factory() as session:
    package = session.get(PublicationPackage, package_id)
    assert package is not None
    draft_repo = DraftRepository(session)
    draft = draft_repo.get_draft(package.content_draft_id)
    assert draft is not None and draft.content_hash == package.content_hash
    usages = draft_repo.list_claim_usages(draft.id)
    assert usages, "the published draft must bind claims"
    chains = 0
    for usage in usages:
        claim = session.get(BriefClaim, usage.brief_claim_id)
        assert claim is not None
        links = (
            session.query(BriefClaimEvidence).filter(BriefClaimEvidence.claim_id == claim.id).all()
        )
        assert links, f"claim {claim.claim_key} has no evidence links"
        for link in links:
            evidence = session.get(ResearchEvidence, link.research_evidence_id)
            assert evidence is not None
            document = session.get(NormalizedDocument, evidence.normalized_document_id)
            assert document is not None
            snapshot = session.get(FetchSnapshot, document.fetch_snapshot_id)
            assert snapshot is not None
            source = session.get(Source, evidence.source_id)
            assert source is not None
            chains += 1
print(
    "OK ADR 0007 chain resolvable from the PUBLISHED package: "
    f"{len(usages)} usages -> {chains} full chains"
)

print("ALL FULL-LOOP REAL-INFRASTRUCTURE VERIFICATIONS PASSED")
