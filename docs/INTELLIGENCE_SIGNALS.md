# Intelligence Signals

Status: implemented, 2026-09-05 (migration `0032`, table `intelligence_signals`).

ContentOS turns external material into original Konsepthane opportunities
through one chain:

```
SOURCE -> ROLE-SPECIFIC SIGNAL EXTRACTION -> SIGNALS -> IDEA INTELLIGENCE
       -> DEDUP / CLUSTERING -> OPPORTUNITY
```

This document explains the middle of that chain: what a signal is, which
families exist, where each family is stored, and the privacy rule that
governs community-derived signals.

## SOURCE vs SIGNAL vs IDEA vs OPPORTUNITY

| Concept | What it is | What it is not |
| --- | --- | --- |
| Source | A governed origin with a technical `kind` (how we fetch), an editorial `primary_role` (why we read it) and `capabilities` (which signal families it MAY yield) | Permission to copy or a fact provider by itself |
| Signal | One bounded, provenance-linked clue about a concept: "this forum asks how to decorate a 1st birthday", "this shop lists a Safari theme", "this competitor covers this title" | Evidence, an article, a demand figure, or a verdict |
| Idea | A concrete original direction selected after commissioning, shaped by signals and strategy | A spun source title or a signal with a nicer name |
| Opportunity | A research-backed proposal for Konsepthane, scored with honest UNKNOWNs, gated by a human | Automatic permission to write |

Signals never become `ResearchEvidence`. Evidence is a traceable factual
claim unit extracted from documents whose source is allowed to provide
facts; signals are clues used to *rank, group and explain* opportunities.

## Where signals live

There are three durable signal stores, each with its own identity rule:

| Family | Store | Identity / idempotency |
| --- | --- | --- |
| `inspiration` | `inspiration_signals` (`contentos.inspiration`) | per opportunity + document + extractor + signal key |
| `search`, `trend` (provider observations) | `search_signals` (`contentos.signals`) | `observation_hash` of the provider observation |
| `community_need`, `market`, `competition`, `taxonomy`, plus reserved `search`, `trend`, `visual_trend`, `historical_performance` mirrors | `intelligence_signals` (`contentos.intelligence`) | `observation_hash` = sha256 of `family|concept_key|provider|source_id|normalized_document_id` |

`intelligence_signals` is deliberately ONE bounded table rather than one
table per family: every row has a `family`, a human-readable `subject`
(max 300 chars), a `concept_key` (`normalize_phrase`, max 240 chars) for
dedup/clustering, locale/market, optional links to `sources`,
`normalized_documents` and `editorial_opportunities`, the extractor
identity in `provider` (e.g. `community-need-extractor/1`), a bounded JSON
`value` (max 40 keys, no string over 300 chars), and `occurrence_count` +
`first_observed_at` / `last_observed_at`. Re-extracting the same document
updates the count and timestamp instead of duplicating the row.

## The nine families

| Family | Meaning | Produced by |
| --- | --- | --- |
| `inspiration` | An idea/concept clue worth original treatment | `contentos.inspiration` (engine `inspiration-quality`) |
| `community_need` | A question or need people voice in a forum/community, as a PII-free pattern with a category guess | `community-need-extractor/1` on sources with the `community_need` capability |
| `market` | Which Konsepthane strategy clusters/keywords a Turkish editorial document touches | `market-context-extractor/1` (uses `StrategyService.context_for_text`) |
| `competition` | A competing piece exists for a concept: title pattern, host, publish date | `competition-extractor/1` |
| `taxonomy` | A theme/product/category term seen in a shop or taxonomy source | `taxonomy-extractor/1` |
| `search` | Independent search-demand observation | provider adapters (`search_signals`); UNKNOWN until a provider reports |
| `trend` | Independent trend observation | provider adapters; UNKNOWN until a provider reports |
| `visual_trend` | Visual/style trend observation | reserved for a visual-trend provider |
| `historical_performance` | How Konsepthane's own published content performed | reserved for the performance feedback loop |

Extraction is deterministic keyword/cue matching, versioned in `provider`.
No AI is involved; a document that matches nothing yields nothing. The
extractors run in the WORKER right after a `NormalizedDocument` is
committed (`contentos.research.normalize_fetch`), are selected by the
source's capabilities, and are fail-safe: an extractor error is logged and
never fails normalization or the downstream pipeline.

## Community privacy rule

Community sources (forums, Q&A, social threads) are read for NEEDS, never
for people. The rule, enforced in `contentos.intelligence.privacy` and the
community extractor:

Stored:

- one PII-scrubbed sentence-level need pattern (max 300 chars), e.g.
  `Kızım [ad] için tema önerir misiniz?`
- a category guess (`doğum günü`, `düğün`, `nişan`, `baby shower`,
  `evlilik teklifi`, `diğer`)
- the cues that qualified the sentence (`?`, `nasıl`, `nereden`, `önerir
  misiniz`, `tavsiye`, `fikir`, `ne yapabilirim`, ...)
- the concept key, provenance ids and counts

Never stored:

- the paragraph or post body, usernames, display names, e-mail addresses,
  phone numbers, `@handles`, URLs carrying query strings
- personal names following Turkish cues (`adım`, `ismim`, `benim adım`,
  `kızım`, `oğlum`, `eşim`, `kızımın adı`, ...) — the name token becomes
  `[ad]`
- any `ResearchEvidence`: community sources are never allowed to produce
  factual evidence, regardless of trust tier

`is_pii_free(text)` is the check; `scrub_pii(text)` is the transformation;
`bounded_pattern(text)` scrubs and cuts. Tests cover Turkish phone
formats (`05xx ...`, `+90 (5xx) ...`), e-posta, handles, query URLs and the
name cues.

## Community interest is not search demand

A need voiced ten times in a forum is a strong `community_need` signal. It
says people *ask*; it does not say people *search*, how often, or with
which words. Search demand stays UNKNOWN until an independent provider
observation exists in `search_signals`. Opportunity intelligence therefore
reads families separately:

- `signal_bands_for_opportunity(session, opportunity_id)` returns one
  `Band` (`strong | moderate | weak | unknown`) per family, computed only
  from durable rows linked to the opportunity (its research documents,
  rows pinned to it, or concept-key matches with its topic summary).
  Thresholds (constants in `contentos.intelligence.service`): STRONG needs
  at least 6 occurrences from at least 2 distinct sources; MODERATE needs
  3 occurrences or 2 sources; anything observed is at least WEAK; no row
  is UNKNOWN.
- A family with no rows is UNKNOWN, never 0. Nothing in one family is
  ever used to fill in another.

## Read API

- `GET /internal/intelligence/signals?family=&opportunity_id=&limit=` —
  bounded list (default 50, max 200); with `opportunity_id` it returns the
  same join `signal_bands_for_opportunity` uses; unknown opportunity → 404.
- `GET /internal/intelligence/summary` — per family: row count, occurrence
  total, distinct sources, last observed timestamp (null when none).

Both are operator-guarded, read-only, and never expose raw text.
