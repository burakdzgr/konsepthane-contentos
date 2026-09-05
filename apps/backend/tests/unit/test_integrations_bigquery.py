"""Google Trends — BigQuery Public Dataset: provider, dedup, persistence,
discovery matching, the daily task, opportunity enrichment and the API.

The transport is scripted httpx: the service-account token exchange and
BigQuery `jobs.query` answer as the vendor would. No test invents a trend:
a term absent from the sets is asserted NOT_OBSERVED / UNKNOWN, never
"low", and every persisted value names the dataset, table and refresh date.
"""

import json
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest
from editorial_harness import Context, Harness, api_settings, seed_scored
from integrations_fixtures import (
    FixedClock,
    Recorder,
    assert_no_secrets,
    integration_settings,
    json_response,
    service_account_json,
    token_response,
)
from sqlalchemy import select

from contentos.inspiration.enrichment import (
    DISCOVERY_NOT_OBSERVED,
    DISCOVERY_OBSERVED,
    DISCOVERY_UNKNOWN,
    STATE_NOT_REQUESTED,
    STATE_STORED,
    enrich_opportunity,
)
from contentos.inspiration.enums import TrendState
from contentos.inspiration.service import InspirationIntelligenceService
from contentos.integrations.base import ProviderError
from contentos.integrations.dto import TrendTermObservation, TrendTermRegion
from contentos.integrations.enums import ProviderState
from contentos.integrations.google_trends_bigquery import (
    DATASET,
    QUERY_VERSION,
    RISING_TABLE,
    TOP_TABLE,
    GoogleTrendsBigQueryProvider,
    aggregate_terms,
    parse_rows,
)
from contentos.integrations.models import IntegrationStatusRecord
from contentos.integrations.observations import (
    record_trend_term_observations,
    trend_terms_synced_for,
)
from contentos.integrations.registry import IntegrationRegistry
from contentos.intelligence.enums import SignalFamily
from contentos.intelligence.models import IntelligenceSignal
from contentos.intelligence.trend_discovery import (
    discovery_snapshot,
    domain_terms_for,
    match_observation,
    record_trend_discoveries,
)
from contentos.queue.celery import create_celery_app
from contentos.signals.models import SearchSignal
from contentos.strategy.service import StrategyService
from contentos.worker.main import create_worker_app
from contentos.worker.runtime import WorkerRuntime
from contentos.worker.trend_discovery_tasks import (
    SYNC_GOOGLE_TRENDS_BIGQUERY_TASK,
    TrendDiscoverySyncRunner,
    trend_discovery_beat_schedule,
)

NOW = datetime(2026, 9, 5, 10, 0, tzinfo=UTC)
REFRESH = date(2026, 9, 3)
PROJECT = "konsepthane-test-project"
PRIMARY = "doğum günü partisi"

TERMS_SCHEMA = [
    ("term", "STRING"),
    ("region_code", "STRING"),
    ("region_name", "STRING"),
    ("rank", "INTEGER"),
    ("latest_score", "INTEGER"),
    ("peak_score", "INTEGER"),
    ("percent_gain", "INTEGER"),
    ("weeks_with_score", "INTEGER"),
    ("first_week", "DATE"),
    ("last_week", "DATE"),
]

TOP_ROWS: list[list[Any]] = [
    ["galatasaray", "TR-34", "Istanbul", 1, 100, 100, None, 52, "2025-09-07", "2026-08-30"],
    ["doğum günü", "TR-34", "Istanbul", 3, 61, 88, None, 52, "2025-09-07", "2026-08-30"],
    ["doğum günü", "TR-06", "Ankara", 5, 44, 70, None, 51, "2025-09-14", "2026-08-30"],
    ["hava durumu", "TR-35", "Izmir", 2, None, 90, None, 50, "2025-09-07", "2026-08-23"],
]
RISING_ROWS: list[list[Any]] = [
    ["ayıcıklı doğum günü", "TR-34", "Istanbul", 2, 70, 70, 250, 3, "2026-08-16", "2026-08-30"],
    ["ayıcıklı doğum günü", "TR-16", "Bursa", 4, 55, 55, 180, 3, "2026-08-16", "2026-08-30"],
    ["yeni telefon", "TR-34", "Istanbul", 1, 90, 90, 900, 2, "2026-08-23", "2026-08-30"],
]


def bq_payload(
    schema: list[tuple[str, str]], records: list[list[Any]], **extra: Any
) -> dict[str, Any]:
    return {
        "kind": "bigquery#queryResponse",
        "jobComplete": True,
        "schema": {"fields": [{"name": name, "type": kind} for name, kind in schema]},
        "rows": [
            {"f": [{"v": None if v is None else str(v)} for v in record]} for record in records
        ],
        "totalRows": str(len(records)),
        "totalBytesProcessed": "12345678",
        "cacheHit": False,
        **extra,
    }


