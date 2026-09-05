"""Semrush adapter: parsing, typed states, budget/cache behaviour."""

import httpx
import pytest
from integrations_fixtures import (
    FAKE_SEMRUSH_KEY,
    FixedClock,
    Recorder,
    assert_no_secrets,
    integration_settings,
    text_response,
    timeout_raiser,
)

from contentos.integrations.base import ProviderError
from contentos.integrations.enums import ProviderName, ProviderState
from contentos.integrations.semrush import (
    API_URL,
    UNITS_URL,
    SemrushProvider,
    parse_table,
    semrush_error,
)

OVERVIEW_BODY = (
    "Keyword;Search Volume;CPC;Competition;Keyword Difficulty;Intent\n"
    "doğum günü pastası;12100;0.45;0.12;38.5;1\n"
    "parti süsleri;;;;;\n"
)


def provider(recorder: Recorder, **overrides: object) -> SemrushProvider:
    settings = integration_settings(semrush_api_key=FAKE_SEMRUSH_KEY, **overrides)
    return SemrushProvider(
        settings, http_client=recorder.client(), clock=FixedClock(), sleep=recorder.sleep
    )


def test_parse_table_pads_short_rows_and_maps_headers() -> None:
    rows = parse_table(OVERVIEW_BODY)

    assert rows[0]["Keyword"] == "doğum günü pastası"
    assert rows[0]["Search Volume"] == "12100"
    assert rows[1]["Search Volume"] == ""


def test_error_codes_map_to_typed_states() -> None:
    assert semrush_error("ERROR 50 :: NOTHING FOUND") is None
    limit = semrush_error("ERROR 132 :: API UNITS BALANCE IS ZERO")
    assert limit is not None and limit.kind is ProviderState.RATE_LIMITED
    assert limit.error_class == "semrush_api_132"
    auth = semrush_error("ERROR 120 :: WRONG KEY - ID PAIR")
    assert auth is not None and auth.kind is ProviderState.ACCESS_REQUIRED
    other = semrush_error("ERROR 40 :: MANDATORY PARAMETER phrase MISSED")
    assert other is not None and other.kind is ProviderState.ERROR


def test_keyword_overview_parses_metrics_and_keeps_unknown_as_none() -> None:
    recorder = Recorder(lambda request: text_response(200, OVERVIEW_BODY))
    semrush = provider(recorder)

    metrics = semrush.keyword_overview(["doğum günü pastası", "parti süsleri", "Parti Süsleri"])

    assert len(metrics) == 2
    first = metrics[0]
    assert first.search_volume == 12100
    assert first.keyword_difficulty == 38.5
    assert first.cpc == 0.45
    assert first.competition == 0.12
    assert first.intent == "informational"
    assert first.database == "tr"
    second = metrics[1]
    assert second.search_volume is None and second.keyword_difficulty is None
    request = recorder.requests[0]
    assert str(request.url).startswith(API_URL)
    assert request.url.params["type"] == "phrase_these"
    assert request.url.params["database"] == "tr"
    # Deduplicated (case-insensitive), joined with ';'.
    assert request.url.params["phrase"] == "doğum günü pastası;parti süsleri"


def test_cache_hit_avoids_second_request_and_counts_one_budget_unit() -> None:
    recorder = Recorder(lambda request: text_response(200, OVERVIEW_BODY))
    semrush = provider(recorder)

    semrush.keyword_overview(["doğum günü pastası"])
    semrush.keyword_overview(["doğum günü pastası"])

    assert len(recorder.requests) == 1
    assert semrush.cost.requests_today() == 1


def test_daily_budget_exhaustion_is_rate_limited() -> None:
    recorder = Recorder(lambda request: text_response(200, OVERVIEW_BODY))
    semrush = provider(recorder, semrush_daily_budget=1)

    semrush.keyword_overview(["a"])
    with pytest.raises(ProviderError) as info:
        semrush.keyword_overview(["b"])

    assert info.value.kind is ProviderState.RATE_LIMITED
    assert info.value.error_class == "semrush_daily_budget"
    assert len(recorder.requests) == 1


def test_not_configured_status_names_env_without_calling() -> None:
    recorder = Recorder(lambda request: text_response(200, "1"))
    semrush = SemrushProvider(integration_settings(), http_client=recorder.client())

    status = semrush.test_connection()

    assert not semrush.configured()
    assert status.state is ProviderState.NOT_CONFIGURED
    assert "CONTENTOS_SEMRUSH_API_KEY" in status.detail
    assert recorder.requests == []


def test_test_connection_reads_remaining_units() -> None:
    recorder = Recorder(lambda request: text_response(200, "123456"))
    semrush = provider(recorder)

    status = semrush.test_connection()

    assert status.state is ProviderState.HEALTHY
    assert "123456" in status.detail
    assert str(recorder.requests[0].url).startswith(UNITS_URL)
    assert_no_secrets(status.detail)


def test_http_401_is_access_required() -> None:
    recorder = Recorder(lambda request: text_response(401, "unauthorized"))
    status = provider(recorder).test_connection()

    assert status.state is ProviderState.ACCESS_REQUIRED
    assert status.last_error_class == "semrush_http_401"


def test_api_error_body_on_test_maps_to_state() -> None:
    recorder = Recorder(lambda request: text_response(200, "ERROR 121 :: WRONG KEY"))
    status = provider(recorder).test_connection()

    assert status.state is ProviderState.ACCESS_REQUIRED
    assert status.last_error_class == "semrush_api_121"


def test_429_with_retry_after_backs_off_then_reports_rate_limited() -> None:
    recorder = Recorder(lambda request: text_response(429, "slow", {"Retry-After": "2"}))
    semrush = provider(recorder)

    with pytest.raises(ProviderError) as info:
        semrush.related_keywords("parti")

    assert info.value.kind is ProviderState.RATE_LIMITED
    assert info.value.retry_after_seconds == 2.0
    assert recorder.sleeps == [2.0, 2.0]
    assert len(recorder.requests) == 3


def test_timeout_is_degraded_with_bounded_class() -> None:
    recorder = Recorder(timeout_raiser)
    semrush = provider(recorder)

    with pytest.raises(ProviderError) as info:
        semrush.domain_organic("konsepthane.net")

    assert info.value.kind is ProviderState.DEGRADED
    assert info.value.error_class == "semrush_timeout"
    assert len(recorder.requests) == 3


def test_malformed_body_yields_empty_result_not_numbers() -> None:
    recorder = Recorder(lambda request: text_response(200, "<html>oops</html>"))
    metrics = provider(recorder).keyword_overview(["parti"])

    assert metrics == []


def test_related_and_domain_are_bounded() -> None:
    body = "Keyword;Search Volume;Keyword Difficulty\n" + "\n".join(
        f"k{i};{i * 10};{i}" for i in range(1, 40)
    )
    recorder = Recorder(lambda request: text_response(200, body))
    semrush = provider(recorder)

    related = semrush.related_keywords("parti", limit=5)

    assert len(related) == 5
    assert related[0].search_volume == 10
    assert recorder.requests[0].url.params["display_limit"] == "5"


def test_unconfigured_call_raises_typed_not_configured() -> None:
    semrush = SemrushProvider(integration_settings(), http_client=httpx.Client())
    with pytest.raises(ProviderError) as info:
        semrush.keyword_overview(["x"])
    assert info.value.kind is ProviderState.NOT_CONFIGURED
    assert semrush.name is ProviderName.SEMRUSH
