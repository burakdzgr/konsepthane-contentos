"""Read-only internal research visibility API tests (SQLite, real sessions)."""

import asyncio
import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from fastapi import FastAPI
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from contentos.api.app import create_app
from contentos.core.config import Environment, LogLevel, Settings
from contentos.db.base import Base
from contentos.discovery.enums import DiscoveryRejectionReason
from contentos.discovery.models import DiscoveryItem
from contentos.discovery.service import DiscoveryService
from contentos.duplicates.service import DuplicateDecisionService
from contentos.fetching.models import (
    FetchOutcome,
    FetchResult,
    RetryClassification,
    RobotsDecision,
)
from contentos.fetching.snapshot_service import FetchSnapshotService
from contentos.normalization.enums import NormalizationFailureCode
from contentos.normalization.service import NormalizationService
from contentos.research.enums import EvidenceType, ExtractionMethod, VerificationStatus
from contentos.research.service import ResearchEvidenceService
from contentos.sources.enums import (
    DiscoveryStrategy,
    SourceKind,
    SourceLifecycleState,
    TrustTier,
)
from contentos.sources.models import Source
from contentos.sources.service import SourceRegistryService

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)

FORBIDDEN_JSON_KEYS = {
    "payload",
    "raw_payload_ref",
    "clean_text",
    "excerpt",
    "statement",
    "database_url",
    "redis_url",
    "secret",
    "selected_headers",
    "redirect_chain",
    "structured_metadata",
    "metadata",
    "signals",
    "thresholds",
    "matches",
}

CLEAN_TEXT_SAMPLE = (
    "İstanbul'da kutlama programı gün boyu sürdü ve tüm detaylar bu uzun metinde anlatılıyor."
)
EVIDENCE_STATEMENT = "Kaynak, içeriğin yazarını 'Ayşe Yılmaz' olarak belirtiyor."


def read_api_settings() -> Settings:
    return Settings(
        environment=Environment.TEST,
        service_name="ContentOS Read API Test",
        application_version="1.0.0-test",
        log_level=LogLevel.INFO,
        api_docs_enabled=False,
        database_url="postgresql+psycopg://contentos:read-api-secret@localhost:5432/contentos_ra",
        redis_broker_url="redis://:read-api-secret@localhost:6379/0",
    )


