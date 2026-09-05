"""Intelligence signals: privacy, role-aware extractors, idempotency, bands,
read endpoints and the fail-safe worker hook."""

import hashlib
import json
import uuid
from collections.abc import Iterable
from typing import Any

import pytest
from editorial_harness import NOW, Context, Harness, seed_scored
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_research_tasks import ARTICLE_HTML, RecordingDispatcher, committed_success_snapshot
from test_research_tasks import Harness as PipelineHarness

from contentos.discovery.service import DiscoveryService
from contentos.fetching.models import (
    FetchOutcome,
    FetchResult,
    RetryClassification,
    RobotsDecision,
)
from contentos.fetching.snapshot_service import FetchSnapshotService
from contentos.intelligence.enums import Band, SignalFamily
from contentos.intelligence.extractors import DEFAULT_CAPABILITIES, capabilities_of
from contentos.intelligence.models import IntelligenceSignal
from contentos.intelligence.privacy import (
    MAX_PATTERN_LENGTH,
    bounded_pattern,
    is_pii_free,
    scrub_pii,
)
from contentos.intelligence.service import (
    MODERATE_MIN_OCCURRENCES,
    STRONG_MIN_OCCURRENCES,
    STRONG_MIN_SOURCES,
    DocumentNotFoundError,
    IntelligenceSignalService,
    OpportunityNotFoundError,
    band_for,
    signal_bands_for_opportunity,
)
from contentos.normalization.service import NormalizationService
from contentos.opportunities.models import EditorialOpportunity
from contentos.sources.enums import SourceKind, TrustTier
from contentos.sources.service import SourceRegistryService
from contentos.strategy.service import StrategyService
from contentos.worker import research_tasks
from contentos.worker.research_tasks import (
    EVALUATE_DUPLICATE_TASK,
    NORMALIZE_FETCH_TASK,
    _extract_intelligence_signals,
)

COMMUNITY_PARAGRAPH = (
    "Merhaba arkadaşlar, kızım Elif 3 yaşında olacak. Ev partisi için süsleme "
    "fikri olan var mı? Bana 0532 123 45 67 numarasından ya da "
    "elif.anne@example.com adresinden ulaşabilirsiniz."
)
COMMUNITY_TEXT = (
    f"{COMMUNITY_PARAGRAPH}\n\n"
    "Kızım Elif için 0532 123 45 67 numaralı pastacıdan başka pasta nereden bulabilirim?\n\n"
    "Ayrıca https://forum.example.test/konu?id=42 linkteki gibi bir konsept "
    "önerir misiniz? @elif_anne"
)


@pytest.fixture()
def harness() -> Harness:
    return Harness()


def make_document(
    session: Session,
    *,
    slug: str,
    title: str | None,
    clean_text: str,
    headings: Iterable[str] = (),
    capabilities: Iterable[str] | None = None,
    url: str | None = None,
) -> uuid.UUID:
    source = SourceRegistryService(session).register_source(
        slug=slug,
        name=f"Kaynak {slug}",
        kind=SourceKind.MANUAL,
        base_url=f"https://{slug}.example.test/",
        trust_tier=TrustTier.GENERAL,
    )
    if capabilities is not None:
        source.capabilities = list(capabilities)
    discoveries = DiscoveryService(session)
    item = discoveries.discover_manual(source.id, url or f"https://{slug}.example.test/konu-1")
    discoveries.accept_item(item.id)
    body = f"<html>{slug}</html>".encode()
    snapshot = FetchSnapshotService(session).record_fetch_result(
        item.id,
        FetchResult(
            requested_url=item.canonical_url,
            outcome=FetchOutcome.SUCCESS,
            retry=RetryClassification.NOT_APPLICABLE,
            robots_decision=RobotsDecision.ALLOWED,
            fetched_at=NOW,
            duration_ms=2.0,
            final_url=item.canonical_url,
            status_code=200,
            content_type="text/html; charset=utf-8",
            body=body,
        ),
        raw_payload_ref=f"memory:sha256:{hashlib.sha256(body).hexdigest()}",
    )
    document = NormalizationService(session).record_success(
        snapshot.id,
        extractor_name="html-basic",
        extractor_version="1",
        clean_text=clean_text,
        title=title,
        headings=[{"level": 2, "text": text} for text in headings],
    )
    session.commit()
    return document.id