def latest_payload(value: date | None) -> dict[str, Any]:
    return bq_payload([("refresh_date", "DATE")], [[value.isoformat() if value else None]])


Handler = Callable[[httpx.Request], httpx.Response]


def partitions_payload(dates: list[date]) -> dict[str, Any]:
    return bq_payload([("partition_id", "STRING")], [[d.strftime("%Y%m%d")] for d in dates])


def bigquery(
    *,
    latest: date | None = REFRESH,
    top: list[list[Any]] | None = None,
    rising: list[list[Any]] | None = None,
    fail: Handler | None = None,
    metadata_fail: Handler | None = None,
    partitions: list[date] | None = None,
) -> Recorder:
    def handle(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if host == "oauth2.googleapis.com":
            return token_response()
        assert host == "bigquery.googleapis.com", host
        if fail is not None:
            return fail(request)
        body = json.loads(request.content)
        query = body["query"]
        if "INFORMATION_SCHEMA.PARTITIONS" in query:
            if metadata_fail is not None:
                return metadata_fail(request)
            listed = partitions if partitions is not None else ([latest] if latest else [])
            return json_response(200, partitions_payload(listed))
        if "MAX(refresh_date)" in query:
            if "refresh_date = DATE" in query:
                wanted = query.split("DATE '")[1][:10]
                return json_response(
                    200, latest_payload(latest if latest and latest.isoformat() == wanted else None)
                )
            return json_response(200, latest_payload(latest))
        if RISING_TABLE in query:
            return json_response(
                200, bq_payload(TERMS_SCHEMA, rising if rising is not None else RISING_ROWS)
            )
        return json_response(200, bq_payload(TERMS_SCHEMA, top if top is not None else TOP_ROWS))

    return Recorder(handle)


def provider(recorder: Recorder, **overrides: Any) -> GoogleTrendsBigQueryProvider:
    settings = integration_settings(
        google_service_account_json=service_account_json(),
        google_cloud_project_id=PROJECT,
        **overrides,
    )
    return GoogleTrendsBigQueryProvider(
        settings, http_client=recorder.client(), clock=FixedClock(NOW), sleep=recorder.sleep
    )


def registry(
    recorder: Recorder, harness: Harness | None = None, **overrides: Any
) -> IntegrationRegistry:
    settings = integration_settings(
        google_service_account_json=service_account_json(),
        google_cloud_project_id=PROJECT,
        **overrides,
    )
    return IntegrationRegistry(
        settings,
        harness.session_factory if harness is not None else None,
        http_client=recorder.client(),
        clock=FixedClock(NOW),
        sleep=recorder.sleep,
    )


def query_bodies(recorder: Recorder) -> list[dict[str, Any]]:
    return [
        json.loads(request.content)
        for request in recorder.requests
        if request.url.host == "bigquery.googleapis.com"
    ]


def observation(
    term: str,
    *,
    trend_type: str = "rising",
    rank: int | None = 2,
    percent_gain: float | None = 250.0,
    refresh: date = REFRESH,
    regions: int = 2,
) -> TrendTermObservation:
    return TrendTermObservation(
        term=term,
        country_code="TR",
        refresh_date=refresh,
        trend_type=trend_type,
        rank=rank,
        latest_score=70.0,
        peak_score=70.0,
        percent_gain=percent_gain,
        region_count=regions,
        regions=tuple(
            TrendTermRegion(f"TR-{index}", f"Region {index}", rank, 70.0, percent_gain)
            for index in range(regions)
        ),
        first_week=date(2026, 8, 16),
        last_week=date(2026, 8, 30),
        weeks_with_score=3,
        dataset=DATASET,
        table=RISING_TABLE if trend_type == "rising" else TOP_TABLE,
        query_version=QUERY_VERSION,
        observed_at=NOW,
    )


@pytest.fixture()
def harness() -> Harness:
    return Harness()


# --- provider -------------------------------------------------------------------


class TestProvider:
    def test_without_service_account_is_not_configured_and_never_calls(self) -> None:
        recorder = bigquery()
        adapter = GoogleTrendsBigQueryProvider(
            integration_settings(), http_client=recorder.client(), clock=FixedClock(NOW)
        )

        status = adapter.test_connection()

        assert not adapter.configured()
        assert status.state is ProviderState.NOT_CONFIGURED
        assert "CONTENTOS_GOOGLE_SERVICE_ACCOUNT_JSON" in status.detail
        assert recorder.requests == []

    def test_connection_test_runs_one_bounded_partition_probe(self) -> None:
        recorder = bigquery()
        adapter = provider(recorder)

        status = adapter.test_connection()

        assert status.state is ProviderState.HEALTHY, status.detail
        assert "2026-09-03" in status.detail
        assert "24.7 MB" in status.detail  # metadata + one partition check
        bodies = query_bodies(recorder)
        assert len(bodies) == 2
        listing = bodies[0]["query"]
        assert "INFORMATION_SCHEMA.PARTITIONS" in listing
        assert "LIMIT 14" in listing
        assert bodies[0]["queryParameters"][0]["parameterValue"]["value"] == TOP_TABLE
        body = bodies[1]
        query = body["query"]
        assert "SELECT *" not in query
        assert "country_code = @country" in query
        assert "refresh_date = DATE '2026-09-03'" in query
        assert "DATE_SUB" not in query
        assert f"`{DATASET}.{TOP_TABLE}`" in query
        assert body["useLegacySql"] is False
        assert body["useQueryCache"] is True
        assert body["maximumBytesBilled"] == "2000000000"
        assert body["queryParameters"] == [
            {
                "name": "country",
                "parameterType": {"type": "STRING"},
                "parameterValue": {"value": "TR"},
            }
        ]
        request = next(r for r in recorder.requests if r.url.host == "bigquery.googleapis.com")
        assert request.url.path == f"/bigquery/v2/projects/{PROJECT}/queries"
        assert request.headers["Authorization"].startswith("Bearer ")
        assert_no_secrets(status.detail)

    def test_latest_partition_skips_days_without_country_rows(self) -> None:
        newer = REFRESH + timedelta(days=1)
        recorder = bigquery(
            latest=REFRESH, partitions=[newer, REFRESH, REFRESH - timedelta(days=1)]
        )
        adapter = provider(recorder)

        assert adapter.latest_refresh_date() == REFRESH
        bodies = query_bodies(recorder)
        assert len(bodies) == 3  # metadata, newest (empty for TR), then the hit
        assert f"DATE '{newer.isoformat()}'" in bodies[1]["query"]
        assert "DATE '2026-09-03'" in bodies[2]["query"]

    def test_stale_partitions_outside_the_window_are_not_queried(self) -> None:
        old = REFRESH - timedelta(days=40)
        recorder = bigquery(latest=old, partitions=[old])
        adapter = provider(recorder)

        assert adapter.latest_refresh_date() is None
        assert len(query_bodies(recorder)) == 1  # metadata only

    def test_metadata_unavailable_falls_back_to_the_bounded_probe(self) -> None:
        recorder = bigquery(
            metadata_fail=lambda request: json_response(400, {"error": {"code": 400}})
        )
        adapter = provider(recorder)

        assert adapter.latest_refresh_date() == REFRESH
        bodies = query_bodies(recorder)
        assert len(bodies) == 2
        assert "DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)" in bodies[1]["query"]
        assert "country_code = @country" in bodies[1]["query"]

    def test_project_id_falls_back_to_the_key_file(self) -> None:
        recorder = bigquery()
        settings = integration_settings(
            google_service_account_json=service_account_json(project_id="key-project")
        )
        adapter = GoogleTrendsBigQueryProvider(
            settings, http_client=recorder.client(), clock=FixedClock(NOW)
        )

        assert adapter.project_id() == "key-project"
        assert adapter.test_connection().state is ProviderState.HEALTHY

    def test_access_refused_names_the_minimum_iam_role(self) -> None:
        recorder = bigquery(fail=lambda request: json_response(403, {"error": {"code": 403}}))
        status = provider(recorder).test_connection()

        assert status.state is ProviderState.ACCESS_REQUIRED
        assert "BigQuery Job User" in status.detail
        assert status.last_error_class == "google_trends_bigquery_http_403"

    def test_incomplete_job_is_degraded_not_an_outage(self) -> None:
        recorder = bigquery(
            fail=lambda request: json_response(200, {"jobComplete": False, "jobReference": {}})
        )
        status = provider(recorder).test_connection()

        assert status.state is ProviderState.DEGRADED
        assert status.last_error_class == "google_trends_bigquery_query_incomplete"
        assert "senkron yine de" in status.detail

    def test_no_recent_partition_is_healthy_and_honest(self) -> None:
        recorder = bigquery(latest=None)
        adapter = provider(recorder)

        status = adapter.test_connection()
        assert status.state is ProviderState.HEALTHY
        assert "yayınlanmamış" in status.detail
        assert adapter.latest_refresh_date() is None

    def test_terms_are_partition_bound_and_aggregated_per_term(self) -> None:
        recorder = bigquery()
        adapter = provider(recorder)

        top = adapter.top_terms(REFRESH)
        rising = adapter.rising_terms(REFRESH, "tr")

        top_query = query_bodies(recorder)[0]["query"]
        assert "refresh_date = DATE '2026-09-03'" in top_query
        assert "country_code = @country" in top_query
        assert "LIMIT 5000" in top_query
        assert (
            "percent_gain" not in top_query.split("FROM observed")[0]
            or "NULL AS percent_gain" in top_query
        )
        rising_query = query_bodies(recorder)[1]["query"]
        assert f"`{DATASET}.{RISING_TABLE}`" in rising_query
        assert "MAX(o.percent_gain) AS percent_gain" in rising_query

        # 4 rows → 3 terms; "doğum günü" is ONE observation over two regions.
        assert [item.term for item in top] == ["galatasaray", "hava durumu", "doğum günü"]
        birthday = top[2]
        assert birthday.trend_type == "top"
        assert birthday.rank == 3
        assert birthday.region_count == 2
        assert [region.region_code for region in birthday.regions] == ["TR-34", "TR-06"]
        assert birthday.latest_score == 61.0
        assert birthday.peak_score == 88.0
        assert birthday.percent_gain is None
        assert birthday.first_week == date(2025, 9, 7)
        assert birthday.last_week == date(2026, 8, 30)
        assert birthday.weeks_with_score == 52
        assert birthday.dataset == DATASET
        assert birthday.table == TOP_TABLE
        assert birthday.refresh_date == REFRESH
        assert birthday.country_code == "TR"
        # A NULL latest score stays None (never 0).
        assert top[1].latest_score is None

        assert [item.term for item in rising] == ["yeni telefon", "ayıcıklı doğum günü"]
        bear = rising[1]
        assert bear.percent_gain == 250.0
        assert bear.rank == 2
        assert bear.region_count == 2
        assert bear.table == RISING_TABLE

    def test_repeat_reads_come_from_the_cache_and_the_budget_is_enforced(self) -> None:
        recorder = bigquery()
        adapter = provider(recorder, google_trends_bigquery_daily_budget=2)

        adapter.top_terms(REFRESH)
        adapter.top_terms(REFRESH)
        assert len(query_bodies(recorder)) == 1
        adapter.rising_terms(REFRESH)
        assert len(query_bodies(recorder)) == 2
        with pytest.raises(ProviderError) as info:
            adapter.latest_refresh_date()
        assert len(query_bodies(recorder)) == 2  # the budget refused before any call
        assert info.value.kind is ProviderState.RATE_LIMITED
        assert info.value.error_class == "google_trends_bigquery_daily_budget"

    def test_parse_rows_types_and_nulls(self) -> None:
        payload = bq_payload(
            [("a", "INTEGER"), ("b", "FLOAT"), ("c", "DATE"), ("d", "BOOLEAN"), ("e", "STRING")],
            [["5", "1.5", "2026-09-03", "true", "x"], [None, None, None, None, None]],
        )
        rows = parse_rows(payload)
        assert rows[0] == {"a": 5, "b": 1.5, "c": "2026-09-03", "d": True, "e": "x"}
        assert rows[1] == {"a": None, "b": None, "c": None, "d": None, "e": None}
        assert parse_rows({"rows": []}) == []

    def test_aggregate_is_deterministic(self) -> None:
        rows = parse_rows(bq_payload(TERMS_SCHEMA, list(reversed(TOP_ROWS))))
        first = aggregate_terms(
            rows,
            trend_type="top",
            table=TOP_TABLE,
            refresh_date=REFRESH,
            country="TR",
            observed_at=NOW,
        )
        second = aggregate_terms(
            list(reversed(rows)),
            trend_type="top",
            table=TOP_TABLE,
            refresh_date=REFRESH,
            country="TR",
            observed_at=NOW,
        )
        assert first == second


# --- persistence + discovery ----------------------------------------------------


class TestObservationsAndDiscovery:
    def test_record_observations_is_idempotent_with_full_provenance(self, harness: Harness) -> None:
        rows = [
            observation("ayıcıklı doğum günü"),
            observation("yeni telefon", rank=1, percent_gain=900.0),
        ]
        with harness.session() as session:
            assert record_trend_term_observations(session, rows) == 2
            assert record_trend_term_observations(session, rows) == 0
            assert trend_terms_synced_for(session, REFRESH, "TR") is True
            assert trend_terms_synced_for(session, REFRESH - timedelta(days=1), "TR") is False
            session.commit()
            signals = list(session.scalars(select(SearchSignal)))

        assert len(signals) == 2
        row = next(item for item in signals if item.subject == "ayıcıklı doğum günü")
        assert row.provider == "google_trends_bigquery"
        assert row.signal_type.value == "trend"
        assert row.market == "TR"
        assert row.as_of is not None
        assert row.as_of.replace(tzinfo=UTC) == datetime(2026, 9, 3, tzinfo=UTC)
        value = row.value
        assert value["dataset"] == DATASET
        assert value["table"] == RISING_TABLE
        assert value["refresh_date"] == "2026-09-03"
        assert value["trend_type"] == "rising"
        assert value["rank"] == 2
        assert value["percent_gain"] == 250.0
        assert value["region_count"] == 2
        assert value["regions"][0]["code"] == "TR-0"
        assert value["query_version"] == QUERY_VERSION
        assert value["relative"] is True
        assert_no_secrets(json.dumps(value, ensure_ascii=False))

    def test_unknown_metrics_are_omitted_never_zero(self, harness: Harness) -> None:
        row = observation("hava durumu", trend_type="top", rank=None, percent_gain=None)
        with harness.session() as session:
            record_trend_term_observations(session, [row])
            session.commit()
            stored = session.scalar(select(SearchSignal))
        assert stored is not None
        assert "rank" not in stored.value
        assert "percent_gain" not in stored.value

    def test_domain_vocabulary_matches_on_normalized_tokens(self) -> None:
        assert "doğum günü" in domain_terms_for("ayıcıklı doğum günü")
        assert "doğum günü" in domain_terms_for("AYICIKLI DOGUM GUNU")
        assert domain_terms_for("galatasaray fenerbahçe") == ()
        assert domain_terms_for("yeni telefon") == ()
        assert "baby shower" in domain_terms_for("baby shower süsleme fikirleri")
        assert "süsleme" in domain_terms_for("baby shower süsleme fikirleri")

    def test_strategy_is_a_priority_signal_not_a_filter(self, harness: Harness) -> None:
        with harness.session() as session:
            StrategyService(session).create_keyword(phrase="yeni telefon kılıfı", priority=80)
            session.commit()
            strategy_hit = match_observation(session, observation("yeni telefon"))
            domain_hit = match_observation(session, observation("ayıcıklı doğum günü"))
            miss = match_observation(session, observation("hava durumu"))

        assert strategy_hit.match_kind == "strategy"
        assert strategy_hit.strategy_keywords == ("yeni telefon kılıfı",)
        assert domain_hit.match_kind == "domain"
        assert domain_hit.strategy_keywords == ()
        assert domain_hit.domain_terms == ("doğum günü",)
        assert miss.relevant is False

    def test_discoveries_become_trend_intelligence_signals_with_own_history(
        self, harness: Harness
    ) -> None:
        day_one = [
            observation("ayıcıklı doğum günü"),
            observation("ayıcıklı doğum günü", trend_type="top", rank=9, percent_gain=None),
            observation("hava durumu", trend_type="top", rank=1, percent_gain=None),
        ]
        with harness.session() as session:
            outcome = record_trend_discoveries(session, day_one, now=NOW)
            again = record_trend_discoveries(session, day_one, now=NOW + timedelta(hours=1))
            session.commit()
            rows = list(session.scalars(select(IntelligenceSignal)))

        assert outcome.terms_seen == 2
        assert [match.observation.term for match in outcome.matched] == ["ayıcıklı doğum günü"]
        assert outcome.signals_created == 1 and outcome.signals_updated == 0
        # Same refresh date again: idempotent (no bump, no duplicate).
        assert again.signals_created == 0 and again.signals_updated == 0
        assert len(rows) == 1
        signal = rows[0]
        assert signal.family is SignalFamily.TREND
        assert signal.provider == "google_trends_bigquery"
        assert signal.source_id is None and signal.normalized_document_id is None
        assert signal.concept_key == "ayıcıklı dogum gunu"
        assert signal.occurrence_count == 1
        assert signal.value["trend_types"] == ["rising", "top"]
        assert signal.value["rank"] == 2
        assert signal.value["percent_gain"] == 250.0
        assert signal.value["match_kind"] == "domain"
        assert signal.value["first_refresh_date"] == "2026-09-03"

        # A NEW refresh date: recurring → occurrence 2, first date preserved.
        later = [observation("ayıcıklı doğum günü", refresh=REFRESH + timedelta(days=1), rank=1)]
        with harness.session() as session:
            outcome = record_trend_discoveries(session, later, now=NOW + timedelta(days=1))
            session.commit()
            signal = session.scalar(select(IntelligenceSignal))
        assert outcome.signals_updated == 1
        assert signal is not None
        assert signal.occurrence_count == 2
        assert signal.value["refresh_date"] == "2026-09-04"
        assert signal.value["first_refresh_date"] == "2026-09-03"
        assert signal.value["rank"] == 1

    def test_snapshot_reads_the_latest_refresh_only(self, harness: Harness) -> None:
        with harness.session() as session:
            assert discovery_snapshot(session).synced is False
            old = [observation("eski terim", refresh=REFRESH - timedelta(days=3))]
            new = [
                observation("ayıcıklı doğum günü"),
                observation("yeni telefon", rank=1, percent_gain=900.0),
                observation("galatasaray", trend_type="top", rank=1, percent_gain=None),
            ]
            record_trend_term_observations(session, [*old, *new])
            record_trend_discoveries(session, [*old, *new], now=NOW)
            session.commit()
            snapshot = discovery_snapshot(session)

        assert snapshot.synced is True
        assert snapshot.refresh_date == REFRESH
        assert [item.term for item in snapshot.top] == ["galatasaray"]
        assert [item.term for item in snapshot.rising] == ["yeni telefon", "ayıcıklı doğum günü"]
        assert [item.term for item in snapshot.matched] == ["ayıcıklı doğum günü"]
        assert snapshot.matched[0].match_kind == "domain"
        assert snapshot.matched[0].domain_terms == ("doğum günü",)
        assert snapshot.total_terms == 3
        assert snapshot.rising[0].matched is False


# --- daily task ----------------------------------------------------------------------


def runner_for(harness: Harness, recorder: Recorder, **overrides: Any) -> TrendDiscoverySyncRunner:
    settings = api_settings().model_copy(
        update={
            "google_service_account_json": integration_settings(
                google_service_account_json=service_account_json()
            ).google_service_account_json,
            "google_cloud_project_id": PROJECT,
            **overrides,
        }
    )
    runtime = WorkerRuntime(settings, session_factory=harness.session_factory)
    reg = IntegrationRegistry(
        settings,
        harness.session_factory,
        http_client=recorder.client(),
        clock=FixedClock(NOW),
        sleep=recorder.sleep,
    )
    return TrendDiscoverySyncRunner(runtime, lambda: reg)


def status_row(harness: Harness) -> IntegrationStatusRecord | None:
    with harness.session() as session:
        return session.get(IntegrationStatusRecord, "google_trends_bigquery")


class TestDailySync:
    def test_sync_persists_terms_signals_and_status_then_is_idempotent(
        self, harness: Harness
    ) -> None:
        recorder = bigquery()
        runner = runner_for(harness, recorder)

        first = runner.sync(now=NOW)

        assert first["state"] == "healthy"
        assert first["refresh_date"] == "2026-09-03"
        assert first["top_terms"] == 3 and first["rising_terms"] == 2
        assert first["signals_created"] == 5
        assert first["discovery"]["matched"] == 2  # doğum günü, ayıcıklı doğum günü
        assert first["retry"] is False
        assert len(query_bodies(recorder)) == 4  # partitions + check + top + rising
        row = status_row(harness)
        assert row is not None and row.state is ProviderState.HEALTHY
        assert row.last_sync_at == NOW
        with harness.session() as session:
            assert session.query(SearchSignal).count() == 5
            assert session.query(IntelligenceSignal).count() == 2

        second = runner.sync(now=NOW + timedelta(hours=2))
        assert second["skipped"] == "already_synced"
        assert len(query_bodies(recorder)) == 4  # nothing re-queried
        with harness.session() as session:
            assert session.query(SearchSignal).count() == 5

    def test_not_configured_sync_does_nothing(self, harness: Harness) -> None:
        recorder = bigquery()
        settings = api_settings()
        runtime = WorkerRuntime(settings, session_factory=harness.session_factory)
        reg = IntegrationRegistry(settings, harness.session_factory, http_client=recorder.client())
        summary = TrendDiscoverySyncRunner(runtime, lambda: reg).sync(now=NOW)
        assert summary["state"] == "not_configured"
        assert summary["skipped"] == "not_configured"
        assert recorder.requests == []
        assert status_row(harness) is None

    def test_transient_failures_are_typed_and_ask_for_a_retry(self, harness: Harness) -> None:
        recorder = bigquery(
            fail=lambda request: json_response(429, {"error": {}}, {"Retry-After": "1"})
        )
        summary = runner_for(harness, recorder).sync(now=NOW)
        assert summary["state"] == "rate_limited"
        assert summary["error_class"] == "google_trends_bigquery_http_429"
        assert summary["retry"] is True
        row = status_row(harness)
        assert row is not None and row.state is ProviderState.RATE_LIMITED
        assert row.last_sync_at is None
        assert_no_secrets(json.dumps(summary))

    def test_no_recent_partition_is_a_healthy_skip(self, harness: Harness) -> None:
        summary = runner_for(harness, bigquery(latest=None)).sync(now=NOW)
        assert summary["state"] == "healthy"
        assert summary["skipped"] == "no_recent_partition"
        row = status_row(harness)
        assert row is not None and row.state is ProviderState.HEALTHY
        assert row.last_sync_at is None

    def test_worker_registers_the_task_and_beat_schedules_it_daily(self) -> None:
        settings = api_settings().model_copy(update={"performance_schedule_enabled": True})
        app = create_worker_app(settings)
        assert SYNC_GOOGLE_TRENDS_BIGQUERY_TASK in app.tasks
        assert app.tasks[SYNC_GOOGLE_TRENDS_BIGQUERY_TASK].max_retries == 2
        schedule = create_celery_app(settings).conf.beat_schedule
        assert (
            schedule["trend-discovery-google-bigquery"]["task"] == SYNC_GOOGLE_TRENDS_BIGQUERY_TASK
        )
        custom = trend_discovery_beat_schedule(
            api_settings().model_copy(update={"google_trends_bigquery_sync_hour_utc": 9})
        )
        assert custom["trend-discovery-google-bigquery"]["schedule"].hour == {9}


# --- opportunity intelligence -----------------------------------------------------------


def seed(harness: Harness) -> Context:
    context = Context()
    with harness.session() as session:
        seed_scored(session, context)
        cluster = StrategyService(session).create_cluster(name="Doğum Günü", priority=90)
        StrategyService(session).create_keyword(
            phrase=PRIMARY, priority=95, topic_cluster_id=cluster.id
        )
        session.commit()
    return context


class TestOpportunityIntelligence:
    def test_absent_term_is_unknown_or_not_observed_never_low(self, harness: Harness) -> None:
        context = seed(harness)
        with harness.session() as session:
            before = enrich_opportunity(session, context.opportunity_id, now=NOW)
            assert before.trend_discovery.state == DISCOVERY_UNKNOWN
            assert before.trend_discovery.provider.state == STATE_NOT_REQUESTED
            assert "trend" not in before.families_known

            # The sets were synced but hold nothing related → NOT_OBSERVED.
            record_trend_term_observations(
                session, [observation("yeni telefon"), observation("galatasaray", trend_type="top")]
            )
            session.commit()
            after = enrich_opportunity(session, context.opportunity_id, now=NOW)

        assert after.trend_discovery.state == DISCOVERY_NOT_OBSERVED
        assert after.trend_discovery.provider.state == STATE_STORED
        assert after.trend_discovery.term is None
        assert after.trend_direction == "unknown"  # Google Trends API stays UNKNOWN
        assert "trend" not in after.families_known

    def test_observed_term_feeds_the_trend_section_rationale_and_read_model(
        self, harness: Harness
    ) -> None:
        context = seed(harness)
        with harness.session() as session:
            record_trend_term_observations(
                session,
                [
                    observation("doğum günü", trend_type="top", rank=3, percent_gain=None),
                    observation("doğum günü", rank=2, percent_gain=180.0),
                ],
            )
            session.commit()
            enrichment = enrich_opportunity(session, context.opportunity_id, now=NOW)
            result = InspirationIntelligenceService(session).evaluate(
                context.opportunity_id, evaluated_at=NOW
            )
            session.commit()
            evaluation = result.evaluation

        discovery = enrichment.trend_discovery
        assert discovery.state == DISCOVERY_OBSERVED
        assert discovery.term == "doğum günü"
        assert discovery.trend_type == "rising"  # rising beats top for the same term
        assert discovery.rank == 2
        assert discovery.percent_gain == 180.0
        assert discovery.refresh_date == "2026-09-03"
        assert discovery.provider.state == STATE_STORED
        assert "trend" in enrichment.families_known
        # Keyword-specific Google Trends (API) is still UNKNOWN: never conflated.
        assert enrichment.trend_direction == "unknown"
        assert enrichment.google_trends.state == STATE_NOT_REQUESTED

        assert evaluation.trend_state is TrendState.KNOWN
        block = evaluation.input_snapshot["intelligence"]["trend_discovery"]
        assert block["state"] == "observed"
        assert block["provider"]["provider"] == "google_trends_bigquery"
        assert (
            "Google Trend Keşfi (BigQuery): 'doğum günü' Türkiye yükselen sorgularında gözlendi "
            "(2026-09-03, sıra 2)"
        ) in evaluation.rationale
        assert "Google Trends: bu süreçte sorgulanmadı" in evaluation.rationale

        response = harness.get("/internal/editorial/work-items")
        assert response.status_code == 200, response.text
        row = next(
            item
            for item in response.json()["items"]
            if item["opportunity_id"] == str(context.opportunity_id)
        )
        search = row["intelligence"]["search_intelligence"]
        assert search["google_trends_direction"] == "unknown"
        assert search["google_trends_discovery"] == {
            "state": "observed",
            "term": "doğum günü",
            "trend_type": "rising",
            "refresh_date": "2026-09-03",
            "rank": 2,
            "percent_gain": 180.0,
        }
        assert search["provider_freshness"]["google_trends_bigquery"]["state"] == "stored"
        assert search["provider_freshness"]["google_trends"]["state"] == "not_requested"
        assert_no_secrets(response.text)

    def test_unconfigured_provider_in_a_worker_process_is_unknown(self, harness: Harness) -> None:
        context = seed(harness)
        recorder = bigquery()
        reg = IntegrationRegistry(
            integration_settings(), http_client=recorder.client(), clock=FixedClock(NOW)
        )
        with harness.session() as session:
            result = enrich_opportunity(session, context.opportunity_id, registry=reg, now=NOW)
        assert result.trend_discovery.state == DISCOVERY_UNKNOWN
        assert result.trend_discovery.provider.state == "not_configured"
        assert recorder.requests == []


# --- API -------------------------------------------------------------------------------


class TestApi:
    def test_board_lists_the_provider_separately_from_the_alpha_api(self, harness: Harness) -> None:
        response = harness.get("/internal/integrations")
        assert response.status_code == 200, response.text
        providers = {item["name"]: item for item in response.json()["providers"]}
        assert (
            list(providers).index("google_trends_bigquery")
            == list(providers).index("google_trends") + 1
        )
        item = providers["google_trends_bigquery"]
        assert item["state"] == "not_configured"
        assert item["display_name"] == "Google Trend Keşfi (BigQuery)"
        assert item["required_env"] == ["CONTENTOS_GOOGLE_SERVICE_ACCOUNT_JSON"]
        assert "CONTENTOS_GOOGLE_CLOUD_PROJECT_ID" in item["optional_env"]
        assert item["daily_budget"] == 20
        assert providers["google_trends"]["state"] == "access_required"

    def test_discovery_endpoint_before_and_after_a_sync(self, harness: Harness) -> None:
        empty = harness.get("/internal/integrations/google_trends_bigquery/discovery")
        assert empty.status_code == 200, empty.text
        body = empty.json()
        assert body["synced"] is False
        assert body["refresh_date"] is None
        assert body["top"] == [] and body["rising"] == [] and body["matched"] == []

        with harness.session() as session:
            rows = [
                observation("ayıcıklı doğum günü"),
                observation("yeni telefon", rank=1, percent_gain=900.0),
                observation("galatasaray", trend_type="top", rank=1, percent_gain=None),
            ]
            record_trend_term_observations(session, rows)
            record_trend_discoveries(session, rows, now=NOW)
            session.commit()

        response = harness.get("/internal/integrations/google_trends_bigquery/discovery")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["provider"] == "google_trends_bigquery"
        assert body["country"] == "TR"
        assert body["synced"] is True
        assert body["refresh_date"] == "2026-09-03"
        assert body["total_terms"] == 3
        assert body["matched_count"] == 1
        assert [item["term"] for item in body["rising"]] == ["yeni telefon", "ayıcıklı doğum günü"]
        matched = body["matched"][0]
        assert matched["term"] == "ayıcıklı doğum günü"
        assert matched["match_kind"] == "domain"
        assert matched["domain_terms"] == ["doğum günü"]
        assert matched["percent_gain"] == 250.0
        assert matched["occurrence_count"] == 1
        assert body["top"][0]["percent_gain"] is None
        assert_no_secrets(response.text)

    def test_sync_now_goes_through_the_producer_seam(self, harness: Harness) -> None:
        response = harness.post(
            "/internal/integrations/google_trends_bigquery/sync",
            headers={"X-Request-ID": "req-trends-1"},
        )
        assert response.status_code == 200, response.text
        assert response.json() == {
            "status": "queued",
            "tasks": ["contentos.trends.sync_google_trends_bigquery"],
        }
        assert harness.dispatcher.calls == [("trend_discovery_sync", {}, "req-trends-1")]
