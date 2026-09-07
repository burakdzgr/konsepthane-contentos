# Research Missions — the Research-Driven Idea Engine

ContentOS used to be **source-driven**: register a source → discover its
pages → fetch, normalize, extract → cross-check with other sources → promote
an opportunity. That model rewards topics many sites already cover and
punishes original concepts, which is the opposite of Konsepthane's value.

Since 2026-09-07 the primary starting object is the **Research Mission**
(`research_missions`): an operator states a research goal, and ContentOS
plans and executes the research itself. Sources are no longer the
precondition or the decision mechanism; they are research *surfaces* the
mission may consult next to the open web, keyword/trend providers and
community signals.

```
Research Mission (topic, goal, audience, optional keyword/cluster)
  → PLANNING    intent, keyword expansion, query plan, cliché patterns, primitive hints
  → KEYWORDS    demand (Search Console) / trend (Google Trends BigQuery) per keyword; UNKNOWN otherwise
  → SEARCHING   registered sources · open web · visual inspiration (site:pinterest.com) · community · trend
  → EXTRACTING  idea primitives ("mechanics") + candidates (extracted / synthesized)
  → CLUSTERING  near-duplicates merged deterministically
  → EVALUATING  idea quality, cliché filter, strategy fit, recommendation
  → GROUNDING   pages behind strong ideas fetched through the normal intake chain
  → PROMOTING   strong grounded ideas → EditorialOpportunity (idea-led)
  → existing chain: score → commission → ideas → pack → brief → writer → editor → QA → media → publish
```

## Modules

| Piece | Where |
| --- | --- |
| Durable state | `missions/models.py` (`research_missions`, `mission_signals`, `mission_idea_candidates`), migration `0039` |
| Engine | `missions/engine.py` — stages, model calls, deterministic scoring/clustering/cliché, grounding, promotion |
| Structured contracts | `missions/schemas.py` — `mission-plan/1`, `research-signals/1`, `idea-synthesis/1` |
| Worker | `worker/mission_tasks.py` — `contentos.research.run_mission`, `contentos.research.finalize_mission` |
| API | `api/routes/missions.py` — `POST /internal/research-missions` (creates **and queues**), `GET …/{id}`, `POST …/{id}/run` |
| Admin | `/research` (Yeni araştırma başlat + live progress), `/research/hat` (the old mechanical pipeline view) |

## Two separate confidences

* **Idea quality / idea confidence** — creative merit of a concept: novelty,
  usefulness, specificity, visual potential, shareability, emotional impact,
  audience fit, Türkiye applicability (0–100 each, weighted in
  `QUALITY_WEIGHTS`). A single research signal never makes an idea "weak":
  a creative idea is not a factual claim.
* **Factual evidence confidence** — stays `unknown` on the candidate; only
  the evidence pipeline (fetch → normalize → extract → verify) raises
  anything above it. Every factual statement in the final content is still
  bound to `ResearchEvidence` by the Writer/Editor/QA rules.

Mission signals (`mission_signals`) are **inspiration provenance**. Their
`provenance.is_factual_evidence` is always `false`; they never become
evidence rows.

## What "not source-driven" means in code

* `EditorialOpportunity.mission_candidate_id` marks an idea-led opportunity.
* Scoring: `IdeaLedScoringEngine` (`opportunities/scoring.py`) makes the
  mission's idea quality (`EDITORIAL_VALUE`, weight 0.45) the dominant known
  component; source diversity keeps a 0.03 weight as context, and the bands
  are `strong ≥ 0.70`, `moderate ≥ 0.55`. Intake promotions keep engine v1.
* Evidence pack: `IDEA_LED_EVIDENCE_POLICY` (1 item, 1 source, 0 key facts)
  is selected automatically for idea-led opportunities; the intake policy
  (`default/1`: 3 items, 2 sources, 1 key fact) is unchanged.
* Idea generation: `IDEA_LED_IDEA_ORIGINALITY_POLICY` (1 source) and a
  `mission_seed` in the projection (the synthesized concept, its mechanics,
  steps and the claims that still need grounding).
* Autopilot: `Snapshot.idea_led` lets idea regeneration proceed without a
  second source; every later gate (brief acceptance, writer/editor/QA
  policies, media, human approval, publishing) is untouched.

## Providers and the UNKNOWN rule

* Planning, open-web research and idea synthesis run through the configured
  text provider (the subcontractor gateway locally). Without a provider the
  mission still runs: deterministic plan, registered-source signals only,
  extracted candidates only, and the summary says so.