def all_rows(session: Session) -> list[IntelligenceSignal]:
    return list(session.scalars(select(IntelligenceSignal)))


class TestPrivacy:
    def test_scrubs_turkish_phone_email_handle_and_query_url(self) -> None:
        text = (
            "Bana 0532 123 45 67 ya da +90 (532) 123-45-67 ulaşın, e-posta ayse.k@example.com, "
            "instagram @ayse_k, link https://forum.example.test/konu?id=42"
        )
        cleaned = scrub_pii(text)
        assert "0532" not in cleaned and "532" not in cleaned
        assert "example.com" not in cleaned and "@ayse_k" not in cleaned
        assert "id=42" not in cleaned
        assert cleaned.count("[telefon]") == 2
        assert "[e-posta]" in cleaned and "[hesap]" in cleaned and "[bağlantı]" in cleaned

    def test_replaces_named_persons_after_turkish_cues(self) -> None:
        assert scrub_pii("kızım Elif 3 yaşında") == "kızım [ad] 3 yaşında"
        assert scrub_pii("Benim adım Ayşe, oğlum Kerem için") == "Benim adım [ad], oğlum [ad] için"
        assert scrub_pii("ismim Zeynep") == "ismim [ad]"
        assert scrub_pii("kızımın adı Defne") == "kızımın adı [ad]"

    def test_keeps_years_prices_and_function_words(self) -> None:
        text = "2026 yılında 1500 TL bütçe ile kızım için doğum günü"
        assert scrub_pii(text) == text
        assert is_pii_free(text) is True
        assert is_pii_free("kızım Elif için parti") is False

    def test_bounded_pattern_never_exceeds_limit(self) -> None:
        long_text = " ".join(["süsleme"] * 100)
        pattern = bounded_pattern(long_text)
        assert len(pattern) <= MAX_PATTERN_LENGTH
        assert not pattern.endswith(" ")


