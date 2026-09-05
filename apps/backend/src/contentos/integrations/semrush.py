"""Semrush Analytics API v3 adapter (external SEO market intelligence).

Endpoints: `https://api.semrush.com/?type=phrase_these|phrase_related|
domain_organic&key=...&database=tr&export_columns=...`. Responses are
semicolon-separated tables (first line = header) or `ERROR <code> :: ...`
bodies, which map to typed states. Semrush numbers are MARKET estimates —
never Search Console truth — and missing cells stay None.
"""

import re
from typing import Any

import httpx

from contentos.core.config import Settings
from contentos.integrations.base import ProviderError, ProviderStatus, sanitize_error_class
from contentos.integrations.budget import RequestBudget
from contentos.integrations.cache import JsonPayload, ResponseCache
from contentos.integrations.dto import KeywordMetrics, RelatedKeyword
from contentos.integrations.enums import ProviderName, ProviderState
from contentos.integrations.http import Clock, Sleep
from contentos.integrations.support import TEST_TIMEOUT_SECONDS, ProviderSupport

API_URL = "https://api.semrush.com/"
UNITS_URL = "https://www.semrush.com/users/countapiunits.html"
MAX_BATCH = 100
MAX_LIMIT = 200

_ERROR = re.compile(r"^\s*ERROR\s+(\d+)")
_ACCESS_CODES = frozenset({120, 121, 130, 133, 135})
_LIMIT_CODES = frozenset({131, 132, 134})
_NOTHING_FOUND = 50

_INTENTS = {"0": "commercial", "1": "informational", "2": "navigational", "3": "transactional"}

OVERVIEW_COLUMNS = "Ph,Nq,Cp,Co,Kd,In"
RELATED_COLUMNS = "Ph,Nq,Kd"
DOMAIN_COLUMNS = "Ph,Po,Nq,Cp,Ur,Tr,Kd"


def semrush_error(body: str) -> ProviderError | None:
    """Typed error for an `ERROR <code> :: ...` body; None for `NOTHING FOUND`
    (an empty result, not a failure) and for non-error bodies."""
    match = _ERROR.match(body)
    if match is None:
        return None
    code = int(match.group(1))
    if code == _NOTHING_FOUND:
        return None
    if code in _LIMIT_CODES:
        kind = ProviderState.RATE_LIMITED
    elif code in _ACCESS_CODES:
        kind = ProviderState.ACCESS_REQUIRED
    else:
        kind = ProviderState.ERROR
    return ProviderError(
        f"semrush api error {code}",
        kind=kind,
        error_class=sanitize_error_class("semrush", f"api_{code}"),
    )


def parse_table(body: str) -> list[dict[str, str]]:
    """Semicolon table → row dicts keyed by header. Defensive: short rows
    are padded with empty strings, extra cells are dropped."""
    error = semrush_error(body)
    if error is not None:
        raise error
    if _ERROR.match(body):
        return []
    lines = [line.rstrip("\r") for line in body.split("\n") if line.strip()]
    if not lines:
        return []
    header = [cell.strip() for cell in lines[0].split(";")]
    rows: list[dict[str, str]] = []
    for line in lines[1:]:
        cells = [cell.strip() for cell in line.split(";")]
        if len(cells) < len(header):
            cells.extend([""] * (len(header) - len(cells)))
        rows.append(dict(zip(header, cells, strict=False)))
    return rows


def _int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def _float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    return number if number == number else None


def _intent(value: str | None) -> str | None:
    if not value:
        return None
    first = value.split(",")[0].strip()
    return _INTENTS.get(first)


