"""Google Search Console + GA4 adapters and the service-account token flow."""

from datetime import date
from urllib.parse import parse_qs

import httpx
import pytest
from integrations_fixtures import (
    FAKE_ACCESS_TOKEN,
    FixedClock,
    Recorder,
    assert_no_secrets,
    integration_settings,
    json_response,
    service_account_json,
    token_response,
)

from contentos.integrations.base import ProviderError
from contentos.integrations.enums import ProviderState
from contentos.integrations.google_analytics import GoogleAnalyticsProvider
from contentos.integrations.google_auth import load_service_account
from contentos.integrations.google_search_console import GoogleSearchConsoleProvider

SITE = "https://konsepthane.net/"


def gsc_handler(rows_status: int = 200, site_status: int = 200) -> Recorder:
    def handle(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if host == "oauth2.googleapis.com":
            return token_response()
        if request.url.path.endswith("/searchAnalytics/query"):
            return json_response(
                rows_status,
                {
                    "rows": [
                        {
                            "keys": ["2026-09-01", "doğum günü pastası"],
                            "clicks": 12,
                            "impressions": 340,
                            "ctr": 0.035,
                            "position": 8.4,
                        }
                    ]
                },
            )
        return json_response(site_status, {"siteUrl": SITE, "permissionLevel": "siteFullUser"})

    return Recorder(handle)


def gsc(recorder: Recorder, **overrides: object) -> GoogleSearchConsoleProvider:
    settings = integration_settings(
        google_service_account_json=service_account_json(), gsc_site_url=SITE, **overrides
    )
    return GoogleSearchConsoleProvider(
        settings, http_client=recorder.client(), clock=FixedClock(), sleep=recorder.sleep
    )


def test_service_account_loads_from_json_content_and_path(tmp_path: object) -> None:
    from pathlib import Path

    from pydantic import SecretStr

    info = load_service_account(SecretStr(service_account_json()))
    assert info.client_email.endswith("iam.gserviceaccount.com")
    assert info.token_uri == "https://oauth2.googleapis.com/token"

    assert isinstance(tmp_path, Path)
    key_file = tmp_path / "sa.json"
    key_file.write_text(service_account_json(), encoding="utf-8")
    assert load_service_account(SecretStr(str(key_file))).project_id == "konsepthane-test"


def test_service_account_invalid_json_is_typed_error() -> None:
    from pydantic import SecretStr

    with pytest.raises(ProviderError) as info:
        load_service_account(SecretStr("{not json"))
    assert info.value.error_class == "google_service_account_invalid"
    with pytest.raises(ProviderError):
        load_service_account(SecretStr("/nonexistent/path/sa.json"))


def test_gsc_search_analytics_exchanges_jwt_then_parses_rows() -> None:
    recorder = gsc_handler()
    provider = gsc(recorder)

    rows = provider.search_analytics(
        date(2026, 9, 1), date(2026, 9, 3), ["date", "query"], page_filter=f"{SITE}parti"
    )

    assert len(rows) == 1
    row = rows[0]
    assert row.date == date(2026, 9, 1)
    assert row.query == "doğum günü pastası"
    assert row.page is None
    assert row.clicks == 12 and row.impressions == 340
    token_request, query_request = recorder.requests
    form = parse_qs(token_request.content.decode("utf-8"))
    assert form["grant_type"] == ["urn:ietf:params:oauth:grant-type:jwt-bearer"]
    assert form["assertion"][0].count(".") == 2
    assert query_request.headers["Authorization"] == f"Bearer {FAKE_ACCESS_TOKEN}"
    assert "https%3A%2F%2Fkonsepthane.net%2F" in str(query_request.url)
    body = query_request.read().decode("utf-8")
    assert '"dimensionFilterGroups"' in body


def test_gsc_token_is_cached_across_calls() -> None:
    recorder = gsc_handler()
    provider = gsc(recorder)

    provider.search_analytics(date(2026, 9, 1), date(2026, 9, 2), ["query"])
    provider.search_analytics(date(2026, 9, 1), date(2026, 9, 3), ["query"])

    hosts = [request.url.host for request in recorder.requests]
    assert hosts.count("oauth2.googleapis.com") == 1
    assert hosts.count("searchconsole.googleapis.com") == 2


def test_gsc_not_configured_without_site_url() -> None:
    settings = integration_settings(google_service_account_json=service_account_json())
    provider = GoogleSearchConsoleProvider(settings, http_client=httpx.Client())

    status = provider.test_connection()

    assert status.state is ProviderState.NOT_CONFIGURED
    assert "CONTENTOS_GSC_SITE_URL" in status.detail


def test_gsc_test_connection_healthy_and_access_required() -> None:
    healthy = gsc(gsc_handler()).test_connection()
    assert healthy.state is ProviderState.HEALTHY
    assert "siteFullUser" in healthy.detail
    assert_no_secrets(healthy.detail)

    forbidden = gsc(gsc_handler(site_status=403)).test_connection()
    assert forbidden.state is ProviderState.ACCESS_REQUIRED
    assert forbidden.last_error_class == "google_search_console_http_403"

    missing = gsc(gsc_handler(site_status=404)).test_connection()
    assert missing.state is ProviderState.ACCESS_REQUIRED
    assert "mülk" in missing.detail


def test_gsc_token_refusal_is_access_required() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return json_response(400, {"error": "invalid_grant"})

    status = gsc(Recorder(handle)).test_connection()

    assert status.state is ProviderState.ACCESS_REQUIRED
    assert status.last_error_class.startswith("google_token_") if status.last_error_class else False


def test_gsc_rate_limited_and_timeout_states() -> None:
    def limited(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            return token_response()
        return json_response(429, {}, {"Retry-After": "120"})

    recorder = Recorder(limited)
    with pytest.raises(ProviderError) as info:
        gsc(recorder).search_analytics(date(2026, 9, 1), date(2026, 9, 2), ["query"])
    assert info.value.kind is ProviderState.RATE_LIMITED
    # A Retry-After beyond the wait cap is reported, not slept.
    assert recorder.sleeps == []

    def slow(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            return token_response()
        raise httpx.ConnectTimeout("slow", request=request)

    status = gsc(Recorder(slow)).test_connection()
    assert status.state is ProviderState.DEGRADED
    assert status.last_error_class == "google_search_console_timeout"


def test_gsc_malformed_body_is_typed() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            return token_response()
        return httpx.Response(200, text="<html>")

    with pytest.raises(ProviderError) as info:
        gsc(Recorder(handle)).search_analytics(date(2026, 9, 1), date(2026, 9, 2), ["query"])
    assert info.value.error_class == "google_search_console_malformed_body"


def test_gsc_daily_budget_exhausted() -> None:
    recorder = gsc_handler()
    provider = gsc(recorder, gsc_daily_budget=1)
    provider.search_analytics(date(2026, 9, 1), date(2026, 9, 2), ["query"])
    with pytest.raises(ProviderError) as info:
        provider.search_analytics(date(2026, 9, 1), date(2026, 9, 3), ["query"])
    assert info.value.error_class == "google_search_console_daily_budget"


# --- GA4 -------------------------------------------------------------------


def ga4_handler(report_status: int = 200, metadata_status: int = 200) -> Recorder:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            return token_response()
        if request.url.path.endswith(":runReport"):
            return json_response(
                report_status,
                {
                    "dimensionHeaders": [{"name": "date"}, {"name": "pagePath"}],
                    "metricHeaders": [
                        {"name": "activeUsers"},
                        {"name": "sessions"},
                        {"name": "screenPageViews"},
                        {"name": "engagementRate"},
                        {"name": "keyEvents:newsletter_signup"},
                    ],
                    "rows": [
                        {
                            "dimensionValues": [{"value": "20260901"}, {"value": "/parti"}],
                            "metricValues": [
                                {"value": "40"},
                                {"value": "52"},
                                {"value": "90"},
                                {"value": "0.61"},
                                {"value": "3"},
                            ],
                        }
                    ],
                },
            )
        return json_response(metadata_status, {"metrics": [], "dimensions": []})

    return Recorder(handle)


def ga4(recorder: Recorder, **overrides: object) -> GoogleAnalyticsProvider:
    settings = integration_settings(
        google_service_account_json=service_account_json(),
        ga4_property_id="properties/123456",
        **overrides,
    )
    return GoogleAnalyticsProvider(
        settings, http_client=recorder.client(), clock=FixedClock(), sleep=recorder.sleep
    )


def test_ga4_run_report_maps_metrics_and_key_events_only_when_configured() -> None:
    recorder = ga4_handler()
    provider = ga4(recorder, ga4_key_events="newsletter_signup")

    rows = provider.run_report(
        date(2026, 9, 1),
        date(2026, 9, 3),
        ["date", "pagePath"],
        ["users", "sessions", "screenPageViews", "engagementRate", "keyEvents"],
        page_filter="/parti",
    )

    assert len(rows) == 1
    row = rows[0]
    assert row.date == date(2026, 9, 1)
    assert row.page == "/parti"
    assert row.users == 40 and row.sessions == 52 and row.views == 90
    assert row.engagement_rate == 0.61
    assert row.key_events == 3
    report = recorder.requests[-1]
    assert report.url.path == "/v1beta/properties/123456:runReport"
    body = report.read().decode("utf-8")
    assert '"keyEvents:newsletter_signup"' in body
    assert '"activeUsers"' in body
    assert '"EXACT"' in body


def test_ga4_key_events_unconfigured_stay_unknown() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            return token_response()
        return json_response(
            200,
            {
                "dimensionHeaders": [{"name": "pagePath"}],
                "metricHeaders": [{"name": "sessions"}],
                "rows": [{"dimensionValues": [{"value": "/x"}], "metricValues": [{"value": "5"}]}],
            },
        )

    recorder = Recorder(handle)
    rows = ga4(recorder).run_report(
        date(2026, 9, 1), date(2026, 9, 2), ["pagePath"], ["sessions", "keyEvents"]
    )

    assert rows[0].key_events is None
    assert rows[0].users is None
    assert "keyEvents" not in recorder.requests[-1].read().decode("utf-8")


def test_ga4_states() -> None:
    assert ga4(ga4_handler()).test_connection().state is ProviderState.HEALTHY
    forbidden = ga4(ga4_handler(metadata_status=403)).test_connection()
    assert forbidden.state is ProviderState.ACCESS_REQUIRED
    assert forbidden.last_error_class == "google_analytics_http_403"

    unconfigured = GoogleAnalyticsProvider(integration_settings(), http_client=httpx.Client())
    assert unconfigured.test_connection().state is ProviderState.NOT_CONFIGURED

    def failing(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            return token_response()
        return json_response(503, {})

    recorder = Recorder(failing)
    degraded = ga4(recorder).test_connection()
    assert degraded.state is ProviderState.DEGRADED
    assert degraded.last_error_class == "google_analytics_http_503"
    assert recorder.sleeps == [0.5, 1.0]


def test_ga4_cache_and_budget() -> None:
    recorder = ga4_handler()
    provider = ga4(recorder, ga4_daily_budget=1)
    provider.run_report(date(2026, 9, 1), date(2026, 9, 2), ["date"], ["sessions"])
    provider.run_report(date(2026, 9, 1), date(2026, 9, 2), ["date"], ["sessions"])
    assert [r.url.host for r in recorder.requests].count("analyticsdata.googleapis.com") == 1
    with pytest.raises(ProviderError) as info:
        provider.run_report(date(2026, 9, 1), date(2026, 9, 5), ["date"], ["sessions"])
    assert info.value.error_class == "google_analytics_daily_budget"
