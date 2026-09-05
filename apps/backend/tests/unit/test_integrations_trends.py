"""Google Trends (official API only) and Pinterest Trends adapters."""

from datetime import date, timedelta

import httpx
import pytest
from integrations_fixtures import (
    FAKE_PINTEREST_TOKEN,
    FAKE_TRENDS_KEY,
    FixedClock,
    Recorder,
    assert_no_secrets,
    integration_settings,
    json_response,
    timeout_raiser,
)

from contentos.integrations.base import ProviderError
from contentos.integrations.dto import trend_direction
from contentos.integrations.enums import ProviderState
from contentos.integrations.google_trends import GoogleTrendsProvider
from contentos.integrations.pinterest_trends import PinterestTrendsProvider


def weekly_points(values: list[float]) -> list[dict[str, object]]:
    start = date(2026, 1, 4)
    return [
        {"date": (start + timedelta(weeks=index)).isoformat(), "value": value}
        for index, value in enumerate(values)
    ]


def trends(recorder: Recorder, **overrides: object) -> GoogleTrendsProvider:
    settings = integration_settings(google_trends_api_key=FAKE_TRENDS_KEY, **overrides)
    return GoogleTrendsProvider(
        settings, http_client=recorder.client(), clock=FixedClock(), sleep=recorder.sleep
    )


def test_trend_direction_windows() -> None:
    assert trend_direction([10.0] * 12 + [20.0] * 12) == "rising"
    assert trend_direction([20.0] * 12 + [10.0] * 12) == "falling"
    assert trend_direction([20.0] * 12 + [21.0] * 12) == "stable"
    assert trend_direction([5.0] * 10) == "unknown"


def test_google_trends_without_key_is_access_required_and_never_calls() -> None:
    recorder = Recorder(lambda request: json_response(200, {}))
    provider = GoogleTrendsProvider(integration_settings(), http_client=recorder.client())

    status = provider.test_connection()

    assert not provider.configured()
    assert status.state is ProviderState.ACCESS_REQUIRED
    assert status.detail.startswith("Google Trends API erişimi gerekli (resmi API alfa/izinli)")
    assert recorder.requests == []
    with pytest.raises(ProviderError) as info:
        provider.interest_over_time(["parti"])
    assert info.value.kind is ProviderState.ACCESS_REQUIRED


def test_google_trends_series_and_summary_use_relative_values() -> None:
    values = [30.0] * 12 + [60.0] * 12
    recorder = Recorder(
        lambda request: json_response(
            200, {"series": [{"term": "doğum günü", "points": weekly_points(values)}]}
        )
    )
    provider = trends(recorder, google_trends_api_url="https://trends.example.test/v1beta/")

    series = provider.interest_over_time(["doğum günü"], geo="tr")
    summary = provider.summary("doğum günü", "TR")

    assert series[0].relative is True
    assert len(series[0].points) == 24
    assert series[0].points[0].period == date(2026, 1, 4)
    assert summary.direction == "rising"
    assert summary.geo == "TR"
    assert summary.provider == "google_trends"
    request = recorder.requests[0]
    assert str(request.url).startswith("https://trends.example.test/v1beta/interestOverTime")
    assert request.headers["X-Goog-Api-Key"] == FAKE_TRENDS_KEY
    assert FAKE_TRENDS_KEY not in str(request.url)
    # summary reused the cached series: one vendor call in total.
    assert len(recorder.requests) == 1


def test_google_trends_timeline_shape_is_accepted() -> None:
    body = {
        "terms": ["parti"],
        "timelineData": [
            {"time": "1767484800", "value": [40]},
            {"date": "2026-01-11", "value": [55]},
        ],
    }
    provider = trends(Recorder(lambda request: json_response(200, body)))

    series = provider.interest_over_time(["parti"])

    assert series[0].term == "parti"
    assert [point.value for point in series[0].points] == [40.0, 55.0]


def test_google_trends_states() -> None:
    forbidden = trends(Recorder(lambda request: json_response(403, {}))).test_connection()
    assert forbidden.state is ProviderState.ACCESS_REQUIRED
    assert forbidden.last_error_class == "google_trends_http_403"

    limited = Recorder(lambda request: json_response(429, {}, {"Retry-After": "1"}))
    status = trends(limited).test_connection()
    assert status.state is ProviderState.RATE_LIMITED
    assert limited.sleeps == [1.0, 1.0]

    slow = trends(Recorder(timeout_raiser)).test_connection()
    assert slow.state is ProviderState.DEGRADED
    assert slow.last_error_class == "google_trends_timeout"

    malformed = trends(Recorder(lambda request: httpx.Response(200, text="nope")))
    assert malformed.test_connection().last_error_class == "google_trends_malformed_body"

    empty = trends(Recorder(lambda request: json_response(200, {"unexpected": 1})))
    assert empty.summary("parti").direction == "unknown"

    budget = trends(
        Recorder(lambda request: json_response(200, {"series": []})), google_trends_daily_budget=1
    )
    budget.interest_over_time(["a"])
    with pytest.raises(ProviderError) as info:
        budget.interest_over_time(["b"])
    assert info.value.error_class == "google_trends_daily_budget"


