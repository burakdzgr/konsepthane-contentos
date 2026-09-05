"""Google Trends — BigQuery Public Dataset (first-party trend DISCOVERY).

Google publishes its daily Top and Rising search-term sets as the official
public dataset `bigquery-public-data.google_trends`. This adapter answers
ONE question: "which queries did Google list in Türkiye's top / rising
trend sets on a given refresh date?" It is a discovery source, not a
keyword-research API:

- it never yields search volume for an arbitrary keyword;
- a keyword that does not appear in the sets is `NOT_OBSERVED`, never
  "low trend" — the sets hold ~25 terms per region per day;
- it does not replace Semrush (volume) or the official Google Trends API
  (arbitrary-keyword interest, `GoogleTrendsProvider`, access-gated).

Cost safety, in this order: every query is bound to ONE `refresh_date`
partition (or a 14-day window for the latest-partition probe) and to
`country_code = @country`; only the needed columns are selected; rows are
grouped and LIMITed; `maximumBytesBilled` caps a query; BigQuery's own
query cache is on; the shared response cache and the daily request budget
sit in front of every call; and there is no free-form SQL surface.

Auth reuses the Search Console / GA4 service-account key
(`CONTENTOS_GOOGLE_SERVICE_ACCOUNT_JSON`). The account only needs the
`BigQuery Job User` role on the billing project (`CONTENTOS_GOOGLE_CLOUD_
PROJECT_ID`, defaulting to the key file's project) — public datasets are
readable by every authenticated account.
"""

from datetime import date, datetime, timedelta
from typing import Any

import httpx

from contentos.core.config import Settings
from contentos.integrations.base import ProviderError, ProviderStatus, sanitize_error_class
from contentos.integrations.budget import RequestBudget
from contentos.integrations.cache import JsonPayload, ResponseCache
from contentos.integrations.dto import TrendTermObservation, TrendTermRegion
from contentos.integrations.enums import ProviderName, ProviderState
from contentos.integrations.google_auth import (
    ServiceAccountInfo,
    ServiceAccountTokenSource,
    load_service_account,
)
from contentos.integrations.http import Clock, Sleep
from contentos.integrations.support import TEST_TIMEOUT_SECONDS, ProviderSupport

BASE_URL = "https://bigquery.googleapis.com/bigquery/v2"
SCOPES = ("https://www.googleapis.com/auth/bigquery.readonly",)
DATASET = "bigquery-public-data.google_trends"
TOP_TABLE = "international_top_terms"
RISING_TABLE = "international_top_rising_terms"
TREND_TYPE_TOP = "top"
TREND_TYPE_RISING = "rising"
QUERY_VERSION = "1"
# Latest-partition lookup: partition ids come from INFORMATION_SCHEMA
# (metadata, ~10 MB minimum billing), then ONE partition is checked for the
# country's rows (~80 MB) — instead of scanning 14 partitions (~1 GB). The
# 14-day MAX() probe stays as the fallback when metadata is unavailable.
LOOKBACK_DAYS = 14
MAX_PARTITION_CANDIDATES = 3
# Rows per (term, region) query — 25 terms × ~81 provinces is ~2k.
MAX_ROWS = 5000
# Regions kept per term in the aggregated observation (sorted by rank).
MAX_REGIONS_PER_TERM = 100
QUERY_TIMEOUT_MS = 30_000
TEST_QUERY_TIMEOUT_MS = 3_000
MINIMUM_IAM_ROLE = "BigQuery Job User"


def _bounded_country(value: str) -> str:
    cleaned = value.strip().upper()
    if len(cleaned) != 2 or not cleaned.isalpha():
        raise ValueError("country code must be two letters")
    return cleaned


def _sql_date(value: date) -> str:
    """A DATE literal from a real `date` (never from user text) so BigQuery
    prunes the partition; the type check is the injection guard."""
    if not isinstance(value, date) or isinstance(value, datetime):
        raise TypeError("refresh_date must be a date")
    return f"DATE '{value.isoformat()}'"


def latest_refresh_sql(lookback_days: int = LOOKBACK_DAYS) -> str:
    return (
        "SELECT MAX(refresh_date) AS refresh_date\n"
        f"FROM `{DATASET}.{TOP_TABLE}`\n"
        f"WHERE refresh_date BETWEEN DATE_SUB(CURRENT_DATE(), INTERVAL {int(lookback_days)} DAY)"
        " AND CURRENT_DATE()\n"
        "  AND country_code = @country"
    )


