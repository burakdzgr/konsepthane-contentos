# Konsepthane Idea Intelligence Engine

Status: implemented baseline, 2026-09-03; Opportunity Intelligence
(engine `inspiration-quality` v5, pre-decision enrichment) 2026-09-05.

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

Search opportunity is independent. It is strong/medium/weak only when a real,
known search-demand component exists on the base score OR an independent
Semrush observation exists for the opportunity's keyword set; otherwise it is
`Bilinmiyor`. Trend is `Bilinmiyor` until Google Trends or Pinterest Trends
reports; community interest never counts as trend or demand.

## Opportunity Intelligence (engine `inspiration-quality` v5)

Before the human decision, `contentos.inspiration.enrichment.enrich_opportunity`
gathers EVERY signal family and EVERY configured provider for one opportunity
into the evaluation's `input_snapshot["intelligence"]` block (no migration:
JSON). Nothing in it is an opaque score; the operator reads four explainable
Turkish sections on the `/firsatlar` card and the work-item detail:

| Section | Fields | Source |
| --- | --- | --- |
| **İçerik Değeri** | İlham Değeri, Kitle Uyumu, Stratejik Uyum, Türkiye Pazar Sinyali, Topluluk İhtiyacı | inspiration factors; `market` / `community_need` family bands (`intelligence_signals`) |
| **Arama İstihbaratı** | Semrush Arama Potansiyeli, Arama Hacmi, Anahtar Kelime Zorluğu, Google Trends (yükseliyor/stabil/düşüyor/bilinmiyor), Pinterest Trend, Rekabet — each with provider freshness ("2 gün önce", "Yapılandırılmadı", "API erişimi gerekli", "Kota sınırında", "Kısıtlı", "Kayıtlı gözlem") | Semrush `keyword_overview` (≤ 8 phrases, one batched call), Google Trends `summary`, Pinterest `keyword_trend` (one call each on the primary phrase); `competition` family band |
| **Konsepthane Verisi** | Benzer içerik performansı, Kanibalizasyon, Geçmiş başarı | `historical_signal_for` (performance loop, priority-only), latest `SearchIntentAnalysis.cannibalization_status` |
| **Araştırma** | Bağımsız kaynak N, Sinyal türü N, Kanıt Yeterli/Eksik/Bilinmiyor | research-input + signal sources + providers with a known observation; distinct known families |

Rules the block obeys:

- **UNKNOWN is a value.** A provider that is not configured, refused access,
  hit its quota, timed out or errored yields UNKNOWN plus its state (persisted
  on the provider's durable status through the registry). Nothing is filled
  with 0; a metric the vendor omitted stays `null`.
- **Never conflate community interest with search demand.** A need voiced in
  a forum is a `community_need` band; search demand comes ONLY from the base
  score's `search_demand` component or an independent Semrush observation.
- **Never conflate historical performance with a filter.** A positive history
  is a PRIORITY signal: it can lift a HUMAN_REVIEW to ÜRET only when
  inspiration is HIGH, evidence exists, the base is commissionable and search
  is not known-weak — never on its own, never over the commissioning gate.
- **Bounded and provider-free where it must be.** Only the worker task
  `evaluate_opportunity` composes the provider registry; the API process
  evaluates provider-free and reads the durable `search_signals` history
  (`state = stored`). Provider timestamps are not part of the evaluation
  identity, so a re-run over the same facts is the SAME evaluation.
- Keyword set: at most 8 natural-Turkish phrases (strategy keywords first,
  then the topic, then inspiration concepts; sentence-length titles skipped),
  deduplicated on the normalized key. Diacritics are kept for the vendor.
- Thresholds (constants in `enrichment.py`): Semrush STRONG ≥ 1.000 volume
  with KD ≤ 50, MODERATE ≥ 200 with KD ≤ 70, any other known volume WEAK;
  Pinterest STRONG ≥ 20 % growth, MODERATE ≥ 5 %, else WEAK.

## Recommendation policy and human decisions

- **ÜRET:** high inspiration, usable evidence and a strategy match (or a
  positive Konsepthane history, see above) are present AND the effective base
  score is `commissionable` — the same rule the commissioning command enforces
  (`commissioning_admits`), so ÜRET is never shown next to a decision the
  backend would refuse — AND search intelligence is not known-weak. A
  high-inspiration opportunity whose base score is not commissionable, or whose
  measured search potential is weak, routes to İNSAN İNCELEMESİ with a
  rationale naming the block.
- **ARAŞTIRMAYA DEVAM ET:** the current idea/evidence set is weak or, notably,
  search opportunity is strong while inspiration quality is low — including
  when every idea signal is cliché even though community need is high.
- **ELE:** both the established base eligibility and inspiration are weak.
- **İNSAN İNCELEMESİ:** the signals are mixed and require editorial judgment.

The persisted rationale ("Neden?") is Turkish and names the concrete bases:
`Semrush: hacim 1.900, zorluk 32 (tr, bugün)`, `Google Trends: erişim gerekli`,
`Topluluk ihtiyacı: orta (3 kaynak, 7 gözlem)`, `Geçmiş başarı: bilinmiyor`,
`Kanıt: 3 kayıt, 5 bağımsız kaynak, 4 sinyal türü; strateji: 1 konu eşleşti`.

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
