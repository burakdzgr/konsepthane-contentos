"""Operator control API tests (SQLite, real sessions, fake dispatcher)."""

import asyncio
import uuid
from typing import Any

import httpx
from fastapi import FastAPI
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from contentos.api.app import create_app
from contentos.core.config import Environment, LogLevel, Settings
from contentos.core.context import is_valid_request_id
from contentos.db.base import Base
from contentos.discovery.enums import DiscoveryLifecycleState
from contentos.discovery.models import DiscoveryItem
from contentos.discovery.service import DiscoveryService
from contentos.sources.enums import (
    DiscoveryStrategy,
    LifecycleChangeOrigin,
    SourceKind,
    SourceLifecycleState,
    TrustTier,
)
from contentos.sources.models import Source, SourceLifecycleEvent
from contentos.sources.service import SourceRegistryService


def control_settings() -> Settings:
    return Settings(
        environment=Environment.TEST,
        service_name="ContentOS Control API Test",
        application_version="1.0.0-test",
        log_level=LogLevel.INFO,
        api_docs_enabled=False,
        database_url="postgresql+psycopg://contentos:control-secret@localhost:5432/contentos_ctl",
        redis_broker_url="redis://:control-secret@localhost:6379/0",
    )


class FakeResearchControlDispatcher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str | None]] = []

    def enqueue_discovery(self, source_id: str, *, request_id: str | None = None) -> None:
        self.calls.append(("discover_source", source_id, request_id))

    def enqueue_fetch(self, discovery_item_id: str, *, request_id: str | None = None) -> None:
        self.calls.append(("fetch_discovery_item", discovery_item_id, request_id))


class FailingDispatcher(FakeResearchControlDispatcher):
    def enqueue_discovery(self, source_id: str, *, request_id: str | None = None) -> None:
        raise ConnectionError("broker connect failed: redis://:secret@internal:6379/0")

    def enqueue_fetch(self, discovery_item_id: str, *, request_id: str | None = None) -> None:
        raise ConnectionError("broker connect failed: redis://:secret@internal:6379/0")


