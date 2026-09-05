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

Navigation (operator's path, then the system section): Kontrol Merkezi
(`/kontrol`), Çalışmalar (`/calisma`), Kaynaklar (`/sources`), Fikirler
(`/fikirler`), İçerikler (`/editorial`), Benden Bekleyenler
(`/firsatlar`), Strateji (`/strateji`), Performans (`/performans`),
Entegrasyonlar (`/entegrasyonlar`); Sistem: Sistem Sağlığı (`/`), Canlı
Operasyon (`/operasyon`), Gelişmiş Motor (`/motor`), Teknik Görünümler
(`/research`).

- `Çalışmalar` (`/calisma`): run history; `/calisma/{id}` is the live
  operation view: the full Turkish line as a vertical stage list
  (Kaynak taranıyor → URL'ler keşfediliyor → Ön eleme → İçerikler
  getiriliyor → İçerik anlaşılıyor → Fikirler çıkarılıyor → Benzer
  fikirler gruplanıyor → Topluluk sinyali → Pazar sinyali → Strateji
  eşleşmesi → Semrush → Google Trends → Pinterest Trends → Konsepthane
  geçmiş verisi → Fırsat; intake stages from the run view, signal stages
  from `GET /internal/intelligence/summary?run_id=`, provider stages from
  `/internal/integrations`; no data → "veri yok" / "bekleniyor"), the
  Turkish event feed, results and controls; 5-second bounded polling via
  server re-render.
- `Fikirler` (`/fikirler`): what the system found — open and commissioned
  ideas grouped as Güçlü fikirler / İncelenmeli / Araştırma sürüyor /
  Elenenler with the explainable intelligence sections; read-only.
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
- `Canlı Operasyon` (`/operasyon`): the ADR 0012 autopilot mode switch, the
  AI gateway's health and running job, running intake runs, the editorial
  line with the autopilot's last word per item, and one merged feed;
  5-second polling.
- Kontrol Merkezi: "Benden Bekleyenler" lists only the four genuine
  human decisions (üretim kararı, yayın onayı, güncelleme kararı, strateji
  önerisi) with real counts; `/firsatlar` hosts all four.
- Raw discovery-item accept/fetch controls remain ONLY on the
  research (advanced) detail pages as a debug capability.

## Source purpose: kind (technical) vs role / capabilities (editorial)

A source carries two orthogonal descriptions (migration `0031`):

- `kind` + `discovery_strategy` are TECHNICAL: how content is acquired
  (`rss_feed`/feed, `sitemap`/sitemap, `manual`/manual, provider
  placeholders). Discovery, fetching and robots handling depend only on
  these; nothing here changed.
- `primary_role` + `capabilities` are the EDITORIAL PURPOSE: why we read
  the source and which signal families it may yield. Roles:
  `inspiration`, `turkish_editorial`, `community_intent`, `competitor`,
  `taxonomy`, `trend`, `search`. Capabilities: `inspiration`,
  `community_need`, `market`, `competition`, `taxonomy`, `search`,
  `trend`, `visual_trend`. A source is never locked into one role: the
  role picks a default capability set
  (`default_capabilities_for(role)`, e.g. `turkish_editorial` →
  inspiration + market + competition + taxonomy) and the operator may
  widen or narrow it. Capabilities are validated (known values only,
  non-empty), deduplicated and stored in canonical enum order.
- Existing rows became `inspiration` / `["inspiration"]` through server
  defaults; registration without the fields keeps that behaviour.
- API: `POST /internal/research/sources` accepts optional `primary_role`
  and `capabilities`; `POST /internal/research/sources/{id}/purpose`
  changes them later (audited as a same-state `source_lifecycle_events`
  row whose reason names the new role and capabilities). The source list
  and pipeline-detail read models expose both fields.
- Admin `/sources/new` and the per-row "Amacı düzenle" editor ask
  "Bu kaynak ne için kullanılsın?" with Turkish checkboxes and a
  "Birincil rol" select; the list shows role + capability badges.
- Consumers ask `SourceRegistryService.capabilities_for(source)` /
  `has_capability(source, capability)` rather than reading the JSON.

Community-source evidence rule: a source whose `primary_role` is
`community_intent` (the `community_need` family) NEVER becomes a
`ResearchEvidence` source. `SourceRegistryService.evidence_allowed(source)`
is the single predicate; `ResearchEvidenceService.record_evidence`
refuses such documents with `ResearchDocumentNotEligibleError` before any
row exists, and every future evidence writer (including the community
signal extractor) must call the same predicate. Community raw text is
never persisted; only PII-free normalized signals are.

## Honest limits (deliberate)

- No AI relevance/taxonomy classifier exists; "relevance" today is the
  deterministic explainable opportunity score. Building an AI relevance
  agent is future work and must not be faked in the UI.
- Score-ineligible opportunities are NOT auto-rejected: opportunity
  rejection is a named human decision (Phase 5); the UI surfaces them
  as ATLA recommendations for a one-click human reject instead.
