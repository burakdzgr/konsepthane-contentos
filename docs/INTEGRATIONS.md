# External intelligence providers (Entegrasyonlar)

ContentOS can enrich idea intelligence with five external providers. Every
adapter talks to the vendor's **official API only**, is constructed from
`Settings`, and degrades to an honest state when credentials are missing:
nothing is scraped, nothing is fabricated, and a missing metric stays
`None` / "Bilinmiyor" — never `0`.

Code: `apps/backend/src/contentos/integrations/`. Admin screen:
`/entegrasyonlar` ("Entegrasyonlar", nav section "Sistem").

## What each provider is for

| Provider | Role in ContentOS | Never |
| --- | --- | --- |
| **Semrush** | External SEO *market* intelligence: search volume, keyword difficulty, CPC, competition, intent, related keywords, a competitor domain's organic keywords. | Treated as Search Console truth. It is a market estimate. |
| **Google Search Console** | *Our* real search performance for konsepthane.net: clicks, impressions, CTR, position per query/page/date/country/device. | Used as a market-demand estimate for topics we do not rank for. |
| **Google Analytics 4** | On-site behaviour of our pages: users, sessions, views, engagement rate, and key events **only** for names configured in `CONTENTOS_GA4_KEY_EVENTS`. | Invented events; key events without configuration stay UNKNOWN. |
| **Google Trends** | Relative interest (0–100) over time and a rising/stable/falling summary. | Absolute volumes; scraping trends.google.com. Requires official (alpha/allow-listed) API access. |
| **Pinterest Trends** | Visual/idea trend signals: growing keywords per region with week-over-week / year-over-year growth. | Scraping pinterest.com. Requires a Pinterest developer app with `trends:read`. |

## States

Every provider reports one of (`contentos.integrations.enums.ProviderState`):

| State | Turkish badge | Meaning |
| --- | --- | --- |
| `healthy` | Bağlı | The last connection test or sync succeeded. |
| `not_configured` | Yapılandırılmadı | Required env variables are missing. No call is made. |
| `access_required` | API erişimi gerekli | Credentials are missing for an access-gated API (Google Trends, Pinterest) or the vendor refused them (401/403, token exchange refused, property not visible). |
| `rate_limited` | Kota sınırında | Vendor 429 (after backoff) / vendor units exhausted / ContentOS daily budget exhausted. |
| `degraded` | Kısıtlı | Timeouts or 5xx after retries. Configured-but-untested providers show "Henüz doğrulanmadı". |
| `error` | Hata | Any other typed failure (malformed body, unexpected HTTP status, unusable service-account key). |

Errors are persisted as **bounded machine classes** (`last_error_class`),
never vendor text: `semrush_http_401`, `semrush_api_132`,
`google_search_console_timeout`, `google_token_http_400`,
`pinterest_trends_daily_budget`, `google_analytics_malformed_body`, …

## Environment variables

All are optional. Empty values mean "unset". Set them in `.env`;
`compose.yaml` passes every one of them into the `api` and `worker`
containers. Restart both after changing them (`docker compose up -d api
worker`). Secrets never appear in API responses, logs, the admin, or the
database.

### Semrush

| Variable | Purpose |
| --- | --- |
| `CONTENTOS_SEMRUSH_API_KEY` | API key from the Semrush account (Profile → Subscription info → API). Needs a plan with API units. |
| `CONTENTOS_SEMRUSH_DATABASE` | Country database, default `tr`. |
| `CONTENTOS_SEMRUSH_DAILY_BUDGET` | Requests per UTC day, default `200`. |
| `CONTENTOS_SEMRUSH_CACHE_HOURS` | Response cache TTL, default `72`. |

Endpoints used: `https://api.semrush.com/` with `type=phrase_these`
(batched, deduplicated, ≤100 keywords), `phrase_related`, `domain_organic`;
the connection test calls `countapiunits.html` (free) and reports the
remaining units. `ERROR 131/132/134` → `rate_limited`; `ERROR
120/121/130/133/135` → `access_required`; `ERROR 50 NOTHING FOUND` → an empty
result.

### Google service account (Search Console + GA4)

| Variable | Purpose |
| --- | --- |
| `CONTENTOS_GOOGLE_SERVICE_ACCOUNT_JSON` | The service-account key: either the JSON content itself or a path to the key file (mount it into the containers). |
| `CONTENTOS_GSC_SITE_URL` | The Search Console property exactly as listed: `https://konsepthane.net/` (URL prefix) or `sc-domain:konsepthane.net`. |
| `CONTENTOS_GSC_DAILY_BUDGET` / `CONTENTOS_GSC_CACHE_HOURS` | Default `500` / `12`. |
| `CONTENTOS_GA4_PROPERTY_ID` | Numeric GA4 property id (Admin → Property settings), with or without the `properties/` prefix. |
| `CONTENTOS_GA4_KEY_EVENTS` | Comma-separated GA4 key event names to report. Unset → key events stay UNKNOWN. |
| `CONTENTOS_GA4_DAILY_BUDGET` / `CONTENTOS_GA4_CACHE_HOURS` | Default `500` / `12`. |