class SemrushProvider(ProviderSupport):
    name = ProviderName.SEMRUSH

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
            ProviderName.SEMRUSH,
            settings,
            daily_budget=settings.semrush_daily_budget,
            cache_hours=settings.semrush_cache_hours,
            http_client=http_client,
            clock=clock,
            sleep=sleep,
            cache=cache,
            budget=budget,
        )
        self._database = settings.semrush_database

    def configured(self) -> bool:
        return self._settings.semrush_api_key is not None

    def test_connection(self) -> ProviderStatus:
        if not self.configured():
            return self.not_configured_status()
        try:
            body = self.cost.uncached(
                lambda: (
                    self._http.request(
                        "GET",
                        UNITS_URL,
                        params={"key": self._key()},
                        timeout_seconds=TEST_TIMEOUT_SECONDS,
                    ).text
                )
            )
        except ProviderError as error:
            return self.status_from_error(error)
        api_error = semrush_error(body)
        if api_error is not None:
            return self.status_from_error(api_error)
        units = _int(body.strip())
        if units is None:
            return self.status(
                ProviderState.ERROR,
                "Semrush beklenmedik bir yanıt döndürdü.",
                error_class=sanitize_error_class("semrush", "malformed_body"),
            )
        return self.status(
            ProviderState.HEALTHY,
            f"Bağlı. Kalan API birimi: {units}. Veritabanı: {self._database}.",
        )

    def keyword_overview(
        self, keywords: list[str], database: str | None = None
    ) -> list[KeywordMetrics]:
        """Volume/KD/CPC/competition/intent for up to 100 deduplicated keywords."""
        cleaned = _dedupe(keywords)[:MAX_BATCH]
        if not cleaned:
            return []
        db = (database or self._database).lower()
        payload = self.cost.cached(
            ("phrase_these", db, cleaned),
            lambda: self._table(
                {
                    "type": "phrase_these",
                    "phrase": ";".join(cleaned),
                    "database": db,
                    "export_columns": OVERVIEW_COLUMNS,
                }
            ),
        )
        observed_at = self.now()
        metrics: list[KeywordMetrics] = []
        for row in _rows(payload):
            keyword = row.get("Keyword", "").strip()
            if not keyword:
                continue
            metrics.append(
                KeywordMetrics(
                    keyword=keyword,
                    database=db,
                    search_volume=_int(row.get("Search Volume")),
                    keyword_difficulty=_float(row.get("Keyword Difficulty")),
                    cpc=_float(row.get("CPC")),
                    competition=_float(row.get("Competition")),
                    intent=_intent(row.get("Intent")),
                    observed_at=observed_at,
                )
            )
        return metrics

    def related_keywords(self, phrase: str, limit: int = 20) -> list[RelatedKeyword]:
        cleaned = " ".join(phrase.split())
        if not cleaned:
            return []
        bounded = max(1, min(limit, MAX_LIMIT))
        payload = self.cost.cached(
            ("phrase_related", self._database, cleaned, bounded),
            lambda: self._table(
                {
                    "type": "phrase_related",
                    "phrase": cleaned,
                    "database": self._database,
                    "display_limit": bounded,
                    "export_columns": RELATED_COLUMNS,
                }
            ),
        )
        related: list[RelatedKeyword] = []
        for row in _rows(payload):
            keyword = row.get("Keyword", "").strip()
            if not keyword:
                continue
            related.append(
                RelatedKeyword(
                    keyword=keyword,
                    search_volume=_int(row.get("Search Volume")),
                    keyword_difficulty=_float(row.get("Keyword Difficulty")),
                )
            )
        return related[:bounded]

    def domain_organic(self, domain: str, limit: int = 50) -> list[dict[str, Any]]:
        """Bounded organic keyword rows for a domain (keyword, position,
        volume, cpc, url, traffic share, difficulty); UNKNOWN cells are None."""
        cleaned = domain.strip().lower()
        if not cleaned:
            return []
        bounded = max(1, min(limit, MAX_LIMIT))
        payload = self.cost.cached(
            ("domain_organic", self._database, cleaned, bounded),
            lambda: self._table(
                {
                    "type": "domain_organic",
                    "domain": cleaned,
                    "database": self._database,
                    "display_limit": bounded,
                    "export_columns": DOMAIN_COLUMNS,
                }
            ),
        )
        result: list[dict[str, Any]] = []
        for row in _rows(payload):
            keyword = row.get("Keyword", "").strip()
            if not keyword:
                continue
            result.append(
                {
                    "keyword": keyword,
                    "position": _int(row.get("Position")),
                    "search_volume": _int(row.get("Search Volume")),
                    "cpc": _float(row.get("CPC")),
                    "url": row.get("Url") or None,
                    "traffic_pct": _float(row.get("Traffic (%)")),
                    "keyword_difficulty": _float(row.get("Keyword Difficulty")),
                }
            )
        return result[:bounded]

    def _key(self) -> str:
        key = self._settings.semrush_api_key
        if key is None:
            raise ProviderError(
                "semrush is not configured",
                kind=ProviderState.NOT_CONFIGURED,
                error_class=sanitize_error_class("semrush", "not_configured"),
            )
        return key.get_secret_value()

    def _table(self, params: dict[str, Any]) -> JsonPayload:
        response = self._http.request("GET", API_URL, params={**params, "key": self._key()})
        return {"rows": parse_table(response.text)}


def _rows(payload: JsonPayload) -> list[dict[str, str]]:
    rows = payload.get("rows")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _dedupe(keywords: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for keyword in keywords:
        cleaned = " ".join(keyword.split())
        if not cleaned:
            continue
        marker = cleaned.casefold()
        if marker in seen:
            continue
        seen.add(marker)
        result.append(cleaned)
    return result