# --- Pinterest --------------------------------------------------------------


PINTEREST_BODY = {
    "trends": [
        {
            "keyword": "doğum günü süsleri",
            "pct_growth_wow": 12.5,
            "pct_growth_yoy": 40.0,
            "pct_growth_mom": 5.0,
            "time_series": {
                "date": ["2026-08-02", "2026-08-09", "bad", "2026-08-16"],
                "index": [10, 12, 13, True],
            },
        },
        {"keyword": "", "pct_growth_wow": 1},
        {"keyword": "parti pastası", "pct_growth_wow": None, "pct_growth_yoy": 8.25},
    ]
}


def pinterest(recorder: Recorder, **overrides: object) -> PinterestTrendsProvider:
    settings = integration_settings(pinterest_access_token=FAKE_PINTEREST_TOKEN, **overrides)
    return PinterestTrendsProvider(
        settings, http_client=recorder.client(), clock=FixedClock(), sleep=recorder.sleep
    )


def test_pinterest_without_token_is_access_required() -> None:
    recorder = Recorder(lambda request: json_response(200, PINTEREST_BODY))
    provider = PinterestTrendsProvider(integration_settings(), http_client=recorder.client())

    status = provider.test_connection()

    assert status.state is ProviderState.ACCESS_REQUIRED
    assert "CONTENTOS_PINTEREST_ACCESS_TOKEN" in status.detail
    assert "trends:read" in status.detail
    assert recorder.requests == []


def test_pinterest_top_trends_parse_official_shape() -> None:
    recorder = Recorder(lambda request: json_response(200, PINTEREST_BODY))
    provider = pinterest(recorder)

    result = provider.top_trends(region="TR", trend_type="growing", limit=10)

    assert [trend.keyword for trend in result] == ["doğum günü süsleri", "parti pastası"]
    first = result[0]
    assert first.growth_pct_wow == 12.5 and first.growth_pct_yoy == 40.0
    assert [point.value for point in first.weekly_points] == [10.0, 12.0]
    assert first.region == "TR"
    assert result[1].growth_pct_wow is None and result[1].growth_pct_yoy == 8.25
    request = recorder.requests[0]
    assert request.url.path == "/v5/trends/keywords/TR/top/growing"
    assert request.headers["Authorization"] == f"Bearer {FAKE_PINTEREST_TOKEN}"
    assert request.url.params["limit"] == "10"


def test_pinterest_keyword_trend_filters_by_keyword() -> None:
    recorder = Recorder(lambda request: json_response(200, PINTEREST_BODY))
    provider = pinterest(recorder)

    found = provider.keyword_trend("Parti Pastası", region="TR")
    missing = provider.keyword_trend("yok böyle", region="TR")

    assert found is not None and found.keyword == "parti pastası"
    assert missing is None
    assert recorder.requests[0].url.params["include_keywords"] == "Parti Pastası"
    assert recorder.requests[0].url.path == "/v5/trends/keywords/TR/top/monthly"


def test_pinterest_states() -> None:
    healthy = pinterest(Recorder(lambda request: json_response(200, PINTEREST_BODY)))
    status = healthy.test_connection()
    assert status.state is ProviderState.HEALTHY
    assert_no_secrets(status.detail)

    unauthorized = pinterest(
        Recorder(lambda request: json_response(401, {"code": 2}))
    ).test_connection()
    assert unauthorized.state is ProviderState.ACCESS_REQUIRED
    assert unauthorized.last_error_class == "pinterest_trends_http_401"

    limited = Recorder(lambda request: json_response(429, {}, {"Retry-After": "3"}))
    assert pinterest(limited).test_connection().state is ProviderState.RATE_LIMITED
    assert limited.sleeps == [3.0, 3.0]

    slow = pinterest(Recorder(timeout_raiser)).test_connection()
    assert (
        slow.state is ProviderState.DEGRADED and slow.last_error_class == "pinterest_trends_timeout"
    )

    malformed = pinterest(Recorder(lambda request: json_response(200, {"items": []})))
    assert malformed.test_connection().last_error_class == "pinterest_trends_malformed_body"


def test_pinterest_cache_hit_and_budget() -> None:
    recorder = Recorder(lambda request: json_response(200, PINTEREST_BODY))
    provider = pinterest(recorder, pinterest_daily_budget=1)

    provider.top_trends()
    provider.top_trends()
    assert len(recorder.requests) == 1
    with pytest.raises(ProviderError) as info:
        provider.top_trends(trend_type="yearly")
    assert info.value.kind is ProviderState.RATE_LIMITED
    assert info.value.error_class == "pinterest_trends_daily_budget"
