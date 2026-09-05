# Konsepthane Idea & Content Intelligence Engine

ContentOS is not a rewriting machine for other sites' articles. It is the
closed loop that turns outside signals into Konsepthane's own ideas, produces
governed content from them, and learns from what that content does once it
is live:

```
Discover → Understand → Evaluate → Produce → Publish → Measure → Learn → Improve
```

Two sentences are architecture invariants and bind every module:

> **External content is a signal, not a template to reproduce.**

> **Strategic keywords guide discovery and editorial planning; they are not
> keyword-stuffing instructions.**

## The vocabulary, and how each concept differs from its neighbours

| Concept | What it is | What it is NOT |
| --- | --- | --- |
| **SOURCE** | A registered origin (site, feed, sitemap, provider) with a technical `kind` (how it is acquired), an editorial `primary_role` and `capabilities` (which signal families it may yield). | A template. A source never becomes an opportunity by itself. |
| **SIGNAL** | A durable, bounded, provenance-carrying observation extracted from a source or a provider: inspiration, community need, market, competition, taxonomy, search, trend, visual trend, historical performance. | Raw text. Community signals are PII-free patterns; nothing else is kept. |
| **IDEA** | A concrete, original content direction synthesised from several signals for one opportunity (`Idea` versions with originality checks). | A spun source title. |
| **STRATEGY** | Konsepthane's growth intent: target audiences, the keyword portfolio, topic clusters. A priority signal for discovery, evaluation and planning. | A filter that throws away what is not on the list. Unexpected, trending ideas must still surface. |
| **SEARCH INTELLIGENCE** | External SEO market data (Semrush: volume, difficulty, intent, CPC, competition) with provider, database, freshness. | Our real performance. Estimates are never shown as Search Console truth. |
| **TREND** | Relative interest over time (Google Trends API, access-gated), *discovery* of the daily Türkiye top / rising query sets (Google Trends BigQuery Public Dataset, active), visual/idea trend (Pinterest Trends), with direction, rank and freshness. Stored as relative interest or list observation, never as search volume. | Search volume. Scraped data. "Not in the top/rising set" read as "low trend" — absence is NOT_OBSERVED. |
| **OPPORTUNITY** | A researched content candidate: the synthesis of signals + idea intelligence + strategy fit + search/trend intelligence + Konsepthane's own data, with an explainable recommendation (ÜRET / ARAŞTIRMAYA DEVAM ET / ELE / İNSAN İNCELEMESİ). | A URL. A single score without a reason. |
| **EVIDENCE** | `ResearchEvidence` statements with the full provenance chain to a fetch snapshot. Only sources whose role permits it produce evidence. | AI output. Community posts. Model pretraining. |
| **CONTENT** | Brief → draft → editor review → QA → publication package, every step pinned and versioned. | A rewrite of a source article. |
| **PUBLICATION** | The exact approved package sent through the Publishing API, bound to a canonical Konsepthane URL. **Published is not done; published is measurement started.** | The end of the item's life. |
| **PERFORMANCE** | Append-only snapshots per provider (Search Console = our truth; GA4 = on-site behaviour; Semrush/Trends = market context) and windowed assessments (7/28/90 days): insufficient data, rising, stable, declining, volatile, unknown. | A judgement after three days of data. |
| **HISTORICAL SIGNAL** | "What works on Konsepthane" as structured data per cluster / audience / theme / format, with the publications and metrics that support it. A priority signal for new opportunities. | A rule that clones past winners. |
| **REFRESH** | A human-decided update opportunity for declining or aged content, with a diagnosis and the original provenance intact. | An automatic republish. |

## Two things that must never be conflated

- **Community interest ≠ search demand.** A forum full of the same question
  is a user need. It says nothing about Google volume. Both are stored,
  neither pretends to be the other; `Community Interest: HIGH` next to
  `Search Demand: UNKNOWN` is a valid and honest state.
- **Inspiration quality ≠ search opportunity.** A keyword may be strong while
  every idea found for it is a cliché; the recommendation is then
  ARAŞTIRMAYA DEVAM ET, never automatic production.

## Inspiration quality

Inspiration quality is an explainable editorial heuristic over ten factors:
novelty, usefulness, specificity, visual potential, shareability, emotional
impact, audience fit, Turkish market applicability, variation potential,
strategic fit. The operator sees a band ("İlham Değeri: Çok Yüksek") and one
sentence of why; the factors and their basis stay available under the
detail. "Restoranda evlenme teklif edin" is low; "dönme dolabın en yüksek
noktasında, partneriniz manzaraya bakarken yüzüğü çıkarın" is specific,
visual and shareable — the engine must tell those apart.

## Human gates

The machine fetches, normalises, extracts, evaluates, enriches from every
configured provider and proposes. The named human decides:

1. Should Konsepthane produce this researched opportunity? (commissioning)
2. Should the prepared package be published? (ADR 0004)
3. Should this published content be refreshed? (refresh opportunity)
4. Should this strategy suggestion enter the strategy? (strategy suggestion)

Nothing else asks the operator a question. Missing provider data stays
UNKNOWN and never blocks the line.

## Where each piece lives

- Sources, roles, capabilities: `docs/INTAKE_ORCHESTRATION.md`
- Signal families and privacy: `docs/INTELLIGENCE_SIGNALS.md`
- Providers and credentials: `docs/INTEGRATIONS.md`
- Opportunity intelligence and recommendation policy: `docs/IDEA_INTELLIGENCE.md`
- Measure → Learn → Improve: `docs/PERFORMANCE_LOOP.md`
- Autopilot and human gates: `docs/adr/0012-autopilot-bounded-autonomous-editorial-line.md`