PARTITIONS_SQL = (
    "SELECT partition_id\n"
    f"FROM `{DATASET}.INFORMATION_SCHEMA.PARTITIONS`\n"
    "WHERE table_name = @table AND partition_id != '__NULL__'\n"
    f"ORDER BY partition_id DESC\nLIMIT {LOOKBACK_DAYS}"
)


def partition_check_sql(refresh_date: date) -> str:
    """Does ONE partition hold rows for the country? (partition-bound)"""
    return (
        "SELECT MAX(refresh_date) AS refresh_date\n"
        f"FROM `{DATASET}.{TOP_TABLE}`\n"
        f"WHERE refresh_date = {_sql_date(refresh_date)} AND country_code = @country"
    )


def terms_sql(table: str, refresh_date: date) -> str:
    """Per (term, region) aggregation of ONE refresh partition for ONE country."""
    gain = (
        "  MAX(o.percent_gain) AS percent_gain,\n"
        if table == RISING_TABLE
        else "  NULL AS percent_gain,\n"
    )
    columns = "term, region_code, region_name, rank, week, score" + (
        ", percent_gain" if table == RISING_TABLE else ""
    )
    return (
        "WITH observed AS (\n"
        f"  SELECT {columns}\n"
        f"  FROM `{DATASET}.{table}`\n"
        f"  WHERE refresh_date = {_sql_date(refresh_date)} AND country_code = @country\n"
        "), latest AS (SELECT MAX(week) AS week FROM observed)\n"
        "SELECT o.term AS term, o.region_code AS region_code, o.region_name AS region_name,\n"
        "  MIN(o.rank) AS rank,\n"
        "  MAX(IF(o.week = latest.week, o.score, NULL)) AS latest_score,\n"
        "  MAX(o.score) AS peak_score,\n"
        f"{gain}"
        "  COUNTIF(o.score IS NOT NULL) AS weeks_with_score,\n"
        "  MIN(o.week) AS first_week, MAX(o.week) AS last_week\n"
        "FROM observed AS o CROSS JOIN latest\n"
        "GROUP BY term, region_code, region_name\n"
        "ORDER BY rank, term, region_code\n"
        f"LIMIT {MAX_ROWS}"
    )