Setup: Google Cloud → IAM → Service accounts → create → Keys → add JSON key.
Enable the *Google Search Console API* and the *Google Analytics Data API*
on the project. Then add the service account e-mail as a user to the Search
Console property (Full or Restricted permission) and to the GA4 property
(Viewer). The adapter mints a scoped access token itself (RS256 JWT bearer
via `google-auth`'s signer, token exchange over httpx) and caches it until
shortly before expiry. Search Console test = `GET sites/{siteUrl}`
(reports `permissionLevel`); GA4 test = `GET properties/{id}/metadata`.

### Google Trends

| Variable | Purpose |
| --- | --- |
| `CONTENTOS_GOOGLE_TRENDS_API_KEY` | API key for the official Google Trends API (alpha / allow-listed access granted by Google). Without it the provider is `access_required`. |
| `CONTENTOS_GOOGLE_TRENDS_API_URL` | Base URL override (default `https://trends.googleapis.com/v1beta`). |
| `CONTENTOS_GOOGLE_TRENDS_DAILY_BUDGET` / `CONTENTOS_GOOGLE_TRENDS_CACHE_HOURS` | Default `200` / `24`. |

The adapter targets `GET {base}/interestOverTime?terms=…&geo=TR` with the
key sent as `X-Goog-Api-Key`, and accepts both a `series[].points[]`
payload and a `timelineData[]` payload. Because the official API is not
generally available, verify the endpoint shape when access is granted and
adjust `google_trends.py` if needed — the state machine, budget and cache
do not change. `summary()` derives rising/stable/falling from the last 12
points vs the previous 12 (±15 %); values are always relative.

### Pinterest Trends

| Variable | Purpose |
| --- | --- |
| `CONTENTOS_PINTEREST_ACCESS_TOKEN` | Access token of a Pinterest developer app (developers.pinterest.com) with the `trends:read` scope. Without it the provider is `access_required`. |
| `CONTENTOS_PINTEREST_REGION` | Default region, default `TR`. |
| `CONTENTOS_PINTEREST_DAILY_BUDGET` / `CONTENTOS_PINTEREST_CACHE_HOURS` | Default `200` / `24`. |

Endpoint: `GET https://api.pinterest.com/v5/trends/keywords/{region}/top/{growing|monthly|yearly|seasonal}`
(`include_keywords` for a single keyword). The connection test requests one
growing trend for the configured region.

### Shared

| Variable | Purpose |
| --- | --- |
| `CONTENTOS_INTEGRATIONS_HTTP_TIMEOUT_SECONDS` | Per-call HTTP timeout, default `20`. Connection tests use a 4 s cap so the admin answers within its request window. |

## Cost control

Migration `0033` adds three tables:

- `integration_status` — one row per provider: state, Turkish detail,
  `checked_at`, `last_success_at`, `last_error_class`, `last_sync_at`.
- `provider_request_log` — requests actually sent per provider per UTC day
  (`UNIQUE(provider, day)`); the daily budget is enforced with an atomic
  bounded increment.
- `provider_cache` — parsed payloads keyed by a sha256 of the request
  identity (the API key is never part of it), with `expires_at`.

`BudgetedClient.cached(parts, fetch)` is the single path for provider
reads: cache lookup → budget check (`<provider>_daily_budget` when spent)
→ the real call → cache store; identical concurrent calls in one process
are deduplicated behind a per-key lock. `ProviderHttp` retries 429/5xx/
timeouts at most twice with exponential backoff and honours `Retry-After`
(waits up to 5 s; longer values are reported as `rate_limited`).

Stores use the caller's session when one is bound
(`contentos.integrations.sessions.bind_session(session)`; the API and
worker do this) and otherwise open their own short-lived session.

## Observations → SearchSignal

`contentos.integrations.observations` appends provider observations to the
existing `search_signals` history (append-only, idempotent via
`observation_hash`):

- `record_keyword_metrics` → `search_volume` signals for Semrush keywords
  whose volume is **known**; `value` carries `unit`, `basis`, `provider`,
  `metrics` (KD/CPC/competition/intent when present) and `observed_at`.
- `record_trend_summary` → `trend` signals for Google Trends with
  `relative: true`, direction and an optional seasonality hint.
- `record_pinterest_trend` → `trend` signals for Pinterest with
  `relative: true` and the growth percentages.
- `freshness_for(session, provider, subject)` → newest observation time
  or `None` (UNKNOWN).

## API and registry

- `GET /internal/integrations` — every provider: `state`, `configured`,
  `verified` (a status row exists), `detail`, `checked_at`,
  `last_success_at`, `last_error_class`, `freshness` (= `last_sync_at`),
  `daily_budget`, `requests_today`, `cache_hours`, `required_env`,
  `optional_env`. Reads persisted rows; computes `not_configured` /
  `access_required` live; never calls a vendor.
- `POST /internal/integrations/{name}/test` — runs the provider's ONE
  cheap real call, persists the outcome, returns the same view. `404` for
  an unknown name.
- `IntegrationRegistry(settings, session_factory)` /
  `create_integration_registry(settings, session_factory)` — `providers()`,
  `get(name)`, `statuses(session)`, `test(session, name)`,
  `record_success(session, name)`, `record_error(session, name,
  error_class, kind=…)`. The worker composes one registry per process;
  scheduling of syncs lives outside this module.

## "Bağlantıyı Test Et" flow

1. The operator sets the variables in `.env` and restarts `api` and
   `worker`.
2. `/entegrasyonlar` shows the provider as "Henüz doğrulanmadı"
   (configured, no status row yet).
3. "Bağlantıyı Test Et" submits the server action → `POST
   /internal/integrations/{name}/test` → one cheap vendor call (units check,
   site entry, property metadata, one trend row) → the durable status row
   is written and the card shows Bağlı / API erişimi gerekli / Kota
   sınırında / Kısıtlı / Hata with the bounded error class.
4. Unconfigured providers never call out: the test reports
   `not_configured` / `access_required` and stores nothing.
