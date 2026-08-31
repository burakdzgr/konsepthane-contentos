"""Tests for the DiscoveryItem persistence foundation."""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from contentos.core.urls import InvalidUrlError, canonical_url_hash
from contentos.db.base import Base
from contentos.discovery.enums import (
    DiscoveryLifecycleState,
    DiscoveryMethod,
    DiscoveryRejectionReason,
)
from contentos.discovery.models import DiscoveryItem
from contentos.discovery.repository import DiscoveryItemRepository
from contentos.discovery.service import (
    DiscoveryError,
    DiscoveryItemNotFoundError,
    DiscoveryService,
    InvalidDiscoveryTransitionError,
    SourceNotEligibleForDiscoveryError,
)
from contentos.sources.enums import SourceKind, SourceLifecycleState, TrustTier
from contentos.sources.models import Source
from contentos.sources.service import SourceNotFoundError, SourceRegistryService


@pytest.fixture()
def session() -> Iterator[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db_session:
        yield db_session
    engine.dispose()


def make_source(session: Session, slug: str = "manuel-kaynak") -> Source:
    return SourceRegistryService(session).register_source(
        slug=slug,
        name=f"Kaynak {slug}",
        kind=SourceKind.MANUAL,
        base_url=f"https://{slug}.example",
        trust_tier=TrustTier.GENERAL,
    )


DEFAULT_URL = "https://example.com/haber/yeni-konu?b=2&a=1"
CANONICAL_URL = "https://example.com/haber/yeni-konu?a=1&b=2"


class TestEnumContracts:
    def test_persistent_enum_values_are_stable(self) -> None:
        assert [s.value for s in DiscoveryLifecycleState] == [
            "discovered",
            "accepted",
            "rejected",
            "fetched",
            "fetch_failed",
        ]
        assert [m.value for m in DiscoveryMethod] == [
            "manual",
            "feed",
            "sitemap",
            "provider",
            "search",
        ]
        assert [r.value for r in DiscoveryRejectionReason] == [
            "out_of_scope",
            "duplicate_url",
            "source_not_active",
            "policy",
            "invalid_url",
            "unsupported_scheme",
        ]


class TestManualAdmission:
    def test_creates_item_with_canonical_identity(self, session: Session) -> None:
        source = make_source(session)
        service = DiscoveryService(session)

        item = service.discover_manual(
            source.id,
            DEFAULT_URL,
            title_hint="Yeni Konu",
            snippet_hint="Kısa özet",
        )

        assert item.canonical_url == CANONICAL_URL
        assert item.url_hash == canonical_url_hash(CANONICAL_URL)
        assert item.url_canonicalization_version == 1
        assert item.discovered_url == DEFAULT_URL
        assert item.discovery_method is DiscoveryMethod.MANUAL
        assert item.lifecycle_state is DiscoveryLifecycleState.DISCOVERED
        assert item.locale == source.locale
        assert item.title_hint == "Yeni Konu"
        assert item.rejection_reason is None

    def test_locale_override_is_respected(self, session: Session) -> None:
        source = make_source(session)

        item = DiscoveryService(session).discover_manual(source.id, DEFAULT_URL, locale="en-US")

        assert item.locale == "en-US"

    @pytest.mark.parametrize(
        "variant",
        [
            "https://example.com/haber/yeni-konu?a=1&b=2#yorumlar",
            "HTTPS://EXAMPLE.com:443/haber/yeni-konu?b=2&a=1",
            "https://example.com/haber/yeni-konu/?a=1&utm_source=x&b=2",
            "https://example.com/haber/yeni-konu?b=2&a=1&fbclid=zzz",
        ],
    )
    def test_canonical_equivalents_dedupe_to_one_row(self, session: Session, variant: str) -> None:
        source = make_source(session)
        service = DiscoveryService(session)

        first = service.discover_manual(source.id, DEFAULT_URL)
        second = service.discover_manual(source.id, variant)

        assert second.id == first.id
        count = session.execute(select(func.count()).select_from(DiscoveryItem)).scalar_one()
        assert count == 1

    def test_same_canonical_url_under_different_source_is_allowed(self, session: Session) -> None:
        first_source = make_source(session, "kaynak-bir")
        second_source = make_source(session, "kaynak-iki")
        service = DiscoveryService(session)

        first = service.discover_manual(first_source.id, DEFAULT_URL)
        second = service.discover_manual(second_source.id, DEFAULT_URL)

        assert first.id != second.id
        assert first.url_hash == second.url_hash

    def test_invalid_url_raises_typed_domain_error(self, session: Session) -> None:
        source = make_source(session)

        with pytest.raises(InvalidUrlError):
            DiscoveryService(session).discover_manual(source.id, "ftp://example.com/x")

    def test_missing_source_raises_not_found(self, session: Session) -> None:
        with pytest.raises(SourceNotFoundError):
            DiscoveryService(session).discover_manual(uuid.uuid4(), DEFAULT_URL)

    @pytest.mark.parametrize(
        ("target_state", "reason"),
        [
            (SourceLifecycleState.BLOCKED, "policy prohibition"),
            (SourceLifecycleState.PAUSED, "manual hold"),
            (SourceLifecycleState.DISABLED, "seasonal off"),
        ],
    )
    def test_only_active_sources_admit_discovery(
        self, session: Session, target_state: SourceLifecycleState, reason: str
    ) -> None:
        source = make_source(session)
        SourceRegistryService(session).transition_source_state(
            source.id, target_state, reason=reason
        )

        with pytest.raises(SourceNotEligibleForDiscoveryError):
            DiscoveryService(session).discover_manual(source.id, DEFAULT_URL)


class TestRediscovery:
    def test_rediscovery_updates_only_last_seen(self, session: Session) -> None:
        source = make_source(session)
        service = DiscoveryService(session)
        item = service.discover_manual(source.id, DEFAULT_URL, title_hint="Orijinal Başlık")
        first_seen = item.last_seen_at

        rediscovered = service.discover_manual(
            source.id,
            "https://example.com/haber/yeni-konu?b=2&a=1&utm_medium=m",
            title_hint="Farklı Başlık",
            snippet_hint="Sonradan gelen özet",
        )

        assert rediscovered.id == item.id
        assert rediscovered.title_hint == "Orijinal Başlık"
        assert rediscovered.snippet_hint is None
        assert rediscovered.last_seen_at >= first_seen

    def test_rediscovery_does_not_reset_lifecycle(self, session: Session) -> None:
        source = make_source(session)
        service = DiscoveryService(session)
        item = service.discover_manual(source.id, DEFAULT_URL)
        service.accept_item(item.id)

        rediscovered = service.discover_manual(source.id, DEFAULT_URL)

        assert rediscovered.lifecycle_state is DiscoveryLifecycleState.ACCEPTED

    def test_rediscovery_never_resurrects_a_rejected_item(self, session: Session) -> None:
        source = make_source(session)
        service = DiscoveryService(session)
        item = service.discover_manual(source.id, DEFAULT_URL)
        service.reject_item(item.id, DiscoveryRejectionReason.OUT_OF_SCOPE, note="kapsam dışı")

        rediscovered = service.discover_manual(source.id, DEFAULT_URL)

        assert rediscovered.lifecycle_state is DiscoveryLifecycleState.REJECTED
        assert rediscovered.rejection_reason is DiscoveryRejectionReason.OUT_OF_SCOPE
        assert rediscovered.rejection_note == "kapsam dışı"

    def test_rediscovery_preserves_fetch_state(self, session: Session) -> None:
        source = make_source(session)
        service = DiscoveryService(session)
        item = service.discover_manual(source.id, DEFAULT_URL)
        service.accept_item(item.id)
        service.mark_fetched(item.id)

        rediscovered = service.discover_manual(source.id, DEFAULT_URL)

        assert rediscovered.lifecycle_state is DiscoveryLifecycleState.FETCHED


class TestLifecycle:
    def test_happy_path_transitions(self, session: Session) -> None:
        source = make_source(session)
        service = DiscoveryService(session)
        item = service.discover_manual(source.id, DEFAULT_URL)

        assert service.accept_item(item.id).lifecycle_state is DiscoveryLifecycleState.ACCEPTED
        assert service.mark_fetched(item.id).lifecycle_state is DiscoveryLifecycleState.FETCHED

    def test_fetch_failure_and_explicit_requeue(self, session: Session) -> None:
        source = make_source(session)
        service = DiscoveryService(session)
        item = service.discover_manual(source.id, DEFAULT_URL)
        service.accept_item(item.id)
        service.mark_fetch_failed(item.id)

        requeued = service.requeue_fetch(item.id, reason="source outage resolved")

        assert requeued.lifecycle_state is DiscoveryLifecycleState.ACCEPTED
        assert requeued.metadata_json["last_requeue_reason"] == "source outage resolved"

    def test_requeue_requires_a_reason(self, session: Session) -> None:
        source = make_source(session)
        service = DiscoveryService(session)
        item = service.discover_manual(source.id, DEFAULT_URL)
        service.accept_item(item.id)
        service.mark_fetch_failed(item.id)

        with pytest.raises(InvalidDiscoveryTransitionError):
            service.requeue_fetch(item.id, reason="   ")

    def test_invalid_transitions_are_rejected(self, session: Session) -> None:
        source = make_source(session)
        service = DiscoveryService(session)
        item = service.discover_manual(source.id, DEFAULT_URL)

        with pytest.raises(InvalidDiscoveryTransitionError):
            service.mark_fetched(item.id)
        with pytest.raises(InvalidDiscoveryTransitionError):
            service.mark_fetch_failed(item.id)
        with pytest.raises(InvalidDiscoveryTransitionError):
            service.requeue_fetch(item.id, reason="not failed yet")

        service.accept_item(item.id)
        with pytest.raises(InvalidDiscoveryTransitionError):
            service.accept_item(item.id)
        with pytest.raises(InvalidDiscoveryTransitionError):
            service.reject_item(item.id, DiscoveryRejectionReason.POLICY)

    def test_rejected_is_terminal(self, session: Session) -> None:
        source = make_source(session)
        service = DiscoveryService(session)
        item = service.discover_manual(source.id, DEFAULT_URL)
        service.reject_item(item.id, DiscoveryRejectionReason.POLICY)

        with pytest.raises(InvalidDiscoveryTransitionError):
            service.accept_item(item.id)

    def test_unknown_item_raises_not_found(self, session: Session) -> None:
        with pytest.raises(DiscoveryItemNotFoundError):
            DiscoveryService(session).accept_item(uuid.uuid4())


class TestRepositoryAndRaces:
    def test_key_lookups(self, session: Session) -> None:
        source = make_source(session)
        service = DiscoveryService(session)
        item = service.discover_manual(source.id, DEFAULT_URL)
        repository = DiscoveryItemRepository(session)

        assert repository.get_by_id(item.id) is item
        assert repository.get_by_source_and_hash(source.id, item.url_hash) is item
        assert repository.get_by_source_and_hash(source.id, "0" * 64) is None

    def test_admission_race_returns_winner(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source = make_source(session)
        service = DiscoveryService(session)
        winner = service.discover_manual(source.id, DEFAULT_URL)
        session.commit()

        real_lookup = DiscoveryItemRepository.get_by_source_and_hash
        calls = {"count": 0}

        def racy_lookup(
            self: DiscoveryItemRepository, source_id: uuid.UUID, url_hash: str
        ) -> DiscoveryItem | None:
            calls["count"] += 1
            if calls["count"] == 1:
                return None
            return real_lookup(self, source_id, url_hash)

        monkeypatch.setattr(DiscoveryItemRepository, "get_by_source_and_hash", racy_lookup)
        result = service.discover_manual(source.id, DEFAULT_URL)

        assert result.id == winner.id
        assert isinstance(result, DiscoveryItem)

    def test_database_uniqueness_rejects_duplicate_rows(self, session: Session) -> None:
        source = make_source(session)
        service = DiscoveryService(session)
        item = service.discover_manual(source.id, DEFAULT_URL)
        session.commit()

        duplicate = DiscoveryItem(
            source_id=source.id,
            discovered_url=DEFAULT_URL,
            canonical_url=item.canonical_url,
            url_hash=item.url_hash,
            url_canonicalization_version=1,
            discovery_method=DiscoveryMethod.MANUAL,
            locale="tr-TR",
        )
        session.add(duplicate)
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()

    def test_expected_conflicts_are_domain_errors(self, session: Session) -> None:
        source = make_source(session)
        service = DiscoveryService(session)
        SourceRegistryService(session).transition_source_state(
            source.id, SourceLifecycleState.BLOCKED, reason="policy"
        )

        with pytest.raises(DiscoveryError):
            service.discover_manual(source.id, DEFAULT_URL)