class GoogleTrendsBigQueryProvider(ProviderSupport):
    name = ProviderName.GOOGLE_TRENDS_BIGQUERY

    def __init__(
        self,
        settings: Settings,
        *,
        http_client: httpx.Client | None = None,
        clock: Clock | None = None,
        sleep: Sleep | None = None,
        cache: ResponseCache | None = None,
        budget: RequestBudget | None = None,
    ) -> None:
        super().__init__(
            ProviderName.GOOGLE_TRENDS_BIGQUERY,
            settings,
            daily_budget=settings.google_trends_bigquery_daily_budget,
            cache_hours=settings.google_trends_bigquery_cache_hours,
            http_client=http_client,
            clock=clock,
            sleep=sleep,
            cache=cache,
            budget=budget,
        )
        self._max_bytes_billed = settings.google_trends_bigquery_max_bytes_billed
        self._country = _bounded_country(settings.google_trends_bigquery_country)
        self._tokens: ServiceAccountTokenSource | None = None
        self._info: ServiceAccountInfo | None = None

    # --- contract -----------------------------------------------------------

    def configured(self) -> bool:
        return self._settings.google_service_account_json is not None

    @property
    def country(self) -> str:
        return self._country

    def project_id(self) -> str | None:
        """The billing/query project: the explicit setting, else the key's."""
        explicit = self._settings.google_cloud_project_id
        if explicit:
            return explicit.strip()
        try:
            return self._service_account().project_id
        except ProviderError:
            return None

    def test_connection(self) -> ProviderStatus:
        if not self.configured():
            return self.not_configured_status()
        if self.project_id() is None:
            return self.status(
                ProviderState.NOT_CONFIGURED,
                "Google Cloud proje kimliği bulunamadı: CONTENTOS_GOOGLE_CLOUD_PROJECT_ID "
                "tanımlayın (anahtar dosyasında project_id yoksa).",
                error_class=sanitize_error_class(self.name.value, "project_missing"),
            )
        try:
            payload = self.cost.uncached(
                lambda: self._latest_refresh(
                    self._country,
                    timeout_ms=TEST_QUERY_TIMEOUT_MS,
                    http_timeout=TEST_TIMEOUT_SECONDS,
                )
            )
        except ProviderError as error:
            if error.kind is ProviderState.ACCESS_REQUIRED:
                return self.status_from_error(
                    error,
                    "BigQuery erişimi reddedildi: servis hesabına Google Cloud projesinde "
                    f"'{MINIMUM_IAM_ROLE}' rolü verin ve BigQuery API'yi etkinleştirin.",
                )
            if error.error_class.endswith("_query_incomplete"):
                return self.status_from_error(
                    error,
                    "BigQuery sorgusu test süresi içinde tamamlanmadı; günlük senkron yine de "
                    "çalışır. Daha sonra yeniden deneyin.",
                )
            if error.error_class.endswith("_http_400"):
                return self.status_from_error(
                    error,
                    "BigQuery sorguyu reddetti (bütçe sınırı ya da proje ayarı). "
                    "CONTENTOS_GOOGLE_CLOUD_PROJECT_ID ve bytes sınırını kontrol edin.",
                )
            return self.status_from_error(error)
        latest = _latest_from_payload(payload)
        scanned = _megabytes(payload.get("total_bytes_processed"))
        if latest is None:
            return self.status(
                ProviderState.HEALTHY,
                f"Bağlı. Son {LOOKBACK_DAYS} günde {self._country} verisi yayınlanmamış "
                f"(yayın gecikmesi); senkron ilk veride başlar.{scanned}",
            )
        return self.status(
            ProviderState.HEALTHY,
            f"Bağlı. Son {self._country} verisi: {latest.isoformat()}.{scanned}",
        )

    # --- reads --------------------------------------------------------------

    def latest_refresh_date(self, country: str | None = None) -> date | None:
        """Newest partition with rows for the country inside the lookback
        window, or None (upstream publish lag is normal, never an error)."""
        region = _bounded_country(country) if country else self._country
        today = self.now().date().isoformat()
        payload = self.cost.cached(
            ("latest_refresh", region, today, QUERY_VERSION),
            lambda: self._latest_refresh(region),
        )
        return _latest_from_payload(payload)

    def _latest_refresh(
        self,
        country: str,
        *,
        timeout_ms: int = QUERY_TIMEOUT_MS,
        http_timeout: float | None = None,
    ) -> JsonPayload:
        """`{"rows": [{"refresh_date": iso|None}], "total_bytes_processed": n}`
        via metadata + one partition check; the 14-day MAX() probe only when
        the metadata query is unavailable (never on access/quota errors)."""
        scanned = 0
        candidates: list[date] | None
        try:
            listing = self._run_query(
                PARTITIONS_SQL,
                {"table": TOP_TABLE},
                timeout_ms=timeout_ms,
                http_timeout=http_timeout,
            )
        except ProviderError as error:
            if error.kind in (
                ProviderState.ACCESS_REQUIRED,
                ProviderState.RATE_LIMITED,
                ProviderState.DEGRADED,
            ):
                raise
            candidates = None
        else:
            scanned += _bytes(listing)
            candidates = _partition_dates(listing, today=self.now().date())
        if candidates is None:
            payload = self._run_query(
                latest_refresh_sql(),
                {"country": country},
                timeout_ms=timeout_ms,
                http_timeout=http_timeout,
            )
            scanned += _bytes(payload)
            return {
                "rows": [{"refresh_date": _iso(_latest_from_payload(payload))}],
                "total_bytes_processed": scanned,
            }
        for candidate in candidates[:MAX_PARTITION_CANDIDATES]:
            payload = self._run_query(
                partition_check_sql(candidate),
                {"country": country},
                timeout_ms=timeout_ms,
                http_timeout=http_timeout,
            )
            scanned += _bytes(payload)
            found = _latest_from_payload(payload)
            if found is not None:
                return {
                    "rows": [{"refresh_date": found.isoformat()}],
                    "total_bytes_processed": scanned,
                }
        return {"rows": [{"refresh_date": None}], "total_bytes_processed": scanned}

    def top_terms(
        self, refresh_date: date, country: str | None = None
    ) -> list[TrendTermObservation]:
        return self._terms(TOP_TABLE, TREND_TYPE_TOP, refresh_date, country)

    def rising_terms(
        self, refresh_date: date, country: str | None = None
    ) -> list[TrendTermObservation]:
        return self._terms(RISING_TABLE, TREND_TYPE_RISING, refresh_date, country)

    def _terms(
        self, table: str, trend_type: str, refresh_date: date, country: str | None
    ) -> list[TrendTermObservation]:
        region = _bounded_country(country) if country else self._country
        payload = self.cost.cached(
            ("terms", table, region, refresh_date.isoformat(), QUERY_VERSION),
            lambda: self._run_query(terms_sql(table, refresh_date), {"country": region}),
        )
        rows = payload.get("rows")
        return aggregate_terms(
            rows if isinstance(rows, list) else [],
            trend_type=trend_type,
            table=table,
            refresh_date=refresh_date,
            country=region,
            observed_at=self.now(),
        )

    # --- transport ----------------------------------------------------------

    def _service_account(self) -> ServiceAccountInfo:
        if self._info is None:
            self._info = load_service_account(self._settings.google_service_account_json)
        return self._info

    def _token(self) -> str:
        if self._tokens is None:
            self._tokens = ServiceAccountTokenSource(
                self._service_account(), SCOPES, http=self._http, clock=self._clock
            )
        return self._tokens.access_token()

    def _run_query(
        self,
        sql: str,
        params: dict[str, str],
        *,
        timeout_ms: int = QUERY_TIMEOUT_MS,
        http_timeout: float | None = None,
    ) -> JsonPayload:
        project = self.project_id()
        if project is None:
            raise ProviderError(
                "google cloud project id missing",
                kind=ProviderState.NOT_CONFIGURED,
                error_class=sanitize_error_class(self.name.value, "project_missing"),
            )
        body: dict[str, Any] = {
            "query": sql,
            "useLegacySql": False,
            "useQueryCache": True,
            "maximumBytesBilled": str(int(self._max_bytes_billed)),
            "timeoutMs": int(timeout_ms),
            "maxResults": MAX_ROWS,
            "parameterMode": "NAMED",
            "queryParameters": [
                {
                    "name": name,
                    "parameterType": {"type": "STRING"},
                    "parameterValue": {"value": value},
                }
                for name, value in sorted(params.items())
            ],
            "labels": {"app": "contentos", "purpose": "trend_discovery"},
        }
        response = self._http.request(
            "POST",
            f"{BASE_URL}/projects/{project}/queries",
            headers={"Authorization": f"Bearer {self._token()}"},
            json_body=body,
            timeout_seconds=http_timeout,
        )
        decoded = self._http.json(response)
        if not isinstance(decoded, dict):
            raise ProviderError(
                "bigquery returned a non-object body",
                kind=ProviderState.ERROR,
                error_class=sanitize_error_class(self.name.value, "malformed_body"),
            )
        errors = decoded.get("errors")
        if isinstance(errors, list) and errors:
            raise ProviderError(
                "bigquery reported query errors",
                kind=ProviderState.ERROR,
                error_class=sanitize_error_class(self.name.value, "query_error"),
            )
        if decoded.get("jobComplete") is False:
            raise ProviderError(
                "bigquery query did not complete within the timeout",
                kind=ProviderState.DEGRADED,
                error_class=sanitize_error_class(self.name.value, "query_incomplete"),
            )
        total = decoded.get("totalBytesProcessed")
        return {
            "rows": parse_rows(decoded),
            "total_bytes_processed": int(total)
            if isinstance(total, (str, int)) and str(total).isdigit()
            else None,
            "cache_hit": bool(decoded.get("cacheHit", False)),
        }