class Harness:
    """Real sessions over shared in-memory SQLite behind the real app."""

    def __init__(self, dispatcher: FakeResearchControlDispatcher | None = None) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.dispatcher = dispatcher if dispatcher is not None else FakeResearchControlDispatcher()
        self.app: FastAPI = create_app(settings=control_settings())
        self.app.state.db_session_factory = self.session_factory
        self.app.state.research_control_dispatcher = self.dispatcher

    def request(
        self,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        async def run() -> httpx.Response:
            transport = httpx.ASGITransport(app=self.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://ctl") as client:
                return await client.request(method, path, json=json_body, headers=headers)

        return asyncio.run(run())

    def post(
        self,
        path: str,
        json_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        return self.request("POST", path, json_body, headers)

    def session(self) -> Session:
        return self.session_factory()


def registration_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "slug": "ornek-besleme",
        "name": "Örnek Besleme",
        "kind": "rss_feed",
        "base_url": "https://ornek-besleme.example.test/feed",
        "trust_tier": "general",
    }
    body.update(overrides)
    return body


def seed_source(
    harness: Harness,
    slug: str,
    *,
    kind: SourceKind = SourceKind.MANUAL,
    lifecycle_state: SourceLifecycleState = SourceLifecycleState.ACTIVE,
) -> uuid.UUID:
    with harness.session() as session:
        source = SourceRegistryService(session).register_source(
            slug=slug,
            name=f"Kaynak {slug}",
            kind=kind,
            base_url=f"https://{slug}.example.test/",
            trust_tier=TrustTier.GENERAL,
        )
        if lifecycle_state is not SourceLifecycleState.ACTIVE:
            source.lifecycle_state = lifecycle_state
        session.commit()
        return source.id


def seed_item(
    harness: Harness,
    source_id: uuid.UUID,
    path: str,
    *,
    state: DiscoveryLifecycleState = DiscoveryLifecycleState.DISCOVERED,
) -> uuid.UUID:
    with harness.session() as session:
        source = session.get(Source, source_id)
        assert source is not None
        service = DiscoveryService(session)
        item = service.discover_manual(source_id, f"https://{source.slug}.example.test/{path}")
        if state in (
            DiscoveryLifecycleState.ACCEPTED,
            DiscoveryLifecycleState.FETCHED,
            DiscoveryLifecycleState.FETCH_FAILED,
        ):
            service.accept_item(item.id)
        if state is DiscoveryLifecycleState.FETCHED:
            service.mark_fetched(item.id)
        elif state is DiscoveryLifecycleState.FETCH_FAILED:
            service.mark_fetch_failed(item.id)
        session.commit()
        return item.id


def item_state(harness: Harness, item_id: uuid.UUID) -> DiscoveryLifecycleState:
    with harness.session() as session:
        item = session.get(DiscoveryItem, item_id)
        assert item is not None
        return item.lifecycle_state


class TestSourceRegistration:
    def test_registers_feed_sitemap_and_manual_sources(self) -> None:
        harness = Harness()
        for slug, kind, expected_strategy in [
            ("besleme", "rss_feed", DiscoveryStrategy.FEED),
            ("harita", "sitemap", DiscoveryStrategy.SITEMAP),
            ("elle", "manual", DiscoveryStrategy.MANUAL),
        ]:
            response = harness.post(
                "/internal/research/sources",
                registration_body(slug=slug, kind=kind, base_url=f"https://{slug}.example.test/"),
            )
            assert response.status_code == 200, response.text
            payload = response.json()
            assert payload["status"] == "registered"
            assert payload["lifecycle_state"] == "active"
            with harness.session() as session:
                source = session.execute(select(Source).where(Source.slug == slug)).scalar_one()
                # Default discovery strategy comes from the domain service.
                assert source.discovery_strategy is expected_strategy
                assert str(source.id) == payload["source_id"]

    def test_identical_registration_is_idempotent(self) -> None:
        harness = Harness()
        first = harness.post("/internal/research/sources", registration_body()).json()
        second = harness.post("/internal/research/sources", registration_body()).json()

        assert first["status"] == "registered"
        assert second["status"] == "existing"
        assert second["source_id"] == first["source_id"]
        with harness.session() as session:
            count = len(list(session.execute(select(Source)).scalars()))
            assert count == 1

    def test_conflicting_definition_returns_409(self) -> None:
        harness = Harness()
        harness.post("/internal/research/sources", registration_body())
        response = harness.post(
            "/internal/research/sources",
            registration_body(name="Başka İsim"),
        )

        assert response.status_code == 409
        body = response.json()
        assert body["error"]["code"] == "conflict"
        assert "request_id" in body
        # No silent overwrite happened.
        with harness.session() as session:
            source = session.execute(select(Source)).scalar_one()
            assert source.name == "Örnek Besleme"

    def test_invalid_definition_returns_safe_validation_response(self) -> None:
        harness = Harness()
        response = harness.post(
            "/internal/research/sources",
            registration_body(slug="Geçersiz Slug!"),
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"

    def test_placeholder_and_container_kinds_are_not_registrable(self) -> None:
        harness = Harness()
        for kind in ["trend_provider", "search_provider", "editorial_site", "competitor_site"]:
            response = harness.post("/internal/research/sources", registration_body(kind=kind))
            assert response.status_code == 422, kind
            assert response.json()["error"]["code"] == "validation_error"
        with harness.session() as session:
            assert session.execute(select(Source)).scalar_one_or_none() is None

    def test_free_form_json_fields_are_rejected(self) -> None:
        harness = Harness()
        response = harness.post(
            "/internal/research/sources",
            registration_body(metadata={"x": 1}),
        )
        assert response.status_code == 422

        response = harness.post(
            "/internal/research/sources",
            registration_body(fetch_policy={"timeout": 0}),
        )
        assert response.status_code == 422

    def test_registration_performs_no_network_lookup(self) -> None:
        # An unresolvable TLD registers fine because registration never
        # resolves DNS or fetches anything.
        harness = Harness()
        response = harness.post(
            "/internal/research/sources",
            registration_body(base_url="https://kesinlikle-yok.invalid/"),
        )
        assert response.status_code == 200


class TestSourceLifecycle:
    def test_valid_transitions_including_blocked_roundtrip(self) -> None:
        harness = Harness()
        source_id = seed_source(harness, "yasam")

        for new_state, expected in [
            ("paused", "paused"),
            ("active", "active"),
            ("blocked", "blocked"),
            ("active", "active"),
        ]:
            response = harness.post(
                f"/internal/research/sources/{source_id}/lifecycle",
                {"new_state": new_state, "reason": f"operator move to {new_state}"},
            )
            assert response.status_code == 200, response.text
            assert response.json() == {
                "status": "updated",
                "source_id": str(source_id),
                "lifecycle_state": expected,
            }

    def test_transition_writes_operator_audit_event(self) -> None:
        harness = Harness()
        source_id = seed_source(harness, "denetim")
        harness.post(
            f"/internal/research/sources/{source_id}/lifecycle",
            {"new_state": "paused", "reason": "bakım molası"},
        )

        with harness.session() as session:
            events = list(
                session.execute(
                    select(SourceLifecycleEvent)
                    .where(SourceLifecycleEvent.source_id == source_id)
                    .order_by(SourceLifecycleEvent.id)
                ).scalars()
            )
            # Registration event plus the transition event.
            assert [event.new_state for event in events] == [
                SourceLifecycleState.ACTIVE,
                SourceLifecycleState.PAUSED,
            ]
            assert events[-1].previous_state is SourceLifecycleState.ACTIVE
            assert events[-1].reason == "bakım molası"
            assert events[-1].origin is LifecycleChangeOrigin.OPERATOR

    def test_invalid_transition_returns_409_and_mutates_nothing(self) -> None:
        harness = Harness()
        source_id = seed_source(harness, "kilitli")
        harness.post(
            f"/internal/research/sources/{source_id}/lifecycle",
            {"new_state": "blocked", "reason": "policy stop"},
        )

        response = harness.post(
            f"/internal/research/sources/{source_id}/lifecycle",
            {"new_state": "paused", "reason": "should not work"},
        )
        assert response.status_code == 409
        with harness.session() as session:
            source = session.get(Source, source_id)
            assert source is not None
            assert source.lifecycle_state is SourceLifecycleState.BLOCKED

    def test_blank_reason_rejected(self) -> None:
        harness = Harness()
        source_id = seed_source(harness, "sebepsiz")

        missing = harness.post(
            f"/internal/research/sources/{source_id}/lifecycle",
            {"new_state": "paused", "reason": ""},
        )
        assert missing.status_code == 422

        whitespace = harness.post(
            f"/internal/research/sources/{source_id}/lifecycle",
            {"new_state": "paused", "reason": "   "},
        )
        # The domain service, not the route, owns the semantic check.
        assert whitespace.status_code == 409

    def test_missing_source_returns_404(self) -> None:
        harness = Harness()
        response = harness.post(
            f"/internal/research/sources/{uuid.uuid4()}/lifecycle",
            {"new_state": "paused", "reason": "x"},
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"

    def test_lifecycle_origin_cannot_come_from_the_request(self) -> None:
        harness = Harness()
        source_id = seed_source(harness, "kokensiz")
        response = harness.post(
            f"/internal/research/sources/{source_id}/lifecycle",
            {"new_state": "paused", "reason": "x", "origin": "system"},
        )
        # extra="forbid": the field is refused outright.
        assert response.status_code == 422


class TestDiscoveryAdmission:
    def test_accept_discovered_item(self) -> None:
        harness = Harness()
        source_id = seed_source(harness, "kabul")
        item_id = seed_item(harness, source_id, "aday")

        response = harness.post(f"/internal/research/discovery-items/{item_id}/accept")

        assert response.status_code == 200
        assert response.json() == {
            "status": "updated",
            "discovery_item_id": str(item_id),
            "lifecycle_state": "accepted",
        }
        assert item_state(harness, item_id) is DiscoveryLifecycleState.ACCEPTED
        # Accept never enqueues fetch.
        assert harness.dispatcher.calls == []

    def test_reject_discovered_item_with_coded_reason_and_note(self) -> None:
        harness = Harness()
        source_id = seed_source(harness, "ret")
        item_id = seed_item(harness, source_id, "aday")

        response = harness.post(
            f"/internal/research/discovery-items/{item_id}/reject",
            {"reason": "out_of_scope", "note": "kapsam dışı konu"},
        )

        assert response.status_code == 200
        assert response.json()["lifecycle_state"] == "rejected"
        with harness.session() as session:
            item = session.get(DiscoveryItem, item_id)
            assert item is not None
            assert item.rejection_note == "kapsam dışı konu"

    def test_unknown_rejection_reason_rejected(self) -> None:
        harness = Harness()
        source_id = seed_source(harness, "ret-bilinmez")
        item_id = seed_item(harness, source_id, "aday")

        response = harness.post(
            f"/internal/research/discovery-items/{item_id}/reject",
            {"reason": "made_up_reason"},
        )
        assert response.status_code == 422

    def test_accept_or_reject_in_wrong_state_returns_409(self) -> None:
        harness = Harness()
        source_id = seed_source(harness, "yanlis-durum")
        accepted = seed_item(harness, source_id, "kabullu", state=DiscoveryLifecycleState.ACCEPTED)

        assert (
            harness.post(f"/internal/research/discovery-items/{accepted}/accept").status_code == 409
        )
        assert (
            harness.post(
                f"/internal/research/discovery-items/{accepted}/reject",
                {"reason": "policy"},
            ).status_code
            == 409
        )

    def test_rejected_item_cannot_be_resurrected(self) -> None:
        harness = Harness()
        source_id = seed_source(harness, "terminal")
        item_id = seed_item(harness, source_id, "aday")
        harness.post(
            f"/internal/research/discovery-items/{item_id}/reject",
            {"reason": "policy"},
        )

        for path, body in [
            (f"/internal/research/discovery-items/{item_id}/accept", None),
            (f"/internal/research/discovery-items/{item_id}/requeue", {"reason": "tekrar"}),
            (f"/internal/research/discovery-items/{item_id}/fetch", None),
        ]:
            response = harness.post(path, body)
            assert response.status_code == 409, path
        assert item_state(harness, item_id) is DiscoveryLifecycleState.REJECTED

    def test_requeue_failed_fetch(self) -> None:
        harness = Harness()
        source_id = seed_source(harness, "tekrar-dene")
        item_id = seed_item(
            harness, source_id, "hatali", state=DiscoveryLifecycleState.FETCH_FAILED
        )

        response = harness.post(
            f"/internal/research/discovery-items/{item_id}/requeue",
            {"reason": "kaynak tekrar erişilebilir"},
        )

        assert response.status_code == 200
        assert response.json()["lifecycle_state"] == "accepted"
        # Requeue never starts fetch by itself.
        assert harness.dispatcher.calls == []
        with harness.session() as session:
            item = session.get(DiscoveryItem, item_id)
            assert item is not None
            assert item.metadata_json["last_requeue_reason"] == "kaynak tekrar erişilebilir"

    def test_requeue_requires_reason_and_failed_state(self) -> None:
        harness = Harness()
        source_id = seed_source(harness, "tekrar-sebep")
        failed = seed_item(harness, source_id, "hatali", state=DiscoveryLifecycleState.FETCH_FAILED)
        discovered = seed_item(harness, source_id, "aday")

        assert (
            harness.post(
                f"/internal/research/discovery-items/{failed}/requeue", {"reason": ""}
            ).status_code
            == 422
        )
        assert (
            harness.post(
                f"/internal/research/discovery-items/{discovered}/requeue",
                {"reason": "x"},
            ).status_code
            == 409
        )

    def test_missing_item_returns_404(self) -> None:
        harness = Harness()
        response = harness.post(f"/internal/research/discovery-items/{uuid.uuid4()}/accept")
        assert response.status_code == 404


class TestTaskTriggers:
    def test_discover_trigger_for_active_feed_and_sitemap_sources(self) -> None:
        harness = Harness()
        feed_id = seed_source(harness, "akis", kind=SourceKind.RSS_FEED)
        map_id = seed_source(harness, "harita-kaynak", kind=SourceKind.SITEMAP)

        for source_id in (feed_id, map_id):
            response = harness.post(f"/internal/research/sources/{source_id}/discover")
            assert response.status_code == 200
            assert response.json() == {
                "status": "queued",
                "task": "discover_source",
                "entity_id": str(source_id),
            }
        assert [call[:2] for call in harness.dispatcher.calls] == [
            ("discover_source", str(feed_id)),
            ("discover_source", str(map_id)),
        ]

    def test_discover_trigger_refuses_manual_inactive_and_missing_sources(self) -> None:
        harness = Harness()
        manual_id = seed_source(harness, "elle-kaynak", kind=SourceKind.MANUAL)
        paused_id = seed_source(
            harness,
            "durgun",
            kind=SourceKind.RSS_FEED,
            lifecycle_state=SourceLifecycleState.PAUSED,
        )

        assert harness.post(f"/internal/research/sources/{manual_id}/discover").status_code == 409
        assert harness.post(f"/internal/research/sources/{paused_id}/discover").status_code == 409
        assert (
            harness.post(f"/internal/research/sources/{uuid.uuid4()}/discover").status_code == 404
        )
        assert harness.dispatcher.calls == []

    def test_fetch_trigger_for_accepted_item_of_active_source(self) -> None:
        harness = Harness()
        source_id = seed_source(harness, "indir")
        item_id = seed_item(harness, source_id, "kabullu", state=DiscoveryLifecycleState.ACCEPTED)

        response = harness.post(f"/internal/research/discovery-items/{item_id}/fetch")

        assert response.status_code == 200
        assert response.json() == {
            "status": "queued",
            "task": "fetch_discovery_item",
            "entity_id": str(item_id),
        }
        [(task_name, entity_id, request_id)] = harness.dispatcher.calls
        assert (task_name, entity_id) == ("fetch_discovery_item", str(item_id))
        # The middleware generates a request ID when the caller sends none,
        # and it propagates to the dispatch.
        assert is_valid_request_id(request_id)
        # Trigger endpoints mutate no durable state.
        assert item_state(harness, item_id) is DiscoveryLifecycleState.ACCEPTED

    def test_fetch_trigger_refuses_every_ineligible_state(self) -> None:
        harness = Harness()
        source_id = seed_source(harness, "durumlar")
        discovered = seed_item(harness, source_id, "aday")
        fetched = seed_item(harness, source_id, "inmis", state=DiscoveryLifecycleState.FETCHED)
        failed = seed_item(harness, source_id, "hatali", state=DiscoveryLifecycleState.FETCH_FAILED)

        for item_id in (discovered, fetched, failed):
            response = harness.post(f"/internal/research/discovery-items/{item_id}/fetch")
            assert response.status_code == 409, item_id
        assert harness.dispatcher.calls == []

    def test_fetch_trigger_refuses_inactive_parent_source(self) -> None:
        harness = Harness()
        source_id = seed_source(harness, "ebeveyn")
        item_id = seed_item(harness, source_id, "kabullu", state=DiscoveryLifecycleState.ACCEPTED)
        harness.post(
            f"/internal/research/sources/{source_id}/lifecycle",
            {"new_state": "paused", "reason": "hold"},
        )

        response = harness.post(f"/internal/research/discovery-items/{item_id}/fetch")

        assert response.status_code == 409
        assert harness.dispatcher.calls == []

    def test_request_id_propagates_to_dispatch(self) -> None:
        harness = Harness()
        source_id = seed_source(harness, "izli", kind=SourceKind.RSS_FEED)
        harness.post(
            f"/internal/research/sources/{source_id}/discover",
            headers={"X-Request-ID": "operator-req-1"},
        )

        assert harness.dispatcher.calls == [("discover_source", str(source_id), "operator-req-1")]

    def test_dispatcher_failure_is_a_safe_failure_never_queued(self) -> None:
        harness = Harness(dispatcher=FailingDispatcher())
        source_id = seed_source(harness, "kirikli", kind=SourceKind.RSS_FEED)

        response = harness.post(f"/internal/research/sources/{source_id}/discover")

        assert response.status_code == 503
        text = response.text
        assert "queued" not in text
        assert "redis" not in text.lower()
        assert "secret" not in text.lower()
        assert "task_id" not in text

    def test_trigger_response_never_exposes_celery_task_id(self) -> None:
        harness = Harness()
        source_id = seed_source(harness, "temiz", kind=SourceKind.RSS_FEED)
        payload = harness.post(f"/internal/research/sources/{source_id}/discover").json()
        assert set(payload) == {"status", "task", "entity_id"}


class TestTransactionBehavior:
    def test_commit_failure_is_never_reported_as_success(self) -> None:
        harness = Harness()
        source_id = seed_source(harness, "islem")
        base_factory = harness.session_factory

        def failing_commit_factory() -> Session:
            session = base_factory()

            def boom() -> None:
                raise RuntimeError("simulated commit failure")

            session.commit = boom  # type: ignore[method-assign]
            return session

        harness.app.state.db_session_factory = failing_commit_factory
        response = harness.post(
            f"/internal/research/sources/{source_id}/lifecycle",
            {"new_state": "paused", "reason": "will fail"},
        )
        harness.app.state.db_session_factory = base_factory

        assert response.status_code == 500
        assert response.json()["error"]["code"] == "internal_error"
        with harness.session() as session:
            source = session.get(Source, source_id)
            assert source is not None
            assert source.lifecycle_state is SourceLifecycleState.ACTIVE
            events = list(
                session.execute(
                    select(SourceLifecycleEvent).where(SourceLifecycleEvent.source_id == source_id)
                ).scalars()
            )
            # Only the registration event survived: transition + audit event
            # rolled back atomically together.
            assert len(events) == 1

    def test_domain_error_leaves_no_partial_state(self) -> None:
        harness = Harness()
        source_id = seed_source(harness, "atomik")
        item_id = seed_item(harness, source_id, "aday")
        harness.post(f"/internal/research/discovery-items/{item_id}/reject", {"reason": "policy"})

        response = harness.post(
            f"/internal/research/discovery-items/{item_id}/reject",
            {"reason": "out_of_scope", "note": "ikinci deneme"},
        )

        assert response.status_code == 409
        with harness.session() as session:
            item = session.get(DiscoveryItem, item_id)
            assert item is not None
            assert item.rejection_note is None
            assert item.rejection_reason is not None
            assert item.rejection_reason.value == "policy"


class TestApiSurface:
    def test_control_paths_are_post_only_and_read_paths_untouched(self) -> None:
        harness = Harness()
        schema = harness.app.openapi()
        research_paths = {
            path: set(operations)
            for path, operations in schema["paths"].items()
            if path.startswith("/internal/research")
        }

        assert research_paths == {
            "/internal/research/sources": {"get", "post"},
            "/internal/research/discovery-items": {"get"},
            "/internal/research/discovery-items/{discovery_item_id}": {"get"},
            "/internal/research/sources/{source_id}/lifecycle": {"post"},
            "/internal/research/sources/{source_id}/discover": {"post"},
            "/internal/research/discovery-items/{discovery_item_id}/accept": {"post"},
            "/internal/research/discovery-items/{discovery_item_id}/reject": {"post"},
            "/internal/research/discovery-items/{discovery_item_id}/requeue": {"post"},
            "/internal/research/discovery-items/{discovery_item_id}/fetch": {"post"},
        }
        # No PUT/PATCH/DELETE and no generic action endpoint anywhere.
        flattened = {method for methods in research_paths.values() for method in methods}
        assert flattened == {"get", "post"}
        assert not any(path.endswith(("/action", "/execute", "/state")) for path in research_paths)

    def test_get_on_mutation_path_is_405(self) -> None:
        harness = Harness()
        source_id = seed_source(harness, "metod")
        response = harness.request("GET", f"/internal/research/sources/{source_id}/lifecycle")
        assert response.status_code == 405

    def test_put_patch_delete_are_rejected(self) -> None:
        harness = Harness()
        for method in ("PUT", "PATCH", "DELETE"):
            response = harness.request(method, "/internal/research/sources")
            assert response.status_code == 405, method

    def test_read_endpoints_perform_no_mutation(self) -> None:
        harness = Harness()
        source_id = seed_source(harness, "salt-okur")
        seed_item(harness, source_id, "aday")

        list_response = harness.request("GET", "/internal/research/discovery-items")
        assert list_response.status_code == 200
        assert harness.dispatcher.calls == []
        with harness.session() as session:
            item = session.execute(select(DiscoveryItem)).scalar_one()
            assert item.lifecycle_state is DiscoveryLifecycleState.DISCOVERED
