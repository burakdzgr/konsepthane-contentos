# Performance loop: Measure → Learn → Improve

Status: implemented baseline, 2026-09-05 (migration `0034`).

> **PUBLISHED ≠ DONE. PUBLISHED = MEASUREMENT STARTED.**

ContentOS treats a successful publication as the start of a measurement
cycle. Real provider observations are recorded as immutable snapshots,
classified into honest statuses, turned into human-gated refresh
opportunities when a content declines, and folded into a priority-only
historical signal plus bounded strategy suggestions when outcomes are
clear. Nothing in this loop publishes, rewrites, or filters anything on
its own.

## What is measured

| Fact | Table | Notes |
| --- | --- | --- |
| Measurement started | `published_contents` | One row per work item, written by the worker right after the publication attempt succeeds (`record_publication_fail_safe`, fail-safe) or by `PerformanceService.backfill_published` for older successes. `canonical_url` is set ONLY when the remote publication reference is an absolute URL; otherwise it stays NULL and the admin shows "Yayın adresi bilinmiyor". Strategy context (cluster, audience, theme, format) is derived from the selected idea + `StrategyService.context_for_text`; absent context stays NULL. |
| Provider observation | `content_performance_snapshots` | Append-only (PostgreSQL trigger). Identity = `sha256(content|provider|period_start|period_end|observed day)`, so a re-sync on the same day converges. Search Console: daily rows (impressions, clicks, ctr, position) + one 28-day summary row with `top_queries` (≤ 20). GA4: daily rows (users, sessions, views, engagement_rate, key_events) + summary. Semrush / Google Trends / Pinterest: one observation per provider per day for the content's REAL top queries (max 3); no query → nothing asked, nothing invented. |
| Classification | `performance_assessments` | Append-only; a new row only when the verdict or its basis changed. Windows 7 / 28 / 90 days. `engine_name=performance-classifier`, version `1`. |
| Refresh decision | `refresh_opportunities` | `proposed → approved | dismissed | superseded`; one open proposal per content (service rule + partial unique index). |
| Strategy suggestion | `strategy_suggestions` | `proposed → accepted | ignored`; deduplicated by `sha256(kind|normalized title)`. |

The historical signal lives in `intelligence_signals` (family
`historical_performance`, provider `contentos-performance`).

## Windows, thresholds, statuses

The classifier (`contentos.performance.classifier`, pure, table-driven
tests) compares the last `window_days` of Search Console daily points
with the previous equal window. The window is anchored on the latest
observed day (Search Console lags ~2 days), never on "today".

Thresholds are Settings (`CONTENTOS_PERFORMANCE_*`) and are snapshotted
into every assessment basis:

| Setting | Default | Meaning |
| --- | --- | --- |
| `performance_min_impressions` | 100 | Below this in either window → `insufficient_data` |
| `performance_min_days` | 7 | Fewer observed days in either window → `insufficient_data` |
| `performance_decline_pct` | 0.25 | Impressions or clicks drop ≥ 25 % |
| `performance_rise_pct` | 0.25 | Impressions or clicks grow ≥ 25 % |
| `performance_volatility_pct` | 0.5 | The two halves of the current window differ ≥ 50 % |

| Status | Turkish | Rule |
| --- | --- | --- |
| `unknown` | Bilinmiyor | No Search Console daily snapshot at all |
| `insufficient_data` | Yetersiz veri | Too few days or impressions in either window. A new content is NEVER "declining". |
| `declining` | Düşüyor | Impressions or clicks dropped ≥ decline_pct AND average position got worse |
| `rising` | Yükseliyor | Impressions or clicks grew ≥ rise_pct AND position did not get worse |
| `volatile` | Dalgalı | Sub-period swing ≥ volatility_pct (checked after decline/rise) |
| `stable` | Stabil | Everything else |

Position is impression-weighted. Every basis carries both windows
(days, impressions, clicks, position, ctr), the deltas, the sub-period
swing, the sample size and the thresholds, so a verdict can always
explain itself.

## Historical signal: priority, never a filter

`HistoricalPerformanceService.aggregate` folds the latest 90-day
assessment of every published content into one `IntelligenceSignal` per
strategy grain: the full key (cluster | audience | theme | format), the
cluster alone, the audience alone and the theme alone. A group with no
REAL verdict (only `insufficient_data` / `unknown`) writes nothing — an
absence is not a zero. Value: `outcome` (positive when rising verdicts
outnumber declining ones, negative when the reverse, neutral otherwise),
`publications`, `assessments`, `metric_basis`, `window_days=90`,
`real_metric_count`, `priority_only=true`.

`historical_signal_for(session, *, cluster_id, audience_id, theme_key,
content_format) -> HistoricalSignal(band, outcome, basis)` answers from
the most specific known grain. Band: `strong` (≥ 3 real verdicts and a
non-neutral outcome), `moderate` (≥ 2), `weak` (1), `unknown` (no
history). Consumers ORDER candidates with it. They never eliminate an
idea because of it: unexpected ideas must stay visible, and a negative
history can only lower a priority.

## Refresh opportunity flow (human gate)

1. `detect` runs after `assess`. For every content whose latest 28- or
   90-day verdict is `declining`, ONE proposal is written (none if an open
   proposal exists or the same trigger assessment was already decided).