# --- response parsing ----------------------------------------------------------


def parse_rows(decoded: dict[str, Any]) -> list[dict[str, Any]]:
    """`{"schema":{"fields":[...]},"rows":[{"f":[{"v":...}]}]}` → typed dicts
    (JSON-safe: dates stay ISO strings). Unknown types stay strings; NULL
    stays None; nothing is invented."""
    schema = decoded.get("schema")
    fields = schema.get("fields") if isinstance(schema, dict) else None
    if not isinstance(fields, list):
        return []
    names: list[tuple[str, str]] = []
    for field in fields:
        if isinstance(field, dict) and isinstance(field.get("name"), str):
            names.append((field["name"], str(field.get("type", "STRING")).upper()))
    rows = decoded.get("rows")
    if not isinstance(rows, list):
        return []
    result: list[dict[str, Any]] = []
    for row in rows:
        cells = row.get("f") if isinstance(row, dict) else None
        if not isinstance(cells, list):
            continue
        record: dict[str, Any] = {}
        for (name, kind), cell in zip(names, cells, strict=False):
            value = cell.get("v") if isinstance(cell, dict) else None
            record[name] = _cell(value, kind)
        result.append(record)
    return result


def _cell(value: Any, kind: str) -> Any:
    if value is None:
        return None
    try:
        if kind in ("INTEGER", "INT64"):
            return int(value)
        if kind in ("FLOAT", "FLOAT64", "NUMERIC", "BIGNUMERIC"):
            return float(value)
        if kind in ("BOOLEAN", "BOOL"):
            return str(value).lower() == "true"
        # DATE stays an ISO string: parsed payloads are cached as JSON.
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, str) else str(value)


