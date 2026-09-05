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
    SourceCapability,
    SourceKind,
    SourceLifecycleState,
    SourceRole,
    TrustTier,
    default_capabilities_for,
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
    normalize_capabilities,
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


class TestPurposeVocabulary:
    def test_role_and_capability_values_are_stable(self) -> None:
        assert [r.value for r in SourceRole] == [
            "inspiration",
            "turkish_editorial",
            "community_intent",
            "competitor",
            "taxonomy",
            "trend",
            "search",
        ]
        assert [c.value for c in SourceCapability] == [
            "inspiration",
            "community_need",
            "market",
            "competition",
            "taxonomy",
            "search",
            "trend",
            "visual_trend",
        ]

    def test_every_role_has_a_non_empty_default_capability_set(self) -> None:
        for role in SourceRole:
            defaults = default_capabilities_for(role)
            assert defaults, role
            assert all(isinstance(c, SourceCapability) for c in defaults)
        assert default_capabilities_for(SourceRole.TURKISH_EDITORIAL) == (
            SourceCapability.INSPIRATION,
            SourceCapability.MARKET,
            SourceCapability.COMPETITION,
            SourceCapability.TAXONOMY,
        )
        assert default_capabilities_for(SourceRole.COMMUNITY_INTENT) == (
            SourceCapability.COMMUNITY_NEED,
        )
        assert default_capabilities_for(SourceRole.TREND) == (
            SourceCapability.TREND,
            SourceCapability.VISUAL_TREND,
        )

    def test_normalize_capabilities_dedupes_orders_and_validates(self) -> None:
        assert normalize_capabilities(None, role=SourceRole.COMPETITOR) == [
            "competition",
            "market",
        ]
        assert normalize_capabilities(
            ["trend", SourceCapability.INSPIRATION, "trend", "market"],
            role=SourceRole.INSPIRATION,
        ) == ["inspiration", "market", "trend"]
        with pytest.raises(InvalidSourceDefinitionError, match="unknown source capability"):
            normalize_capabilities(["telepathy"], role=SourceRole.INSPIRATION)
        with pytest.raises(InvalidSourceDefinitionError, match="at least one"):
            normalize_capabilities([], role=SourceRole.INSPIRATION)


class TestPurposeRegistration:
    def test_defaults_to_inspiration_with_inspiration_capability(self, session: Session) -> None:
        source = register_default(SourceRegistryService(session))

        assert source.primary_role is SourceRole.INSPIRATION
        assert source.capabilities == ["inspiration"]
        event = SourceRepository(session).list_lifecycle_events(source.id)[0]
        assert event.reason.startswith("registered")
        assert "primary_role=inspiration" in event.reason
        assert "capabilities=inspiration" in event.reason

    def test_role_without_capabilities_uses_role_defaults(self, session: Session) -> None:
        source = register_default(
            SourceRegistryService(session), primary_role=SourceRole.TURKISH_EDITORIAL
        )

        assert source.primary_role is SourceRole.TURKISH_EDITORIAL
        assert source.capabilities == ["inspiration", "market", "competition", "taxonomy"]

    def test_explicit_capabilities_are_validated_and_canonical(self, session: Session) -> None:
        service = SourceRegistryService(session)
        source = register_default(
            service,
            primary_role=SourceRole.COMPETITOR,
            capabilities=["market", "competition", "market", SourceCapability.INSPIRATION],
        )
        assert source.capabilities == ["inspiration", "market", "competition"]

        with pytest.raises(InvalidSourceDefinitionError):
            register_default(service, slug="bozuk", capabilities=["nope"])
        with pytest.raises(InvalidSourceDefinitionError):
            register_default(service, slug="bos", capabilities=[])
        with pytest.raises(InvalidSourceDefinitionError):
            register_default(service, slug="rolsuz", primary_role="inspiration")  # type: ignore[arg-type]

    def test_repeat_registration_with_a_different_purpose_conflicts(self, session: Session) -> None:
        service = SourceRegistryService(session)
        register_default(service)

        with pytest.raises(SourceRegistrationConflictError) as excinfo:
            register_default(service, primary_role=SourceRole.COMPETITOR)
        assert excinfo.value.conflicting_fields == ["primary_role", "capabilities"]
        # Identical purpose stays idempotent.
        assert register_default(service, capabilities=["inspiration"]).slug == "ornek-kaynak"