class TestExtractors:
    def test_community_extractor_stores_only_scrubbed_need_patterns(self, harness: Harness) -> None:
        with harness.session() as session:
            document_id = make_document(
                session,
                slug="forum",
                title="1 yaş doğum günü için ne yapabilirim?",
                headings=["Kızım Elif için tema önerir misiniz?"],
                clean_text=COMMUNITY_TEXT,
            )
            result = IntelligenceSignalService(session).extract_for_document(
                document_id, capabilities=["community_need"]
            )
            session.commit()
            rows = all_rows(session)

        assert result.families == (SignalFamily.COMMUNITY_NEED,)
        assert result.created == len(rows) >= 4
        assert {row.family for row in rows} == {SignalFamily.COMMUNITY_NEED}
        patterns = {row.value["pattern"] for row in rows}
        assert "1 yaş doğum günü için ne yapabilirim?" in patterns
        assert "Kızım [ad] için tema önerir misiniz?" in patterns
        assert (
            "Kızım [ad] için [telefon] numaralı pastacıdan başka pasta nereden bulabilirim?"
            in patterns
        )
        by_pattern = {row.value["pattern"]: row for row in rows}
        title_row = by_pattern["1 yaş doğum günü için ne yapabilirim?"]
        assert title_row.value["category"] == "doğum günü"
        assert set(title_row.value["cues"]) == {"?", "ne yapabilirim"}
        assert title_row.subject == title_row.value["pattern"]
        for row in rows:
            serialized = json.dumps(row.value, ensure_ascii=False) + row.subject
            assert COMMUNITY_PARAGRAPH not in serialized
            assert "Elif" not in serialized
            assert "0532" not in serialized and "example.com" not in serialized
            assert "@elif_anne" not in serialized and "id=42" not in serialized
            assert len(row.value["pattern"]) <= MAX_PATTERN_LENGTH
            assert is_pii_free(row.subject)
            assert set(row.value) == {"pattern", "category", "cues"}

    def test_community_capability_never_yields_market_or_competition(
        self, harness: Harness
    ) -> None:
        with harness.session() as session:
            document_id = make_document(
                session,
                slug="topluluk",
                title="Düğün için masa süsü nereden alınır?",
                clean_text="Düğün için masa süsü nereden alınır?",
            )
            IntelligenceSignalService(session).extract_for_document(
                document_id, capabilities=["community_need"]
            )
            session.commit()
            families = {row.family for row in all_rows(session)}
        assert families == {SignalFamily.COMMUNITY_NEED}

    def test_taxonomy_extractor_classifies_terms_and_skips_navigation(
        self, harness: Harness
    ) -> None:
        with harness.session() as session:
            document_id = make_document(
                session,
                slug="magaza",
                title="Unicorn Temalı Doğum Günü Balon Seti",
                headings=["Safari", "Ayıcık Temalı", "Sepet", "Doğum Günü", "Hesabım"],
                clean_text="Mağaza kategori sayfası.",
            )
            result = IntelligenceSignalService(session).extract_for_document(
                document_id, capabilities=["taxonomy"]
            )
            session.commit()
            rows = all_rows(session)

        assert result.families == (SignalFamily.TAXONOMY,)
        kinds = {row.value["term"]: row.value["kind"] for row in rows}
        assert kinds == {
            "Unicorn Temalı Doğum Günü Balon Seti": "product",
            "Safari": "theme",
            "Ayıcık Temalı": "theme",
            "Doğum Günü": "category",
        }
        assert all(row.concept_key and row.subject == row.value["term"] for row in rows)

    def test_market_extractor_reports_strategy_context_or_nothing(self, harness: Harness) -> None:
        with harness.session() as session:
            strategy = StrategyService(session)
            cluster = strategy.create_cluster(name="Doğum Günü", priority=90)
            strategy.create_keyword(
                phrase="doğum günü partisi", priority=80, topic_cluster_id=cluster.id
            )
            session.commit()
            matched_id = make_document(
                session,
                slug="editoryal",
                title="Doğum günü partisi fikirleri",
                clean_text="Evde doğum günü partisi için özgün öneriler.",
            )
            unmatched_id = make_document(
                session,
                slug="gezi",
                title="İstanbul gezi rehberi",
                clean_text="Şehir gezisi.",
            )
            service = IntelligenceSignalService(session)
            matched = service.extract_for_document(matched_id, capabilities=["market"])
            unmatched = service.extract_for_document(unmatched_id, capabilities=["market"])
            session.commit()
            rows = all_rows(session)

        assert matched.created == 1 and matched.families == (SignalFamily.MARKET,)
        assert unmatched.created == 0 and unmatched.families == ()
        (row,) = rows
        assert row.family is SignalFamily.MARKET
        assert row.value == {
            "clusters": ["Doğum Günü"],
            "keywords": ["doğum günü partisi"],
            "published_at": None,
        }
        assert row.concept_key == "dogum gunu partisi fikirleri"

    def test_competition_extractor_records_title_pattern_and_host(self, harness: Harness) -> None:
        with harness.session() as session:
            document_id = make_document(
                session,
                slug="rakip",
                title="En güzel 1 yaş doğum günü konseptleri",
                clean_text="Rakip yazı gövdesi.",
                url="https://rakip.example.test/yazi/dogum-gunu",
            )
            result = IntelligenceSignalService(session).extract_for_document(
                document_id, capabilities=["competition"]
            )
            session.commit()
            (row,) = all_rows(session)

        assert result.created == 1
        assert row.family is SignalFamily.COMPETITION
        assert row.provider == "competition-extractor/1"
        assert row.value == {
            "title_pattern": "En güzel 1 yaş doğum günü konseptleri",
            "url_host": "rakip.example.test",
            "published_at": None,
        }
        assert row.locale == "tr-TR" and row.market == "TR"
        assert row.normalized_document_id == document_id

    def test_source_capabilities_select_extractors(self, harness: Harness) -> None:
        with harness.session() as session:
            inspiration_only = make_document(
                session,
                slug="ilham",
                title="Parti fikirleri nereden bulunur?",
                clean_text="Parti fikirleri nereden bulunur?",
            )
            competitor = make_document(
                session,
                slug="rakip-site",
                title="Doğum günü süsleme rehberi",
                clean_text="Rehber.",
                capabilities=["competition", "taxonomy"],
            )
            service = IntelligenceSignalService(session)
            nothing = service.extract_for_document(inspiration_only)
            both = service.extract_for_document(competitor)
            session.commit()
            families = {row.family for row in all_rows(session)}

        assert DEFAULT_CAPABILITIES == ("inspiration",)
        assert nothing.created == 0 and nothing.families == ()
        assert set(both.families) == {SignalFamily.COMPETITION, SignalFamily.TAXONOMY}
        assert families == {SignalFamily.COMPETITION, SignalFamily.TAXONOMY}

    def test_capabilities_of_is_defensive(self) -> None:
        class Bare:
            pass

        class Listed:
            capabilities = ["community_need", SignalFamily.MARKET]

        assert capabilities_of(Bare()) == frozenset({"inspiration"})  # type: ignore[arg-type]
        assert capabilities_of(Listed()) == frozenset(  # type: ignore[arg-type]
            {"community_need", "market"}
        )

    def test_reextraction_is_idempotent(self, harness: Harness) -> None:
        with harness.session() as session:
            document_id = make_document(
                session,
                slug="tekrar",
                title="Nişan masası nasıl süslenir?",
                clean_text="Nişan masası nasıl süslenir?",
            )
            service = IntelligenceSignalService(session)
            first = service.extract_for_document(
                document_id, capabilities=["community_need", "competition"]
            )
            session.commit()
            second = service.extract_for_document(
                document_id, capabilities=["community_need", "competition"]
            )
            session.commit()
            rows = all_rows(session)

        assert first.created == 2 and first.updated == 0
        assert second.created == 0 and second.updated == 2
        assert len(rows) == 2
        assert all(row.occurrence_count == 2 for row in rows)
        assert all(row.last_observed_at >= row.first_observed_at for row in rows)
        assert len({row.observation_hash for row in rows}) == 2

    def test_unknown_document_is_an_error(self, harness: Harness) -> None:
        with harness.session() as session:
            with pytest.raises(DocumentNotFoundError):
                IntelligenceSignalService(session).extract_for_document(uuid.uuid4())


