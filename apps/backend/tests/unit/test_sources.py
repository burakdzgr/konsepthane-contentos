"""Tests for the Source Registry persistence foundation."""

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from contentos.db.base import Base
from contentos.sources.enums import (
    DiscoveryStrategy,
    LifecycleChangeOrigin,
    RobotsPolicy,
    SourceKind,
    SourceLifecycleState,
    TrustTier,
)
from contentos.sources.models import Source
from contentos.sources.repository import SourceRepository
from contentos.sources.service import (
    InvalidLifecycleTransitionError,
    InvalidSourceDefinitionError,
    SourceNotFoundError,
    SourceRegistrationConflictError,
    SourceRegistryError,
    SourceRegistryService,
)
from contentos.sources.urls import InvalidSourceUrlError, normalize_base_url


@pytest.fixture()
def session() -> Iterator[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db_session:
        yield db_session
    engine.dispose()


def register_default(service: SourceRegistryService, **overrides: Any) -> Source:
    arguments: dict[str, Any] = {
        "slug": "ornek-kaynak",
        "name": "Örnek Kaynak",
        "kind": SourceKind.RSS_FEED,
        "base_url": "https://example.com/feed.xml",
        "trust_tier": TrustTier.REPUTABLE,
    }
    arguments.update(overrides)
    return service.register_source(**arguments)


class TestEnumContracts:
    def test_persistent_enum_values_are_stable(self) -> None:
        assert [k.value for k in SourceKind] == [
            "editorial_site",
            "competitor_site",
            "rss_feed",
            "sitemap",
            "manual",
            "trend_provider",
            "search_provider",
        ]
        assert [s.value for s in SourceLifecycleState] == [
            "active",
            "paused",
            "disabled",
            "blocked",
        ]
        assert [t.value for t in TrustTier] == [
            "official",
            "expert",
            "reputable",
            "general",
            "reference_only",
        ]
        assert [d.value for d in DiscoveryStrategy] == ["feed", "sitemap", "manual", "provider"]
        assert [r.value for r in RobotsPolicy] == ["obey"]
        assert [o.value for o in LifecycleChangeOrigin] == ["operator", "system"]


class TestBaseUrlNormalization:
    def test_normalizes_case_default_port_fragment_and_trailing_slash(self) -> None:
        assert (
            normalize_base_url("HTTPS://Example.COM:443/Feed/#section")
            == "https://example.com/Feed"
        )
        assert normalize_base_url("http://example.com:80/") == "http://example.com"
        assert normalize_base_url("https://example.com") == "https://example.com"

    def test_preserves_non_default_port_and_query(self) -> None:
        assert (
            normalize_base_url("https://example.com:8443/feed?format=rss")
            == "https://example.com:8443/feed?format=rss"
        )

    @pytest.mark.parametrize(
        "invalid_url",
        ["", "   ", "ftp://example.com/feed", "file:///etc/passwd", "example.com/feed"],
    )
    def test_rejects_unsupported_or_invalid_urls(self, invalid_url: str) -> None:
        with pytest.raises(InvalidSourceUrlError):
            normalize_base_url(invalid_url)

    def test_rejects_embedded_credentials_and_bad_ports(self) -> None:
        with pytest.raises(InvalidSourceUrlError):
            normalize_base_url("https://user:pass@example.com/feed")
        with pytest.raises(InvalidSourceUrlError):
            normalize_base_url("https://example.com:notaport/feed")


class TestRegistration:
    def test_creates_a_new_source_with_defaults(self, session: Session) -> None:
        service = SourceRegistryService(session)

        source = register_default(service)

        assert source.slug == "ornek-kaynak"
        assert source.base_url == "https://example.com/feed.xml"
        assert source.lifecycle_state is SourceLifecycleState.ACTIVE
        assert source.robots_policy is RobotsPolicy.OBEY
        assert source.discovery_strategy is DiscoveryStrategy.FEED
        assert source.locale == "tr-TR"
        assert source.market == "TR"
        assert source.discovery_config == {}
        assert source.metadata_json == {}

    def test_identical_repeat_registration_is_idempotent(self, session: Session) -> None:
        service = SourceRegistryService(session)

        first = register_default(service)
        second = register_default(service)

        assert second.id == first.id
        repository = SourceRepository(session)
        assert repository.get_by_slug("ornek-kaynak") is not None

    def test_registration_normalizes_url_before_identity_comparison(self, session: Session) -> None:
        service = SourceRegistryService(session)

        first = register_default(service, base_url="https://example.com/feed.xml")
        second = register_default(service, base_url="HTTPS://EXAMPLE.com:443/feed.xml")

        assert second.id == first.id

    def test_slug_conflict_with_different_definition_fails(self, session: Session) -> None:
        service = SourceRegistryService(session)
        register_default(service)

        with pytest.raises(SourceRegistrationConflictError) as info:
            register_default(service, base_url="https://different.example.com/feed.xml")

        assert "base_url" in info.value.conflicting_fields

    def test_identity_conflict_with_different_slug_fails(self, session: Session) -> None:
        service = SourceRegistryService(session)
        register_default(service)

        with pytest.raises(SourceRegistrationConflictError) as info:
            register_default(service, slug="baska-kaynak")

        assert "slug" in info.value.conflicting_fields

    def test_no_silent_configuration_overwrite(self, session: Session) -> None:
        service = SourceRegistryService(session)
        original = register_default(service)

        with pytest.raises(SourceRegistrationConflictError) as info:
            register_default(service, trust_tier=TrustTier.OFFICIAL)

        assert info.value.conflicting_fields == ["trust_tier"]
        refreshed = SourceRepository(session).get_by_id(original.id)
        assert refreshed is not None
        assert refreshed.trust_tier is TrustTier.REPUTABLE

    @pytest.mark.parametrize("bad_slug", ["", "Büyük", "UPPER", "-lead", "trail-", "a" * 101])
    def test_invalid_slugs_are_rejected(self, session: Session, bad_slug: str) -> None:
        service = SourceRegistryService(session)

        with pytest.raises(InvalidSourceDefinitionError):
            register_default(service, slug=bad_slug)

    def test_kind_without_default_strategy_requires_explicit_strategy(
        self, session: Session
    ) -> None:
        service = SourceRegistryService(session)

        with pytest.raises(InvalidSourceDefinitionError):
            register_default(service, kind=SourceKind.EDITORIAL_SITE)

        source = register_default(
            service,
            kind=SourceKind.EDITORIAL_SITE,
            discovery_strategy=DiscoveryStrategy.FEED,
        )
        assert source.discovery_strategy is DiscoveryStrategy.FEED

    def test_registration_conflicts_are_domain_errors_not_sqlalchemy(
        self, session: Session
    ) -> None:
        service = SourceRegistryService(session)
        register_default(service)

        with pytest.raises(SourceRegistryError):
            register_default(service, slug="baska-kaynak")


class TestRegistrationRaceRecovery:
    def _patch_first_lookup_miss(self, monkeypatch: pytest.MonkeyPatch) -> None:
        real_find = SourceRegistryService._find_existing
        calls = {"count": 0}

        def racy_find(self: SourceRegistryService, definition: dict[str, Any]) -> Source | None:
            calls["count"] += 1
            if calls["count"] == 1:
                return None
            return real_find(self, definition)

        monkeypatch.setattr(SourceRegistryService, "_find_existing", racy_find)

    def test_race_with_identical_definition_returns_winner(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        service = SourceRegistryService(session)
        winner = register_default(service)
        session.commit()

        self._patch_first_lookup_miss(monkeypatch)
        result = register_default(service)

        assert result.id == winner.id

    def test_race_with_conflicting_definition_raises_typed_conflict(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        service = SourceRegistryService(session)
        register_default(service)
        session.commit()

        self._patch_first_lookup_miss(monkeypatch)
        with pytest.raises(SourceRegistrationConflictError):
            register_default(service, name="Tamamen Farklı")

    def test_database_uniqueness_rejects_actual_duplicate_rows(self, session: Session) -> None:
        service = SourceRegistryService(session)
        original = register_default(service)
        session.commit()

        duplicate = Source(
            slug=original.slug,
            name="Doğrudan Kopya",
            kind=original.kind,
            base_url=original.base_url,
            trust_tier=TrustTier.GENERAL,
            discovery_strategy=DiscoveryStrategy.FEED,
        )
        session.add(duplicate)
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()


class TestLifecycle:
    def test_valid_transitions_update_state_and_audit(self, session: Session) -> None:
        service = SourceRegistryService(session)
        source = register_default(service)

        service.transition_source_state(
            source.id, SourceLifecycleState.PAUSED, reason="manual hold"
        )
        assert source.lifecycle_state is SourceLifecycleState.PAUSED
        assert source.state_reason == "manual hold"
        assert source.state_changed_at is not None

        service.transition_source_state(source.id, SourceLifecycleState.ACTIVE, reason="resume")
        service.transition_source_state(source.id, SourceLifecycleState.DISABLED, reason="seasonal")
        service.transition_source_state(source.id, SourceLifecycleState.ACTIVE, reason="re-enable")

        events = SourceRepository(session).list_lifecycle_events(source.id)
        transitions = [(event.previous_state, event.new_state) for event in events]
        assert transitions == [
            (None, SourceLifecycleState.ACTIVE),
            (SourceLifecycleState.ACTIVE, SourceLifecycleState.PAUSED),
            (SourceLifecycleState.PAUSED, SourceLifecycleState.ACTIVE),
            (SourceLifecycleState.ACTIVE, SourceLifecycleState.DISABLED),
            (SourceLifecycleState.DISABLED, SourceLifecycleState.ACTIVE),
        ]
        assert all(event.reason for event in events)

    def test_blocked_only_leaves_to_active_by_explicit_decision(self, session: Session) -> None:
        service = SourceRegistryService(session)
        source = register_default(service)
        service.transition_source_state(
            source.id, SourceLifecycleState.BLOCKED, reason="robots disallows crawling"
        )

        with pytest.raises(InvalidLifecycleTransitionError):
            service.transition_source_state(
                source.id, SourceLifecycleState.PAUSED, reason="try pause"
            )
        with pytest.raises(InvalidLifecycleTransitionError):
            service.transition_source_state(
                source.id, SourceLifecycleState.DISABLED, reason="try disable"
            )

        unblocked = service.transition_source_state(
            source.id,
            SourceLifecycleState.ACTIVE,
            reason="policy re-reviewed and cleared",
        )
        assert unblocked.lifecycle_state is SourceLifecycleState.ACTIVE

    def test_invalid_transitions_are_rejected(self, session: Session) -> None:
        service = SourceRegistryService(session)
        source = register_default(service)
        service.transition_source_state(source.id, SourceLifecycleState.DISABLED, reason="turn off")

        with pytest.raises(InvalidLifecycleTransitionError):
            service.transition_source_state(
                source.id, SourceLifecycleState.PAUSED, reason="nonsense"
            )

    def test_same_state_transition_is_rejected(self, session: Session) -> None:
        service = SourceRegistryService(session)
        source = register_default(service)

        with pytest.raises(InvalidLifecycleTransitionError):
            service.transition_source_state(source.id, SourceLifecycleState.ACTIVE, reason="noop")

    def test_reason_is_required(self, session: Session) -> None:
        service = SourceRegistryService(session)
        source = register_default(service)

        with pytest.raises(InvalidLifecycleTransitionError):
            service.transition_source_state(source.id, SourceLifecycleState.PAUSED, reason="   ")

    def test_unknown_source_raises_not_found(self, session: Session) -> None:
        service = SourceRegistryService(session)

        with pytest.raises(SourceNotFoundError):
            service.transition_source_state(
                uuid.uuid4(), SourceLifecycleState.PAUSED, reason="missing"
            )

    def test_origin_is_recorded(self, session: Session) -> None:
        service = SourceRegistryService(session)
        source = register_default(service)

        service.transition_source_state(
            source.id,
            SourceLifecycleState.BLOCKED,
            reason="automated policy check failed",
            origin=LifecycleChangeOrigin.SYSTEM,
        )

        events = SourceRepository(session).list_lifecycle_events(source.id)
        assert events[-1].origin is LifecycleChangeOrigin.SYSTEM


class TestRepository:
    def test_key_lookups(self, session: Session) -> None:
        service = SourceRegistryService(session)
        source = register_default(service)
        repository = SourceRepository(session)

        assert repository.get_by_id(source.id) is source
        assert repository.get_by_slug("ornek-kaynak") is source
        assert (
            repository.get_by_identity(SourceKind.RSS_FEED, "https://example.com/feed.xml")
            is source
        )
        assert repository.get_by_slug("yok") is None
        assert repository.get_by_id(uuid.uuid4()) is None