* Search demand comes from Google Search Console when configured
  (`observed` / `not_observed`), otherwise `unknown`. Trend comes from the
  Google Trends BigQuery observations already synced (`observed` /
  `not_observed` / `unknown`). Nothing is estimated.
* Pinterest: no API, no scraping. `site:pinterest.com …` queries are part of
  the open-web research and their hits are `visual_inspiration` signals.
  When the Pinterest API arrives the existing provider adds real data.

## Grounding

Open-web signals carry URLs the model reports (`url_verified: false`). For
promotable candidates the engine registers one `SEARCH`-role source per
domain (`web-<domain>`, metadata `open_web_grounding`), admits the URL as a
manual discovery item and dispatches the normal fetch chain (robots,
snapshot, normalization, duplicate decision, deterministic + model
evidence). `SEARCH` sources never promote opportunities of their own (role
gate), so the only opportunity is the mission's. `finalize_mission` re-checks
every minute for up to 15 minutes and promotes candidates whose signals now
have a normalized document; whatever is not grounded by then stays a
candidate.

### Contextual grounding and the strong-candidate cap

Synthesized ideas often cite only URL-less signals (model recall, visual
inspiration). Such a strong candidate is grounded with the topic pages that
share the most distinctive tokens with it — registered sources first
(`_context_signals`, at most 2) — and the never-fetched registered pages are
pulled through the intake chain on demand. Those pages are *context inputs*
for the later evidence work, never "the source of the idea". Model factor
scores run generous, so at most `MAX_PROMOTE_RECOMMENDED` (8) candidates
keep the `promote` recommendation; the rest become `continue_research`
with the reason recorded. Every rerun increments `result_summary.run_number`
so the three model calls are fresh attempts, never reused.

## Operator experience

Create a mission with four fields: topic, goal, audience, optional keyword
and optional topic cluster. The page shows live stages ("Konu analiz
ediliyor", "Anahtar kelimeler araştırılıyor", …), the elimination summary
("25 fikir: 8 klişe elendi, 6 birleştirildi, 11 güçlü aday"), keyword
demand/trend (or "Bilinmiyor"), candidates with mechanics, steps, factors,
both confidences, and links to the opened content opportunities.

## Live acceptance run (2026-09-07, local stack, real gateway)

Mission: "İlginç Evlilik Teklifleri" — goal "Türkiye için gerçekten yaratıcı
ve uygulanabilir 20 fikir bul", audience "20–35 yaş çiftler". The operator
gave nothing else.

* PLANNING (model): 8 keywords, 12 TR/EN queries, 10 cliché patterns
  ("Sahilde gün batımında teklif", "Şık restoranda yüzüğü tatlının içine
  koymak", "Boğaz manzarasında diz çökerek teklif", …), primitive hints.
* KEYWORDS: Search Console consulted — every keyword `not_observed` on the
  site (truthful: konsepthane.net has no proposal traffic yet); Google Trends
  TR lists — `not_observed`. Nothing estimated.
* SEARCHING: 70 signals — 30 registered-source pages (Düğün.com proposal
  articles and community threads matched by URL slug; 42 000 of the local
  discovery items have no title), 24 open-web + 10 visual + 6 community
  signals from the model. Live browsing froze the ChatGPT tab twice
  (gateway protocol timeout), so those 40 are labelled `model_recall`
  without URLs — the mission says so in its surface summary.
* EXTRACTING / CLUSTERING / EVALUATING: 22 idea mechanics, 22 candidates,
  2 merged, 8 strong (cap), 12 "araştırmaya devam"; synthesized examples:
  "Ortak Haritada Henüz Gitmediğimiz Tek Nokta" (harita + kronolojik anlatı
  + gelecek odaklı anlatı + gizli mesaj), "Kutu Açıldıkça Gelecek Yaklaşsın"
  (katmanlı reveal + gelecek odaklı anlatı), "QR Kodlu Cep Müzesi", "Hobinin
  Final Seviyesi" — all idea quality 92, factual evidence confidence
  `unknown`.
* GROUNDING / PROMOTING: 8 Düğün.com pages fetched through the intake chain
  (10 context links); 4 idea-led opportunities opened, 1 candidate stayed
  ungrounded. Idea-led scores: one `commissionable` (0.74 — its grounding
  page yielded 10 evidence rows), three `needs_operator_review` (0.58 — old
  duplicate-of-earlier pages with no evidence yet). A single source was
  never the reason for a rejection; thin grounding was, and it is reported
  as such.