class TestBands:
    def test_band_thresholds(self) -> None:
        assert band_for(0, 0) is Band.UNKNOWN
        assert band_for(1, 1) is Band.WEAK
        assert band_for(MODERATE_MIN_OCCURRENCES, 1) is Band.MODERATE
        assert band_for(1, 2) is Band.MODERATE
        assert band_for(STRONG_MIN_OCCURRENCES, 1) is Band.MODERATE
        assert band_for(STRONG_MIN_OCCURRENCES, STRONG_MIN_SOURCES) is Band.STRONG

    def test_bands_are_unknown_without_signals(self, harness: Harness) -> None:
        context = Context()
        with harness.session() as session:
            seed_scored(session, context)
            bands = signal_bands_for_opportunity(session, context.opportunity_id)
        assert set(bands) == set(SignalFamily)
        assert set(bands.values()) == {Band.UNKNOWN}

    def test_bands_use_research_inputs_and_concept_matches(self, harness: Harness) -> None:
        context = Context()
        with harness.session() as session:
            seed_scored(session, context)
            opportunity = session.get(EditorialOpportunity, context.opportunity_id)
            assert opportunity is not None
            service = IntelligenceSignalService(session)
            for document_id in context.document_ids:
                service.extract_for_document(document_id, capabilities=["competition"])
            # An unrelated document whose title names the same concept.
            unrelated = make_document(
                session,
                slug="bagimsiz",
                title=opportunity.topic_summary,
                clean_text="Bağımsız yazı.",
            )
            service.extract_for_document(unrelated, capabilities=["competition"])
            # A document that matches nothing about this opportunity.
            noise = make_document(
                session,
                slug="gurultu",
                title="Kış lastiği değişim zamanı",
                clean_text="Otomobil.",
            )
            service.extract_for_document(noise, capabilities=["competition"])
            session.commit()

            rows = service.signals_for_opportunity(context.opportunity_id)
            bands = signal_bands_for_opportunity(session, context.opportunity_id)
            with pytest.raises(OpportunityNotFoundError):
                service.signals_for_opportunity(uuid.uuid4())

        assert {row.normalized_document_id for row in rows} == {*context.document_ids, unrelated}
        assert bands[SignalFamily.COMPETITION] is Band.MODERATE
        assert bands[SignalFamily.COMMUNITY_NEED] is Band.UNKNOWN
        assert bands[SignalFamily.SEARCH] is Band.UNKNOWN