class TestPurposeUpdate:
    def test_update_changes_purpose_and_audits_without_touching_state(
        self, session: Session
    ) -> None:
        service = SourceRegistryService(session)
        source = register_default(service)

        updated = service.update_source_purpose(
            source.id,
            primary_role=SourceRole.TREND,
            capabilities=["visual_trend", "trend", "inspiration"],
        )

        assert updated.id == source.id
        assert updated.primary_role is SourceRole.TREND
        assert updated.capabilities == ["inspiration", "trend", "visual_trend"]
        assert updated.lifecycle_state is SourceLifecycleState.ACTIVE
        assert updated.kind is SourceKind.RSS_FEED
        events = SourceRepository(session).list_lifecycle_events(source.id)
        assert len(events) == 2
        assert events[-1].previous_state is SourceLifecycleState.ACTIVE
        assert events[-1].new_state is SourceLifecycleState.ACTIVE
        assert events[-1].reason == (
            "purpose updated; primary_role=trend; capabilities=inspiration,trend,visual_trend"
        )
        assert events[-1].origin is LifecycleChangeOrigin.OPERATOR

    def test_update_without_capabilities_uses_role_defaults(self, session: Session) -> None:
        service = SourceRegistryService(session)
        source = register_default(service)

        service.update_source_purpose(source.id, primary_role=SourceRole.COMMUNITY_INTENT)

        assert source.capabilities == ["community_need"]

    def test_unchanged_purpose_is_a_no_op(self, session: Session) -> None:
        service = SourceRegistryService(session)
        source = register_default(service)

        service.update_source_purpose(
            source.id, primary_role=SourceRole.INSPIRATION, capabilities=["inspiration"]
        )

        assert len(SourceRepository(session).list_lifecycle_events(source.id)) == 1

    def test_update_errors_are_typed(self, session: Session) -> None:
        service = SourceRegistryService(session)
        source = register_default(service)

        with pytest.raises(SourceNotFoundError):
            service.update_source_purpose(uuid.uuid4(), primary_role=SourceRole.SEARCH)
        with pytest.raises(InvalidSourceDefinitionError):
            service.update_source_purpose(
                source.id, primary_role=SourceRole.SEARCH, capabilities=["bogus"]
            )
        with pytest.raises(InvalidSourceDefinitionError):
            service.update_source_purpose(
                source.id, primary_role=SourceRole.SEARCH, capabilities=[]
            )
        assert source.primary_role is SourceRole.INSPIRATION


class TestPurposePredicates:
    def test_capabilities_for_and_has_capability(self, session: Session) -> None:
        source = register_default(
            SourceRegistryService(session),
            primary_role=SourceRole.TAXONOMY,
            capabilities=["taxonomy", "market"],
        )

        assert SourceRegistryService.capabilities_for(source) == frozenset(
            {SourceCapability.TAXONOMY, SourceCapability.MARKET}
        )
        assert SourceRegistryService.has_capability(source, SourceCapability.MARKET)
        assert not SourceRegistryService.has_capability(source, SourceCapability.COMMUNITY_NEED)

    def test_unknown_persisted_capability_value_is_ignored_not_fatal(
        self, session: Session
    ) -> None:
        source = register_default(SourceRegistryService(session))
        source.capabilities = ["inspiration", "legacy_value"]

        assert SourceRegistryService.capabilities_for(source) == frozenset(
            {SourceCapability.INSPIRATION}
        )

    def test_only_community_intent_sources_are_barred_from_evidence(self, session: Session) -> None:
        service = SourceRegistryService(session)
        for role in SourceRole:
            source = register_default(
                service,
                slug=f"rol-{role.value.replace('_', '-')}",
                base_url=f"https://{role.value.replace('_', '-')}.example.test/feed.xml",
                primary_role=role,
            )
            assert SourceRegistryService.evidence_allowed(source) is (
                role is not SourceRole.COMMUNITY_INTENT
            ), role
