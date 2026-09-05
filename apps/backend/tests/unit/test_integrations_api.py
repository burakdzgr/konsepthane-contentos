"""Registry statuses/tests through the real API over the editorial harness."""

import httpx
from editorial_harness import Harness, api_settings
from integrations_fixtures import (
    FAKE_PINTEREST_TOKEN,
    FAKE_SEMRUSH_KEY,
    FixedClock,
    Recorder,
    assert_no_secrets,
    json_response,
    text_response,
)
from pydantic import SecretStr

from contentos.integrations.enums import ProviderName, ProviderState
from contentos.integrations.models import IntegrationStatusRecord
from contentos.integrations.registry import (
    IntegrationRegistry,
    UnknownProviderError,
    create_integration_registry,
)

PROVIDER_ORDER = [
    "semrush",
    "google_search_console",
    "google_analytics",
    "google_trends",
    "pinterest_trends",
]


def harness_with(recorder: Recorder, **overrides: object) -> tuple[Harness, IntegrationRegistry]:
    harness = Harness()
    settings = api_settings().model_copy(update=overrides)
    harness.app.state.settings = settings
    registry = IntegrationRegistry(
        settings,
        harness.session_factory,
        http_client=recorder.client(),
        clock=FixedClock(),
        sleep=recorder.sleep,
    )
    harness.app.state.integration_registry = registry
    return harness, registry


def semrush_handler(request: httpx.Request) -> httpx.Response:
    if request.url.host == "www.semrush.com":
        return text_response(200, "4242")
    return text_response(200, "Keyword;Search Volume\nparti;100\n")


def test_list_reports_honest_states_without_calling_any_vendor() -> None:
    recorder = Recorder(semrush_handler)
    harness, _registry = harness_with(recorder)

    response = harness.get("/internal/integrations")

    assert response.status_code == 200, response.text
    payload = response.json()
    providers = {item["name"]: item for item in payload["providers"]}
    assert list(providers) == PROVIDER_ORDER
    assert providers["semrush"]["state"] == "not_configured"
    assert providers["semrush"]["configured"] is False
    assert providers["semrush"]["verified"] is False
    assert "CONTENTOS_SEMRUSH_API_KEY" in providers["semrush"]["detail"]
    assert providers["semrush"]["required_env"] == ["CONTENTOS_SEMRUSH_API_KEY"]
    assert providers["semrush"]["daily_budget"] == 200
    assert providers["semrush"]["requests_today"] == 0
    assert providers["semrush"]["cache_hours"] == 72
    assert providers["semrush"]["freshness"] is None
    assert providers["google_trends"]["state"] == "access_required"
    assert providers["pinterest_trends"]["state"] == "access_required"
    assert providers["google_search_console"]["display_name"] == "Google Search Console"
    assert providers["google_analytics"]["display_name"] == "Google Analytics 4"
    assert recorder.requests == []


def test_configured_but_untested_provider_is_unverified() -> None:
    recorder = Recorder(semrush_handler)
    harness, _registry = harness_with(recorder, semrush_api_key=SecretStr(FAKE_SEMRUSH_KEY))

    payload = harness.get("/internal/integrations").json()
    semrush = payload["providers"][0]

    assert semrush["configured"] is True
    assert semrush["verified"] is False
    assert semrush["state"] == "degraded"
    assert "doğrulanmadı" in semrush["detail"]
    assert recorder.requests == []


def test_test_endpoint_runs_one_call_persists_and_counts_budget() -> None:
    recorder = Recorder(semrush_handler)
    harness, registry = harness_with(recorder, semrush_api_key=SecretStr(FAKE_SEMRUSH_KEY))

    response = harness.post("/internal/integrations/semrush/test")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "healthy"
    assert body["verified"] is True
    assert body["last_success_at"] is not None
    assert body["requests_today"] == 1
    assert "4242" in body["detail"]
    assert_no_secrets(response.text)
    assert len(recorder.requests) == 1

    listed = harness.get("/internal/integrations").json()["providers"][0]
    assert listed["state"] == "healthy"
    assert listed["verified"] is True
    assert listed["requests_today"] == 1
    assert_no_secrets(harness.get("/internal/integrations").text)

    with harness.session() as session:
        row = session.get(IntegrationStatusRecord, "semrush")
        assert row is not None and row.state is ProviderState.HEALTHY
        assert row.last_error_class is None
        registry.record_error(
            session, ProviderName.SEMRUSH, "semrush_http_500", kind=ProviderState.DEGRADED
        )
        session.commit()
    degraded = harness.get("/internal/integrations").json()["providers"][0]
    assert degraded["state"] == "degraded"
    assert degraded["last_error_class"] == "semrush_http_500"
    assert degraded["last_success_at"] is not None
    with harness.session() as session:
        registry.record_success(session, ProviderName.SEMRUSH)
        session.commit()
    synced = harness.get("/internal/integrations").json()["providers"][0]
    assert synced["state"] == "healthy"
    assert synced["freshness"] is not None


def test_test_endpoint_persists_access_required_with_bounded_class() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        return json_response(401, {"message": "bad token", "token": FAKE_PINTEREST_TOKEN})

    recorder = Recorder(refuse)
    harness, _registry = harness_with(
        recorder, pinterest_access_token=SecretStr(FAKE_PINTEREST_TOKEN)
    )

    response = harness.post("/internal/integrations/pinterest_trends/test")

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "access_required"
    assert body["last_error_class"] == "pinterest_trends_http_401"
    assert body["last_success_at"] is None
    assert_no_secrets(response.text)


def test_test_endpoint_for_unconfigured_provider_does_not_persist_or_call() -> None:
    recorder = Recorder(semrush_handler)
    harness, _registry = harness_with(recorder)

    response = harness.post("/internal/integrations/google_search_console/test")

    assert response.status_code == 200
    assert response.json()["state"] == "not_configured"
    assert response.json()["verified"] is False
    assert recorder.requests == []


def test_unknown_provider_is_404() -> None:
    harness, registry = harness_with(Recorder(semrush_handler))
    assert harness.post("/internal/integrations/bing/test").status_code == 404
    try:
        registry.get("bing")
    except UnknownProviderError:
        pass
    else:  # pragma: no cover - guard
        raise AssertionError("expected UnknownProviderError")


def test_create_integration_registry_builds_all_providers_lazily() -> None:
    registry = create_integration_registry(api_settings())
    assert [provider.name.value for provider in registry.providers()] == PROVIDER_ORDER
    assert registry.get(ProviderName.SEMRUSH).display_name == "Semrush"
    assert registry.get("google_analytics").configured() is False