class TestReadApi:
    def seed(self, harness: Harness) -> uuid.UUID:
        with harness.session() as session:
            community = make_document(
                session,
                slug="api-forum",
                title="Baby shower için ne yapabilirim?",
                clean_text="Baby shower için ne yapabilirim? Nereden pasta bulurum?",
            )
            shop = make_document(
                session,
                slug="api-magaza",
                title="Safari Temalı Balon Seti",
                headings=["Unicorn", "Sepet"],
                clean_text="Mağaza.",
            )
            service = IntelligenceSignalService(session)
            service.extract_for_document(community, capabilities=["community_need"])
            service.extract_for_document(shop, capabilities=["taxonomy"])
            session.commit()
            return community

    def test_signals_endpoint_filters_by_family_and_limit(self, harness: Harness) -> None:
        self.seed(harness)

        response = harness.get("/internal/intelligence/signals?family=community_need&limit=1")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["bounded"] is True and body["limit"] == 1
        assert body["family"] == "community_need"
        assert len(body["items"]) == 1
        item = body["items"][0]
        assert item["family"] == "community_need"
        assert item["provider"] == "community-need-extractor/1"
        assert item["value"]["category"] == "baby shower"
        assert item["occurrence_count"] == 1

        everything = harness.get("/internal/intelligence/signals").json()
        assert {item["family"] for item in everything["items"]} == {
            "community_need",
            "taxonomy",
        }

    def test_signals_endpoint_scopes_to_opportunity(self, harness: Harness) -> None:
        context = Context()
        with harness.session() as session:
            seed_scored(session, context)
            IntelligenceSignalService(session).extract_for_document(
                context.document_ids[1], capabilities=["competition"]
            )
            session.commit()

        response = harness.get(
            f"/internal/intelligence/signals?opportunity_id={context.opportunity_id}"
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["opportunity_id"] == str(context.opportunity_id)
        assert [item["normalized_document_id"] for item in body["items"]] == [
            str(context.document_ids[1])
        ]

        missing = harness.get(f"/internal/intelligence/signals?opportunity_id={uuid.uuid4()}")
        assert missing.status_code == 404

    def test_summary_lists_every_family(self, harness: Harness) -> None:
        self.seed(harness)

        response = harness.get("/internal/intelligence/summary")

        assert response.status_code == 200, response.text
        body = response.json()
        families = {entry["family"]: entry for entry in body["families"]}
        assert set(families) == {family.value for family in SignalFamily}
        assert families["community_need"]["signal_count"] == 2
        assert families["community_need"]["distinct_sources"] == 1
        assert families["community_need"]["last_observed_at"] is not None
        assert families["search"]["signal_count"] == 0
        assert families["search"]["last_observed_at"] is None
        assert body["total_signals"] == sum(entry["signal_count"] for entry in families.values())

    def test_summary_bounded_to_one_intake_run(self, harness: Harness) -> None:
        # Two documents from two sources; only the first was fetched by the
        # run. The run-scoped summary must count that document's signals only,
        # a run without dispatched fetches tallies nothing, and an unknown run
        # is a 404 — never an unbounded fallback.
        from contentos.discovery.models import DiscoveryItem
        from contentos.fetching.snapshots import FetchSnapshot
        from contentos.intake.enums import IntakeEventKind, IntakeRunStatus, IntakeStage
        from contentos.intake.models import IntakeRun
        from contentos.intake.service import IntakeRunService
        from contentos.normalization.models import NormalizedDocument

        community = self.seed(harness)
        with harness.session() as session:
            snapshot = session.get(
                FetchSnapshot, session.get(NormalizedDocument, community).fetch_snapshot_id
            )
            assert snapshot is not None
            item = session.get(DiscoveryItem, snapshot.discovery_item_id)
            assert item is not None
            run = IntakeRun(source_id=item.source_id, status=IntakeRunStatus.RUNNING, policy={})
            session.add(run)
            session.flush()
            IntakeRunService(session).record_event(
                run,
                IntakeStage.FETCH,
                IntakeEventKind.FETCH_ITEM_DISPATCHED,
                {"discovery_item_id": str(item.id)},
            )
            empty_run = IntakeRun(
                source_id=item.source_id, status=IntakeRunStatus.COMPLETED, policy={}
            )
            session.add(empty_run)
            session.commit()
            run_id, empty_run_id = run.id, empty_run.id

        scoped = harness.get(f"/internal/intelligence/summary?run_id={run_id}")
        assert scoped.status_code == 200, scoped.text
        body = scoped.json()
        assert body["run_id"] == str(run_id)
        assert body["run_document_count"] == 1
        families = {entry["family"]: entry for entry in body["families"]}
        assert families["community_need"]["signal_count"] == 2
        assert families["taxonomy"]["signal_count"] == 0
        assert body["total_signals"] == 2

        empty = harness.get(f"/internal/intelligence/summary?run_id={empty_run_id}").json()
        assert empty["run_document_count"] == 0
        assert empty["total_signals"] == 0
        assert all(entry["last_observed_at"] is None for entry in empty["families"])

        unbounded = harness.get("/internal/intelligence/summary").json()
        assert unbounded["run_id"] is None and unbounded["run_document_count"] is None
        assert unbounded["total_signals"] > 2

        assert (
            harness.get(f"/internal/intelligence/summary?run_id={uuid.uuid4()}").status_code == 404
        )
        assert harness.get("/internal/intelligence/summary?run_id=abc").status_code == 422

    def test_rejects_invalid_query(self, harness: Harness) -> None:
        assert harness.get("/internal/intelligence/signals?limit=0").status_code == 422
        assert harness.get("/internal/intelligence/signals?family=weather").status_code == 422

    def test_requires_authentication(self, harness: Harness) -> None:
        harness.auth_token = "0" * 64
        for path in ("/internal/intelligence/signals", "/internal/intelligence/summary"):
            response = harness.get(path)
            assert response.status_code == 401
            assert "error" in response.json()


class TestWorkerHook:
    def test_normalize_task_extracts_after_commit_and_still_dispatches(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pipeline = PipelineHarness()
        try:
            snapshot = committed_success_snapshot(pipeline, "zeka", ARTICLE_HTML)
            seen: list[uuid.UUID] = []

            def record(session: Session, document_id: uuid.UUID) -> None:
                seen.append(document_id)

            monkeypatch.setattr(research_tasks, "_extract_intelligence_signals", record)
            dispatcher = RecordingDispatcher()
            app = pipeline.app(dispatcher)

            result = app.tasks[NORMALIZE_FETCH_TASK].apply(args=[str(snapshot.id)]).get()

            assert result["status"] == "completed"
            assert seen == [uuid.UUID(result["normalized_document_id"])]
            assert dispatcher.calls[0][0] == EVALUATE_DUPLICATE_TASK
        finally:
            pipeline.engine.dispose()

    def test_extraction_failure_never_fails_normalization(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pipeline = PipelineHarness()
        try:
            snapshot = committed_success_snapshot(pipeline, "hata", ARTICLE_HTML)

            def explode(self: Any, document_id: uuid.UUID, **_: Any) -> Any:
                raise RuntimeError("extractor bug")

            monkeypatch.setattr(IntelligenceSignalService, "extract_for_document", explode)
            dispatcher = RecordingDispatcher()
            app = pipeline.app(dispatcher)

            result = app.tasks[NORMALIZE_FETCH_TASK].apply(args=[str(snapshot.id)]).get()

            assert result["status"] == "completed"
            assert result["next_task"] == EVALUATE_DUPLICATE_TASK
            assert pipeline.count(IntelligenceSignal) == 0
        finally:
            pipeline.engine.dispose()

    def test_helper_rolls_back_and_keeps_session_usable(
        self, harness: Harness, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with harness.session() as session:
            document_id = make_document(
                session, slug="yardimci", title="Başlık", clean_text="Metin."
            )

            def explode(self: Any, document_id: uuid.UUID, **_: Any) -> Any:
                session.add(
                    IntelligenceSignal(
                        family=SignalFamily.MARKET,
                        subject="yarım",
                        concept_key="yarim",
                        provider="test/1",
                        value={},
                        first_observed_at=NOW,
                        last_observed_at=NOW,
                        observation_hash="a" * 64,
                    )
                )
                session.flush()
                raise RuntimeError("late failure")

            monkeypatch.setattr(IntelligenceSignalService, "extract_for_document", explode)
            _extract_intelligence_signals(session, document_id)

            assert all_rows(session) == []
            # The session survived the rollback and can serve the next stage.
            assert session.get(EditorialOpportunity, uuid.uuid4()) is None