class Harness:
    """Real SQLAlchemy sessions over shared in-memory SQLite behind the app."""

    def __init__(self) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.app: FastAPI = create_app(settings=read_api_settings())
        self.app.state.db_session_factory = self.session_factory
        from editorial_harness import (
            TEST_OPERATOR_PASSWORD,
            TEST_OPERATOR_USERNAME,
            seed_test_operator,
        )

        with self.session_factory() as seed_session:
            seed_test_operator(seed_session)
        self._credentials = (TEST_OPERATOR_USERNAME, TEST_OPERATOR_PASSWORD)
        self.auth_token: str | None = None

    def get(self, path: str, params: dict[str, Any] | None = None) -> httpx.Response:
        async def run() -> httpx.Response:
            transport = httpx.ASGITransport(app=self.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://read") as client:
                if self.auth_token is None and not path.startswith("/internal/auth/"):
                    username, password = self._credentials
                    login = await client.post(
                        "/internal/auth/login",
                        json={"username": username, "password": password},
                    )
                    assert login.status_code == 200, login.text
                    self.auth_token = login.json()["token"]
                headers = (
                    {"Authorization": f"Bearer {self.auth_token}"}
                    if self.auth_token is not None
                    else {}
                )
                return await client.get(path, params=params, headers=headers)

        return asyncio.run(run())

    def session(self) -> Session:
        return self.session_factory()


def make_source(
    session: Session,
    slug: str,
    *,
    kind: SourceKind = SourceKind.MANUAL,
    strategy: DiscoveryStrategy = DiscoveryStrategy.MANUAL,
    lifecycle_state: SourceLifecycleState = SourceLifecycleState.ACTIVE,
    name: str | None = None,
    trust_tier: TrustTier = TrustTier.GENERAL,
) -> Source:
    source = SourceRegistryService(session).register_source(
        slug=slug,
        name=name or f"Kaynak {slug}",
        kind=kind,
        base_url=f"https://{slug}.example.test/",
        trust_tier=trust_tier,
        discovery_strategy=strategy,
    )
    if lifecycle_state is not SourceLifecycleState.ACTIVE:
        source.lifecycle_state = lifecycle_state
    session.commit()
    return source


def make_item(
    session: Session,
    source: Source,
    path: str,
    *,
    accepted: bool = True,
    rejected: bool = False,
) -> DiscoveryItem:
    service = DiscoveryService(session)
    item = service.discover_manual(source.id, f"https://{source.slug}.example.test/{path}")
    if rejected:
        service.reject_item(item.id, DiscoveryRejectionReason.OUT_OF_SCOPE, note="test reject")
    elif accepted:
        service.accept_item(item.id)
    session.commit()
    return item


def success_result(url: str, body: bytes, *, fetched_at: datetime = NOW) -> FetchResult:
    return FetchResult(
        requested_url=url,
        outcome=FetchOutcome.SUCCESS,
        retry=RetryClassification.NOT_APPLICABLE,
        robots_decision=RobotsDecision.ALLOWED,
        fetched_at=fetched_at,
        duration_ms=3.0,
        final_url=url,
        status_code=200,
        content_type="text/html; charset=utf-8",
        body=body,
    )


def failure_result(
    url: str,
    *,
    outcome: FetchOutcome = FetchOutcome.TIMEOUT,
    retry: RetryClassification = RetryClassification.RETRYABLE,
    fetched_at: datetime = NOW,
) -> FetchResult:
    return FetchResult(
        requested_url=url,
        outcome=outcome,
        retry=retry,
        robots_decision=RobotsDecision.ALLOWED,
        fetched_at=fetched_at,
        duration_ms=3.0,
        failure_detail=outcome.value,
    )


def record_success_snapshot(
    session: Session,
    item: DiscoveryItem,
    body: bytes,
    *,
    fetched_at: datetime = NOW,
) -> uuid.UUID:
    ref = f"memory:sha256:{hashlib.sha256(body).hexdigest()}"
    snapshot = FetchSnapshotService(session).record_fetch_result(
        item.id,
        success_result(item.canonical_url, body, fetched_at=fetched_at),
        raw_payload_ref=ref,
    )
    session.commit()
    return snapshot.id


def record_failed_snapshot(
    session: Session,
    item: DiscoveryItem,
    *,
    outcome: FetchOutcome = FetchOutcome.TIMEOUT,
    retry: RetryClassification = RetryClassification.RETRYABLE,
    fetched_at: datetime = NOW,
) -> uuid.UUID:
    snapshot = FetchSnapshotService(session).record_fetch_result(
        item.id,
        failure_result(item.canonical_url, outcome=outcome, retry=retry, fetched_at=fetched_at),
    )
    session.commit()
    return snapshot.id


def record_normalized(
    session: Session,
    snapshot_id: uuid.UUID,
    *,
    clean_text: str = CLEAN_TEXT_SAMPLE,
    extractor_version: str = "1",
    normalized_at: datetime | None = None,
    title: str | None = "İstanbul Rehberi",
    author_name: str | None = "Ayşe Yılmaz",
) -> uuid.UUID:
    document = NormalizationService(session).record_success(
        snapshot_id,
        extractor_name="html-basic",
        extractor_version=extractor_version,
        clean_text=clean_text,
        title=title,
        author_name=author_name,
    )
    if normalized_at is not None:
        document.normalized_at = normalized_at
    session.commit()
    return document.id


def record_normalization_failure(session: Session, snapshot_id: uuid.UUID) -> uuid.UUID:
    document = NormalizationService(session).record_failure(
        snapshot_id,
        extractor_name="html-basic",
        extractor_version="1",
        failure_code=NormalizationFailureCode.UNSUPPORTED_CONTENT,
    )
    session.commit()
    return document.id


def record_duplicate_decision(
    session: Session, document_id: uuid.UUID, *, evaluated_at: datetime | None = None
) -> Any:
    decision = DuplicateDecisionService(session).evaluate_and_record(document_id)
    if evaluated_at is not None:
        decision.evaluated_at = evaluated_at
    session.commit()
    return decision


def record_evidence(
    session: Session,
    document_id: uuid.UUID,
    *,
    statement: str = EVIDENCE_STATEMENT,
    evidence_type: EvidenceType = EvidenceType.OBSERVATION,
    extracted_at: datetime | None = None,
) -> uuid.UUID:
    evidence = ResearchEvidenceService(session).record_evidence(
        document_id,
        evidence_type=evidence_type,
        statement=statement,
        extraction_method=ExtractionMethod.MACHINE,
        source_locator="structured_metadata.author",
        verification_status=VerificationStatus.UNVERIFIED,
        extracted_at=extracted_at,
    )
    session.commit()
    return evidence.id


def full_chain(
    session: Session,
    source: Source,
    path: str,
    *,
    body: bytes,
    clean_text: str,
    fetched_at: datetime = NOW,
) -> tuple[DiscoveryItem, uuid.UUID, uuid.UUID]:
    """Item -> successful snapshot -> normalized doc -> decision -> evidence."""
    item = make_item(session, source, path)
    snapshot_id = record_success_snapshot(session, item, body, fetched_at=fetched_at)
    document_id = record_normalized(session, snapshot_id, clean_text=clean_text)
    record_duplicate_decision(session, document_id)
    record_evidence(session, document_id)
    return item, snapshot_id, document_id


def walk_json(node: Any) -> tuple[set[str], list[str]]:
    """Collect every key and every string value from a JSON tree."""
    keys: set[str] = set()
    strings: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            keys.add(key)
            child_keys, child_strings = walk_json(value)
            keys |= child_keys
            strings.extend(child_strings)
    elif isinstance(node, list):
        for value in node:
            child_keys, child_strings = walk_json(value)
            keys |= child_keys
            strings.extend(child_strings)
    elif isinstance(node, str):
        strings.append(node)
    return keys, strings


class TestSourcesEndpoint:
    def test_empty_registry_returns_empty_page(self) -> None:
        harness = Harness()
        response = harness.get("/internal/research/sources")

        assert response.status_code == 200
        assert response.json() == {"items": [], "total": 0, "limit": 50, "offset": 0}

    def test_source_fields_and_aggregate_counts(self) -> None:
        harness = Harness()
        with harness.session() as session:
            busy = make_source(session, "yogun-kaynak", name="Yoğun Kaynak")
            make_source(session, "bos-kaynak", name="Boş Kaynak")
            make_item(session, busy, "yeni", accepted=False)
            make_item(session, busy, "kabul")
            make_item(session, busy, "ret", rejected=True)
            fetched = make_item(session, busy, "indirildi")
            record_success_snapshot(session, fetched, b"<html><body>govde</body></html>")
            failed = make_item(session, busy, "hata")
            record_failed_snapshot(
                session, failed, retry=RetryClassification.TERMINAL, outcome=FetchOutcome.HTTP_ERROR
            )

        payload = harness.get("/internal/research/sources").json()
        by_slug = {item["slug"]: item for item in payload["items"]}
        assert payload["total"] == 2

        row = by_slug["yogun-kaynak"]
        assert row["name"] == "Yoğun Kaynak"
        assert row["kind"] == "manual"
        assert row["locale"] == "tr-TR"
        assert row["market"] == "TR"
        assert row["lifecycle_state"] == "active"
        assert row["trust_tier"] == "general"
        assert row["discovery_strategy"] == "manual"
        # Editorial purpose defaults: inspiration / ["inspiration"].
        assert row["primary_role"] == "inspiration"
        assert row["capabilities"] == ["inspiration"]
        # Registration normalizes the base URL (trailing slash stripped).
        assert row["base_url"] == "https://yogun-kaynak.example.test"
        assert row["created_at"] and row["updated_at"]
        assert row["total_discovery_items"] == 5
        assert row["discovered_count"] == 1
        assert row["accepted_count"] == 1
        assert row["fetched_count"] == 1
        assert row["fetch_failed_count"] == 1
        assert row["rejected_count"] == 1

        empty = by_slug["bos-kaynak"]
        assert empty["total_discovery_items"] == 0
        assert empty["discovered_count"] == 0
        assert empty["rejected_count"] == 0

    def test_filters_and_search(self) -> None:
        harness = Harness()
        with harness.session() as session:
            make_source(
                session,
                "aktif-besleme",
                kind=SourceKind.RSS_FEED,
                strategy=DiscoveryStrategy.FEED,
            )
            make_source(session, "durmus", lifecycle_state=SourceLifecycleState.PAUSED)
            make_source(session, "gezi-notlari", name="Gezi Notları")

        paused = harness.get(
            "/internal/research/sources", params={"lifecycle_state": "paused"}
        ).json()
        assert [row["slug"] for row in paused["items"]] == ["durmus"]
        assert paused["total"] == 1

        feeds = harness.get(
            "/internal/research/sources",
            params={"kind": "rss_feed", "discovery_strategy": "feed"},
        ).json()
        assert [row["slug"] for row in feeds["items"]] == ["aktif-besleme"]

        by_name = harness.get("/internal/research/sources", params={"search": "gezi"}).json()
        assert [row["slug"] for row in by_name["items"]] == ["gezi-notlari"]

        no_match = harness.get("/internal/research/sources", params={"search": "yok-boyle"}).json()
        assert no_match["items"] == []
        assert no_match["total"] == 0

    def test_deterministic_ordering_and_pagination(self) -> None:
        harness = Harness()
        with harness.session() as session:
            for index, slug in enumerate(["eski", "orta", "yeni"]):
                source = make_source(session, slug)
                source.created_at = NOW + timedelta(minutes=index)
                source.updated_at = NOW + timedelta(minutes=index)
            session.commit()

        page = harness.get("/internal/research/sources").json()
        assert [row["slug"] for row in page["items"]] == ["yeni", "orta", "eski"]

        second = harness.get("/internal/research/sources", params={"limit": 1, "offset": 1}).json()
        assert [row["slug"] for row in second["items"]] == ["orta"]
        assert second["total"] == 3
        assert second["limit"] == 1
        assert second["offset"] == 1

    def test_ordering_tie_break_is_stable_id(self) -> None:
        harness = Harness()
        with harness.session() as session:
            for slug in ["ayni-bir", "ayni-iki", "ayni-uc"]:
                source = make_source(session, slug)
                source.created_at = NOW
                source.updated_at = NOW
            session.commit()
            expected = [
                source.slug
                for source in session.execute(select(Source).order_by(Source.id)).scalars()
            ]

        page = harness.get("/internal/research/sources").json()
        assert [row["slug"] for row in page["items"]] == expected

    def test_limit_above_maximum_returns_validation_envelope(self) -> None:
        harness = Harness()
        response = harness.get("/internal/research/sources", params={"limit": 101})

        assert response.status_code == 422
        body = response.json()
        assert body["error"]["code"] == "validation_error"
        assert "request_id" in body


class TestPipelineListEndpoint:
    def test_discovery_only_item_has_null_projections(self) -> None:
        harness = Harness()
        with harness.session() as session:
            source = make_source(session, "sadece-kesif")
            item = make_item(session, source, "aday", accepted=False)

        payload = harness.get("/internal/research/discovery-items").json()
        assert payload["total"] == 1
        row = payload["items"][0]
        assert row["id"] == str(item.id)
        assert row["source_slug"] == "sadece-kesif"
        assert row["source_name"] == "Kaynak sadece-kesif"
        assert row["canonical_url"] == "https://sadece-kesif.example.test/aday"
        assert row["discovery_method"] == "manual"
        assert row["lifecycle_state"] == "discovered"
        assert row["rejection_reason"] is None
        assert row["fetch_snapshot_id"] is None
        assert row["fetch_outcome"] is None
        assert row["normalized_document_id"] is None
        assert row["normalization_status"] is None
        assert row["duplicate_decision_id"] is None
        assert row["duplicate_outcome"] is None
        assert row["evidence_count"] == 0
        assert row["latest_evidence_at"] is None

    def test_accepted_and_rejected_states_project_truthfully(self) -> None:
        harness = Harness()
        with harness.session() as session:
            source = make_source(session, "durumlar")
            make_item(session, source, "kabul")
            make_item(session, source, "ret", rejected=True)

        payload = harness.get("/internal/research/discovery-items").json()
        by_state = {row["lifecycle_state"]: row for row in payload["items"]}
        assert by_state["accepted"]["fetch_outcome"] is None
        assert by_state["rejected"]["rejection_reason"] == "out_of_scope"

    def test_successful_and_failed_fetch_projections(self) -> None:
        harness = Harness()
        with harness.session() as session:
            source = make_source(session, "indirme")
            ok_item = make_item(session, source, "basarili")
            snapshot_id = record_success_snapshot(session, ok_item, b"<html>icerik</html>")
            failed_item = make_item(session, source, "zaman-asimi")
            record_failed_snapshot(session, failed_item)

        payload = harness.get("/internal/research/discovery-items").json()
        rows = {row["lifecycle_state"]: row for row in payload["items"]}

        ok_row = rows["fetched"]
        assert ok_row["fetch_snapshot_id"] == str(snapshot_id)
        assert ok_row["fetch_outcome"] == "success"
        assert ok_row["status_code"] == 200
        assert ok_row["retry_classification"] == "not_applicable"
        assert ok_row["fetched_at"] is not None

        failed_row = rows["fetch_failed"]
        assert failed_row["fetch_outcome"] == "timeout"
        assert failed_row["status_code"] is None
        assert failed_row["retry_classification"] == "retryable"

    def test_latest_fetch_projection_after_retry_success(self) -> None:
        harness = Harness()
        with harness.session() as session:
            source = make_source(session, "tekrar")
            item = make_item(session, source, "deneme")
            record_failed_snapshot(session, item, fetched_at=NOW)
            DiscoveryService(session).requeue_fetch(item.id, reason="manual test requeue")
            session.commit()
            success_id = record_success_snapshot(
                session, item, b"<html>ikinci</html>", fetched_at=NOW + timedelta(minutes=5)
            )

        row = harness.get("/internal/research/discovery-items").json()["items"][0]
        assert row["lifecycle_state"] == "fetched"
        assert row["fetch_snapshot_id"] == str(success_id)
        assert row["fetch_outcome"] == "success"

    def test_normalization_success_and_failure_projections(self) -> None:
        harness = Harness()
        with harness.session() as session:
            source = make_source(session, "normalize")
            ok_item = make_item(session, source, "duz")
            ok_snapshot = record_success_snapshot(session, ok_item, b"<html>bir</html>")
            document_id = record_normalized(session, ok_snapshot)
            bad_item = make_item(session, source, "bozuk")
            bad_snapshot = record_success_snapshot(session, bad_item, b"%PDF-1.7")
            record_normalization_failure(session, bad_snapshot)

        payload = harness.get("/internal/research/discovery-items").json()
        rows = {row["canonical_url"].rsplit("/", 1)[-1]: row for row in payload["items"]}

        assert rows["duz"]["normalized_document_id"] == str(document_id)
        assert rows["duz"]["normalization_status"] == "succeeded"
        assert rows["duz"]["normalization_failure_code"] is None
        assert rows["duz"]["normalized_at"] is not None
        assert rows["bozuk"]["normalization_status"] == "failed"
        assert rows["bozuk"]["normalization_failure_code"] == "unsupported_content"

    def test_latest_document_owns_the_duplicate_projection(self) -> None:
        """A decision for an older normalization version is never shown as latest."""
        harness = Harness()
        with harness.session() as session:
            source = make_source(session, "surumler")
            item = make_item(session, source, "konu")
            snapshot_id = record_success_snapshot(session, item, b"<html>surumlu</html>")
            old_document = record_normalized(
                session, snapshot_id, extractor_version="1", normalized_at=NOW
            )
            old_decision = record_duplicate_decision(session, old_document)
            new_document = record_normalized(
                session,
                snapshot_id,
                extractor_version="2",
                normalized_at=NOW + timedelta(minutes=1),
            )
            record_evidence(session, old_document)

        row = harness.get("/internal/research/discovery-items").json()["items"][0]
        assert row["normalized_document_id"] == str(new_document)
        # The old document's decision and evidence must not leak onto the new one.
        assert row["duplicate_decision_id"] != str(old_decision.id)
        assert row["duplicate_decision_id"] is None
        assert row["duplicate_outcome"] is None
        assert row["evidence_count"] == 0
        assert row["latest_evidence_at"] is None

    def test_unique_and_duplicate_outcomes_with_evidence_counts(self) -> None:
        harness = Harness()
        with harness.session() as session:
            source_a = make_source(session, "ozgun")
            source_b = make_source(session, "kopya")
            item_a, _, document_a = full_chain(
                session,
                source_a,
                "haber",
                body=b"<html>ayni govde</html>",
                clean_text="Ayni metin.",
            )
            record_evidence(
                session,
                document_a,
                statement="Kaynak, yayın tarihini belirtiyor.",
                extracted_at=NOW + timedelta(minutes=2),
            )
            item_b = make_item(session, source_b, "haber-kopya")
            snapshot_b = record_success_snapshot(session, item_b, b"<html>ayni govde 2</html>")
            document_b = record_normalized(session, snapshot_b, clean_text="Ayni metin.")
            decision_b = record_duplicate_decision(session, document_b)

        payload = harness.get("/internal/research/discovery-items").json()
        rows = {row["source_slug"]: row for row in payload["items"]}

        assert rows["ozgun"]["duplicate_outcome"] == "unique"
        assert rows["ozgun"]["evidence_count"] == 2
        assert rows["ozgun"]["latest_evidence_at"] is not None
        assert rows["kopya"]["duplicate_outcome"] == "duplicate"
        assert rows["kopya"]["duplicate_decision_id"] == str(decision_b.id)
        assert rows["kopya"]["evidence_count"] == 0
        assert str(item_a.id) != str(item_b.id)

    def test_filters_cover_every_supported_dimension(self) -> None:
        harness = Harness()
        with harness.session() as session:
            source_a = make_source(session, "filtre-a")
            source_b = make_source(session, "filtre-b")
            full_chain(
                session,
                source_a,
                "tam-zincir",
                body=b"<html>zincir</html>",
                clean_text="Zincir metni burada.",
            )
            failed_item = make_item(session, source_b, "hatali")
            record_failed_snapshot(session, failed_item)
            make_item(session, source_b, "bekleyen", accepted=False)

        base = "/internal/research/discovery-items"
        assert harness.get(base).json()["total"] == 3

        by_source = harness.get(base, params={"source_id": str(source_a.id)}).json()
        assert [row["source_slug"] for row in by_source["items"]] == ["filtre-a"]

        by_state = harness.get(base, params={"lifecycle_state": "discovered"}).json()
        assert [row["lifecycle_state"] for row in by_state["items"]] == ["discovered"]

        by_method = harness.get(base, params={"discovery_method": "manual"}).json()
        assert by_method["total"] == 3

        by_outcome = harness.get(base, params={"fetch_outcome": "timeout"}).json()
        assert [row["fetch_outcome"] for row in by_outcome["items"]] == ["timeout"]

        by_norm = harness.get(base, params={"normalization_status": "succeeded"}).json()
        assert [row["source_slug"] for row in by_norm["items"]] == ["filtre-a"]

        by_dup = harness.get(base, params={"duplicate_outcome": "unique"}).json()
        assert [row["source_slug"] for row in by_dup["items"]] == ["filtre-a"]

        with_evidence = harness.get(base, params={"has_evidence": "true"}).json()
        assert [row["source_slug"] for row in with_evidence["items"]] == ["filtre-a"]

        without_evidence = harness.get(base, params={"has_evidence": "false"}).json()
        assert without_evidence["total"] == 2

        by_url = harness.get(base, params={"url_contains": "tam-zincir"}).json()
        assert [row["canonical_url"] for row in by_url["items"]] == [
            "https://filtre-a.example.test/tam-zincir"
        ]

    def test_ordering_and_pagination_are_deterministic(self) -> None:
        harness = Harness()
        with harness.session() as session:
            source = make_source(session, "sirali")
            for index, path in enumerate(["birinci", "ikinci", "ucuncu"]):
                item = make_item(session, source, path, accepted=False)
                item.discovered_at = NOW + timedelta(minutes=index)
                item.last_seen_at = NOW + timedelta(minutes=index)
            session.commit()

        base = "/internal/research/discovery-items"
        page = harness.get(base).json()
        paths = [row["canonical_url"].rsplit("/", 1)[-1] for row in page["items"]]
        assert paths == ["ucuncu", "ikinci", "birinci"]

        second = harness.get(base, params={"limit": 1, "offset": 1}).json()
        assert [row["canonical_url"].rsplit("/", 1)[-1] for row in second["items"]] == ["ikinci"]
        assert second["total"] == 3

    def test_filtered_pagination_reports_filtered_total(self) -> None:
        harness = Harness()
        with harness.session() as session:
            source = make_source(session, "filtreli-sayfa")
            for index in range(3):
                item = make_item(session, source, f"aday-{index}", accepted=False)
                item.last_seen_at = NOW + timedelta(minutes=index)
            make_item(session, source, "kabul-edilen")
            session.commit()

        page = harness.get(
            "/internal/research/discovery-items",
            params={"lifecycle_state": "discovered", "limit": 2, "offset": 0},
        ).json()
        assert page["total"] == 3
        assert len(page["items"]) == 2


class TestPipelineDetailEndpoint:
    def test_complete_pipeline_detail(self) -> None:
        harness = Harness()
        with harness.session() as session:
            source = make_source(session, "detay", name="Detay Kaynağı")
            item, snapshot_id, document_id = full_chain(
                session,
                source,
                "tam-detay",
                body=b"<html>detay govdesi</html>",
                clean_text=CLEAN_TEXT_SAMPLE,
            )

        response = harness.get(f"/internal/research/discovery-items/{item.id}")
        assert response.status_code == 200
        payload = response.json()

        assert payload["source"]["slug"] == "detay"
        assert payload["source"]["name"] == "Detay Kaynağı"
        assert payload["source"]["lifecycle_state"] == "active"

        discovery = payload["discovery_item"]
        assert discovery["id"] == str(item.id)
        assert discovery["canonical_url"] == "https://detay.example.test/tam-detay"
        assert discovery["discovered_url"] == "https://detay.example.test/tam-detay"
        assert discovery["lifecycle_state"] == "fetched"

        assert payload["total_fetch_attempts"] == 1
        assert payload["fetch_attempts_truncated"] is False
        attempt = payload["fetch_attempts"][0]
        assert attempt["id"] == str(snapshot_id)
        assert attempt["fetch_outcome"] == "success"
        assert attempt["status_code"] == 200
        assert attempt["content_type"] == "text/html; charset=utf-8"
        assert attempt["body_size_bytes"] == len(b"<html>detay govdesi</html>")
        assert attempt["robots_decision"] == "allowed"
        assert attempt["retry_classification"] == "not_applicable"
        assert attempt["failure_detail"] is None

        assert payload["total_normalization_attempts"] == 1
        normalization = payload["normalization_attempts"][0]
        assert normalization["id"] == str(document_id)
        assert normalization["fetch_snapshot_id"] == str(snapshot_id)
        assert normalization["normalization_status"] == "succeeded"
        assert normalization["extractor_name"] == "html-basic"
        assert normalization["title"] == "İstanbul Rehberi"
        assert normalization["author_name"] == "Ayşe Yılmaz"
        assert "clean_text" not in normalization

        assert payload["total_duplicate_decisions"] == 1
        decision = payload["duplicate_decisions"][0]
        assert decision["normalized_document_id"] == str(document_id)
        assert decision["engine_name"] == "duplicate-engine"
        assert decision["decision"] == "unique"
        assert isinstance(decision["rationale_codes"], list)
        assert decision["match_count"] == 0

        evidence = payload["evidence"]
        assert evidence["total"] == 1
        assert evidence["by_verification_status"] == {"unverified": 1}
        assert evidence["by_evidence_type"] == {"observation": 1}
        assert evidence["latest_extracted_at"] is not None

    def test_multiple_fetch_attempts_newest_first_and_bounded(self) -> None:
        harness = Harness()
        with harness.session() as session:
            source = make_source(session, "cok-deneme")
            item = make_item(session, source, "inatci")
            service = DiscoveryService(session)
            for attempt in range(22):
                record_failed_snapshot(session, item, fetched_at=NOW + timedelta(minutes=attempt))
                service.requeue_fetch(item.id, reason="test retry")
                session.commit()

        payload = harness.get(f"/internal/research/discovery-items/{item.id}").json()
        assert payload["total_fetch_attempts"] == 22
        assert len(payload["fetch_attempts"]) == 20
        assert payload["fetch_attempts_truncated"] is True
        fetched_ats = [attempt["fetched_at"] for attempt in payload["fetch_attempts"]]
        assert fetched_ats == sorted(fetched_ats, reverse=True)

    def test_multiple_normalization_versions_and_linked_decisions(self) -> None:
        harness = Harness()
        with harness.session() as session:
            source = make_source(session, "iki-surum")
            item = make_item(session, source, "konu")
            snapshot_id = record_success_snapshot(session, item, b"<html>iki surum</html>")
            first_document = record_normalized(
                session, snapshot_id, extractor_version="1", normalized_at=NOW
            )
            first_decision = record_duplicate_decision(session, first_document, evaluated_at=NOW)
            second_document = record_normalized(
                session,
                snapshot_id,
                extractor_version="2",
                normalized_at=NOW + timedelta(minutes=1),
            )
            second_decision = record_duplicate_decision(
                session, second_document, evaluated_at=NOW + timedelta(minutes=1)
            )

        payload = harness.get(f"/internal/research/discovery-items/{item.id}").json()
        assert payload["total_normalization_attempts"] == 2
        assert [row["id"] for row in payload["normalization_attempts"]] == [
            str(second_document),
            str(first_document),
        ]
        assert [row["id"] for row in payload["duplicate_decisions"]] == [
            str(second_decision.id),
            str(first_decision.id),
        ]
        # Each decision stays linked to its own document.
        assert payload["duplicate_decisions"][0]["normalized_document_id"] == str(second_document)
        assert payload["duplicate_decisions"][1]["normalized_document_id"] == str(first_document)

    def test_detail_never_includes_other_items_history(self) -> None:
        harness = Harness()
        with harness.session() as session:
            source = make_source(session, "ayrik")
            item_a, snapshot_a, _ = full_chain(
                session, source, "bir", body=b"<html>bir</html>", clean_text="Bir metni."
            )
            item_b, snapshot_b, _ = full_chain(
                session, source, "iki", body=b"<html>iki</html>", clean_text="Iki metni."
            )

        payload = harness.get(f"/internal/research/discovery-items/{item_a.id}").json()
        assert [row["id"] for row in payload["fetch_attempts"]] == [str(snapshot_a)]
        assert payload["evidence"]["total"] == 1
        assert str(snapshot_b) not in str(payload)

    def test_missing_item_returns_404_envelope(self) -> None:
        harness = Harness()
        response = harness.get(f"/internal/research/discovery-items/{uuid.uuid4()}")

        assert response.status_code == 404
        body = response.json()
        assert body["error"]["code"] == "not_found"
        assert "request_id" in body

    def test_invalid_uuid_returns_validation_envelope(self) -> None:
        harness = Harness()
        response = harness.get("/internal/research/discovery-items/not-a-uuid")

        assert response.status_code == 422
        body = response.json()
        assert body["error"]["code"] == "validation_error"


class TestReadOnlySurfaceAndSafety:
    def test_router_exposes_get_only(self) -> None:
        harness = Harness()
        schema = harness.app.openapi()
        research_paths = {
            path: operations
            for path, operations in schema["paths"].items()
            if path.startswith("/internal/research")
        }
        # The three visibility endpoints must keep their GET operation.
        # (Task 19 added explicit POST-only control endpoints, pinned in
        # tests/unit/test_research_control_api.py; POST /sources is the one
        # intentional overlap on a shared path.)
        for read_path in (
            "/internal/research/sources",
            "/internal/research/discovery-items",
            "/internal/research/discovery-items/{discovery_item_id}",
        ):
            assert "get" in research_paths[read_path], read_path
        for path, operations in research_paths.items():
            assert set(operations) <= {"get", "post"}, path

    def test_mutating_methods_are_rejected_on_read_paths(self) -> None:
        harness = Harness()

        async def run() -> tuple[int, int]:
            transport = httpx.ASGITransport(app=harness.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://read") as client:
                # The list/detail visibility paths accept no mutation verb.
                post = await client.post("/internal/research/discovery-items", json={})
                delete = await client.delete("/internal/research/discovery-items")
                return post.status_code, delete.status_code

        post_status, delete_status = asyncio.run(run())
        assert post_status == 405
        assert delete_status == 405

    def test_no_forbidden_fields_or_content_in_any_response(self) -> None:
        harness = Harness()
        with harness.session() as session:
            source = make_source(session, "guvenlik")
            item, _, document_id = full_chain(
                session,
                source,
                "sizinti-testi",
                body=b"<html>gizli govde baytlari</html>",
                clean_text=CLEAN_TEXT_SAMPLE,
            )
            record_evidence(
                session,
                document_id,
                statement="Kaynak, yayın tarihini '2026-08-30' olarak belirtiyor.",
                evidence_type=EvidenceType.SOURCE_ASSERTION,
            )

        responses = [
            harness.get("/internal/research/sources").json(),
            harness.get("/internal/research/discovery-items").json(),
            harness.get(f"/internal/research/discovery-items/{item.id}").json(),
        ]
        for payload in responses:
            keys, strings = walk_json(payload)
            leaked_keys = keys & FORBIDDEN_JSON_KEYS
            assert leaked_keys == set(), f"forbidden keys leaked: {leaked_keys}"
            joined = "\n".join(strings)
            assert CLEAN_TEXT_SAMPLE not in joined
            assert EVIDENCE_STATEMENT not in joined
            assert "belirtiyor" not in joined
            assert "memory:sha256:" not in joined
            assert "postgres:sha256:" not in joined
            assert "read-api-secret" not in joined
            assert "gizli govde" not in joined