2. The diagnosis contains only what was actually computed: position
   movement, impressions/clicks deltas, content age, query changes
   between the two newest Search Console summaries (lost / new queries,
   position drops ≥ 2), new inspiration/intelligence signals whose concept
   key matches the content's queries or theme and were observed after
   publication, strategy fit (`StrategyService.context_for_text`), and a
   cannibalization hint (other published contents sharing top queries).
   The recommendation is Turkish and always ends with the reminder that
   approval only starts re-research.
3. `approve(refresh_id, user, reason)` requires a NAMED user and a reason.
   It moves the work item through the existing canonical transitions
   only: `PUBLISHED | PINTEREST_PENDING | DISTRIBUTED → MEASURING →
   REFRESH_CANDIDATE` (or `MEASURING → REFRESH_CANDIDATE`), recording the
   operator as actor and the refresh/assessment ids in `artifact_refs`.
   The next step — `REFRESH_CANDIDATE → RESEARCHING` — stays with a human
   or the autopilot's governed path. Nothing is published; the original
   package, attempt and provenance chain are untouched.
4. `dismiss(refresh_id, user, reason)` records the decision and leaves the
   workflow state as is.

Admin: `/performans#guncelleme` and the content detail page offer
"Güncellemeyi Onayla" / "Şimdilik Geç" with a mandatory reason. Kontrol
Merkezi's "Benden Bekleyenler" counts pending refresh decisions
(`attention.refresh_decisions`).

## Strategy suggestions flow

`StrategySuggestionService.generate` looks at the latest 90-day verdicts
with REAL metrics, grouped by cluster, audience and theme. A focus
suggestion needs at least 3 publications in the group with ≥ 60 % rising.
A `keyword_add` suggestion needs a top query shared by ≥ 3 rising/stable
publications that is not yet a strategic keyword. At most 10 suggestions
per run, 5 of them keyword additions. Example title: "Soft Animal 1 Yaş
kümesine odaklan" with the rationale "… 3 yayının 3 tanesi son 90 günde
yükseliyor → bu kümenin alt konu araştırmasını artır."

`accept(id, user, reason)` applies ONE bounded change through
`StrategyService`: cluster/audience priority +10 (capped at 100), or a
new strategic keyword (priority 60, linked to the dominant cluster). The
applied change is recorded in `basis.applied`. `ignore` records the
decision. Suggestions never pause, archive or remove strategy.

## Anti-self-reinforcement rule

- The historical signal orders; it never filters. Every candidate stays
  visible regardless of history.
- Suggestions only ADD focus or keywords and only when ≥ 3 publications
  carry real metrics; they never remove or demote anything, and they only
  take effect through a named human decision.
- New or data-poor contents are `insufficient_data`, never `declining`,
  so the loop cannot punish topics it has not measured.
- Every learned fact keeps its evidence (publication ids, assessment ids,
  metric basis) so an operator can challenge it.

## Worker and schedule

Tasks (`contentos.worker.performance_tasks`, all `bind=True`,
`shared=False`, bounded to 200 contents per run, provider errors caught
and classified — never a crash, never a fabricated metric):

| Task | Purpose |
| --- | --- |
| `contentos.performance.sync_search_console` | last 28 days by date + top queries per content with a URL |
| `contentos.performance.sync_analytics` | GA4 last 28 days by date |
| `contentos.performance.refresh_market_signals` | Semrush / Google Trends / Pinterest for the top 3 queries, one observation per provider per day |
| `contentos.performance.assess` | classify every content for 7 / 28 / 90 |
| `contentos.performance.detect_refresh` | propose refresh opportunities |
| `contentos.performance.aggregate_history` | write the historical signal |
| `contentos.performance.suggest_strategy` | write bounded suggestions |
| `contentos.performance.sync_all` | the manual "Şimdi senkronize et" chain (backfill first, then all of the above in order) |

Provider outcomes are persisted through the integration registry
(`record_success` / `record_error`), so the Ayarlar/Entegrasyonlar status
and the Performans freshness line agree.

Celery beat (`contentos.queue.celery`, guarded by
`CONTENTOS_PERFORMANCE_SCHEDULE_ENABLED=true`): Search Console 03:00 UTC,
GA4 03:10, market signals every `CONTENTOS_PERFORMANCE_MARKET_INTERVAL_HOURS`
(24), assess 04:00, detect 04:10, history 04:20, suggestions 04:30. The
`beat` compose service runs `python -m contentos.worker.main beat
--schedule /tmp/celerybeat-schedule`; run exactly one instance.

## API

- `GET /internal/performance/overview?window=7|28|90`
- `GET /internal/performance/contents/{work_item_id}`
- `GET /internal/performance/refresh-opportunities?status=`
- `POST /internal/performance/refresh-opportunities/{id}/approve|dismiss` (`{reason}`)
- `GET /internal/performance/strategy-suggestions?status=`
- `POST /internal/performance/strategy-suggestions/{id}/accept|ignore` (`{reason}`)
- `POST /internal/performance/sync`

No response carries provider credentials, URLs with keys, or raw provider
bodies; provider failures surface only as bounded states and error
classes.