def _bytes(payload: JsonPayload) -> int:
    value = payload.get("total_bytes_processed")
    return value if isinstance(value, int) else 0


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _partition_dates(payload: JsonPayload, *, today: date) -> list[date]:
    """`YYYYMMDD` partition ids → dates inside the lookback window, newest
    first (ids outside the window are ignored, not queried)."""
    rows = payload.get("rows")
    if not isinstance(rows, list):
        return []
    floor = today - timedelta(days=LOOKBACK_DAYS)
    result: list[date] = []
    for row in rows:
        value = row.get("partition_id") if isinstance(row, dict) else None
        if not isinstance(value, str) or len(value) != 8 or not value.isdigit():
            continue
        try:
            parsed = date(int(value[:4]), int(value[4:6]), int(value[6:8]))
        except ValueError:
            continue
        if floor <= parsed <= today and parsed not in result:
            result.append(parsed)
    result.sort(reverse=True)
    return result


def _latest_from_payload(payload: JsonPayload) -> date | None:
    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        return None
    value = rows[0].get("refresh_date") if isinstance(rows[0], dict) else None
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _megabytes(total: Any) -> str:
    if not isinstance(total, int):
        return ""
    return f" Taranan veri: {total / 1_000_000:.1f} MB."


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _as_date(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def aggregate_terms(
    rows: list[dict[str, Any]],
    *,
    trend_type: str,
    table: str,
    refresh_date: date,
    country: str,
    observed_at: datetime,
) -> list[TrendTermObservation]:
    """One country-level observation per term, regions kept underneath.

    The dataset lists a term once per region (province); the same term in
    many regions is ONE country observation with `region_count` and the
    per-region ranks — never N duplicate signals. Ordering is deterministic
    (best rank, then term) so re-runs produce identical output.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        term = row.get("term")
        if not isinstance(term, str):
            continue
        cleaned = " ".join(term.split())
        if not cleaned:
            continue
        grouped.setdefault(cleaned, []).append(row)
    result: list[TrendTermObservation] = []
    for term, entries in grouped.items():
        regions: list[TrendTermRegion] = []
        for entry in entries:
            code = entry.get("region_code")
            name = entry.get("region_name")
            regions.append(
                TrendTermRegion(
                    region_code=code if isinstance(code, str) and code else None,
                    region_name=name if isinstance(name, str) and name else None,
                    rank=_as_int(entry.get("rank")),
                    latest_score=_as_float(entry.get("latest_score")),
                    percent_gain=_as_float(entry.get("percent_gain")),
                )
            )
        regions.sort(
            key=lambda item: (item.rank if item.rank is not None else 10**6, item.region_code or "")
        )
        ranks = [item.rank for item in regions if item.rank is not None]
        gains = [item.percent_gain for item in regions if item.percent_gain is not None]
        latest_scores = [item.latest_score for item in regions if item.latest_score is not None]
        peaks = [_as_float(entry.get("peak_score")) for entry in entries]
        peak_values = [value for value in peaks if value is not None]
        weeks = [_as_int(entry.get("weeks_with_score")) for entry in entries]
        week_values = [value for value in weeks if value is not None]
        first_weeks = [_as_date(entry.get("first_week")) for entry in entries]
        last_weeks = [_as_date(entry.get("last_week")) for entry in entries]
        first_values = [value for value in first_weeks if value is not None]
        last_values = [value for value in last_weeks if value is not None]
        result.append(
            TrendTermObservation(
                term=term,
                country_code=country,
                refresh_date=refresh_date,
                trend_type=trend_type,
                rank=min(ranks) if ranks else None,
                latest_score=max(latest_scores) if latest_scores else None,
                peak_score=max(peak_values) if peak_values else None,
                percent_gain=max(gains) if gains else None,
                region_count=len(regions),
                regions=tuple(regions[:MAX_REGIONS_PER_TERM]),
                first_week=min(first_values) if first_values else None,
                last_week=max(last_values) if last_values else None,
                weeks_with_score=max(week_values) if week_values else None,
                dataset=DATASET,
                table=table,
                query_version=QUERY_VERSION,
                observed_at=observed_at,
            )
        )
    result.sort(key=lambda item: (item.rank if item.rank is not None else 10**6, item.term))
    return result
