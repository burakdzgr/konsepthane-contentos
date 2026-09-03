# Konsepthane Idea Intelligence Engine

Status: implemented baseline, 2026-09-03.

ContentOS is the editorial discovery layer of Konsepthane's future idea,
inspiration, UGC and community ecosystem. Its job is not to translate another
site's article. It discovers useful signals, preserves their origin, groups
them into ideas and turns sufficiently strong research into original
Konsepthane opportunities.

> **External content is a research/inspiration signal, not a template to reproduce.**

> **Strategic keywords guide discovery and editorial planning; they are not keyword-stuffing instructions.**

## Durable concepts and boundaries

| Concept | Meaning | What it is not |
| --- | --- | --- |
| Source | Governed origin with crawl and trust policy | Permission to copy |
| Signal | One bounded idea/concept clue extracted from a normalized source | Evidence or a finished article |
| Idea | A concrete, original direction selected after commissioning | A spun source title |
| Search intent | The need a person is trying to satisfy | Fabricated search volume |
| Strategy | Operator-managed audience, keyword and topic-cluster priorities | A censorship filter or repetition quota |
| Opportunity | A research-backed proposal for Konsepthane | Automatic permission to write |
| Content brief | The bounded writing contract | The whole keyword portfolio |
| Draft | Original text produced under the brief and claim map | A source rewrite |
| Evidence | A traceable source-backed claim unit | Model pretraining or AI output |

The provenance chain remains resolvable as source -> discovery item -> fetch
snapshot -> normalized document -> inspiration signal/research evidence ->
opportunity -> brief claim -> draft claim use. `UNKNOWN` remains different from
zero at every measurement boundary.

## Strategy layer

The normal operator manages three deliberately small concepts:

- **Hedef Kitle:** a named audience, locale/market, priority and status.
- **Keyword / Konu Hedefi:** a phrase, locale/market, priority, status, optional
  topic cluster and operator note.
- **Konu Kümesi:** an understandable content family which strategic topics
  strengthen.

Strategy ranks bounded discovery candidates and adds relevant context to
opportunity evaluation. It never rejects a strong unexpected idea merely
because the portfolio did not predict it. At most eight matching strategy
items enter one content brief; the Writer never receives the complete
portfolio or a keyword-frequency requirement.

## İlham Değeri

`İlham Değeri` is an explainable editorial heuristic, not a scientific
measurement. The recorded factors are novelty, usefulness, specificity,
visual potential, shareability, emotional impact, audience fit, Turkish-market
applicability, variation potential and strategic fit. Every factor stores its
basis, and the normal UI shows a simple high/medium/low/unknown band.

Search opportunity is independent. It is only strong/medium/weak when a real,
known search-demand component exists; otherwise it is `Bilinmiyor`. Trend is
also `Bilinmiyor` until a real provider or first-party/community signal exists.

## Recommendation policy and human decisions

- **ÜRET:** high inspiration, usable evidence and a strategy match are present.
- **ARAŞTIRMAYA DEVAM ET:** the current idea/evidence set is weak or, notably,
  search opportunity is strong while inspiration quality is low.
- **ELE:** both the established base eligibility and inspiration are weak.
- **İNSAN İNCELEMESİ:** the signals are mixed and require editorial judgment.

Mechanical discovery, fetch, normalization, extraction, grouping and
evaluation do not create inbox approvals. The two meaningful human gates are:

1. commission or reject a sufficiently explained content opportunity;
2. approve the exact QA/media-pinned publication package.

Nothing bypasses the authenticated Publishing API, and publication approval
remains human-only.

## Real local acceptance

After applying migrations, run against the existing local source:

```powershell
cd apps/backend
uv run python scripts/verify_idea_intelligence.py --source kara
```

The command uses existing PostgreSQL rows, adds only an idempotent example
operator strategy, evaluates existing promoted opportunities, reports honest
unknown search/trend state and asserts that every extracted signal resolves
back to the Kara source.
