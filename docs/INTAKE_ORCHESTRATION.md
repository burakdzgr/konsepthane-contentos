# Autonomous intake orchestration (runs)

"Keşfi Başlat" starts an **IntakeRun**: a durable, bounded, resumable
orchestration that carries a source from discovery to scored content
opportunities WITHOUT asking the operator to approve raw URLs. A URL is
a machine fact; the first human question is the editorial one — "should
Konsepthane produce content on this topic?" — answered on the
Fırsat İncelemesi screen (commission/reject with a required reason).

## The run

```
discovery      sitemap/feed traversal via the existing strategies
prefilter      deterministic URL classification; rejections recorded
               through DiscoveryService.reject with coded reasons
               ("intake prefilter: listing:tag", asset_extension, …)
bounded fetch  batches of the frozen fetch task; the worker-owned
               fetch → normalize → duplicate chain is unchanged
promotion      eligible unique documents through the frozen promote
               task, which chains deterministic opportunity scoring
```

Everything downstream (idea generation, evidence selection, drafting,
review, QA, human approval, publishing) keeps its existing governance;
the orchestrator can neither commission nor reject an opportunity,
select an idea, or advance workflow state — it only drives transitions
the domain model already permits, through the existing services and
tasks. Queue completion alone still never mutates editorial state.

## Bounds (settings, snapshot into each run)

- `intake_prefilter_batch_size` (1000/step)
- `intake_fetch_batch_size` (8) and `intake_max_fetches_per_run` (40)
- `intake_daily_fetch_budget_per_source` (150/day)
- `intake_max_promotions_per_run` (20)
- host politeness stays with the fetcher (`fetch_min_host_interval_seconds`)

Remaining candidates stay durable (ACCEPTED discovery items); a later
run continues from them. One live run per source (DB-enforced).

## Durability and safety

State: `intake_runs` (status + counters + policy snapshot) and
`intake_run_events` (append-only timeline). Every step re-derives its
decisions from durable pipeline rows, so retries, worker restarts and
at-least-once delivery are safe; per-item dispatch events prevent
duplicate fetch dispatch, promotion is DB-unique per root document, and
stalled in-flight fetches are re-dispatched after 10 minutes. The step
task uses late acknowledgement. Operational pauses (`research` scope or
the engine) park the run as PAUSED with an event; run pause/resume/stop
are audited operator controls with required reasons. "Stop" is safe:
no new dispatch, in-flight chains finish, nothing is killed.

## API

Operator-guarded under `/internal/intake`:

- `POST /sources/{id}/runs` — start (409 while a live run exists or
  research intake is paused; 422 for non-automated sources)
- `GET /runs`, `GET /runs/{id}`, `GET /runs/{id}/events?after_id=` —
  bounded projections; the events endpoint supports incremental polling
- `POST /runs/{id}/pause|resume|stop` — audited controls

## Admin

- `Çalışmalar` (`/calisma`): run history; `/calisma/{id}` is the live
  operation view (stage timeline, Turkish event feed, results,
  controls; 5-second bounded polling via server re-render).
- `Kaynaklar`: "Keşfi başlat" starts a run and opens it immediately;
  a live run shows as "Aktif çalışmayı aç".
- `Fırsat İncelemesi` (`/firsatlar`): scored open opportunities with
  the explainable score (band, eligibility → ÜRET/İNCELE/ATLA
  recommendation, missing signals, risk flags) and the
  commission/reject decision forms. The commission form is shown only
  when the row's `commission_eligible` flag is true — the backend's own
  `commissioning_admits` gate projected by the read model — so the card
  never offers a decision the command would refuse with 409; a blocked
  row shows the refusal reason instead and keeps only the reject form.
  The page groups cards by that flag (`durum=karar|orta|elenecek|hepsi`;
  the default `karar` shows ONLY commissionable cards, weak source bases
  are "Elenecekler") and filters by the system recommendation
  (`oneri=uret|insan-incelemesi|ele`), and offers
  bulk reject / bulk commission over the ticked or listed cards with one
  shared reason — each card still goes through its own backend command,
  and commissioning is only sent for `commission_eligible` cards. All
  status vocabulary is rendered in Turkish (`tr-labels.ts`).
- Kontrol Merkezi: "Benden Bekleyenler" (real human decisions only)
  and "Aktif Çalışmalar" cards.
- Raw discovery-item accept/fetch controls remain ONLY on the
  research (advanced) detail pages as a debug capability.

## Honest limits (deliberate)

- No AI relevance/taxonomy classifier exists; "relevance" today is the
  deterministic explainable opportunity score. Building an AI relevance
  agent is future work and must not be faked in the UI.
- Score-ineligible opportunities are NOT auto-rejected: opportunity
  rejection is a named human decision (Phase 5); the UI surfaces them
  as ATLA recommendations for a one-click human reject instead.
