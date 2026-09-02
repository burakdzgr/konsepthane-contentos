# Phase 4 Writer-Stage Closure Audit (Task 8)

Audit of the implemented Writer stage (Phase 4 Tasks 2–7) against the
exit criteria of `PHASE4_WRITER_ARCHITECTURE.md` §21. Docs-only; no
runtime was changed by this audit. Evidence cites actual code, tests,
and real-infrastructure verification runs. Every criterion was checked
against the repository at the audited HEAD, not against intentions.

Verification base: 1147 backend tests + 156 admin tests green through
`scripts/check.ps1`; schema head `0018`; real-infrastructure scripts run
against `pgvector/pgvector:pg16` and `redis:7-alpine` containers (Tasks
2 and 5); CI green on every Writer-stage commit.

## §21 exit-criteria matrix

| # | Criterion | Verdict | Evidence |
| --- | --- | --- | --- |
| 1 | Generation requires an exact ACCEPTED_FOR_DRAFTING brief; typed failure otherwise, zero provider spend | **MET** | `DraftService._create_draft` gates on the accepted brief + DRAFTING work item under a row lock; `WriterEngine.generate_draft` re-checks BEFORE building any request. `test_writer_generation.py::test_preconditions_cost_zero_provider_calls` asserts `provider.invocations == 0`; `test_editorial_tasks.py` asserts the unaccepted-brief task run is a durable FAILURE with zero invocations. |
| 2 | Immutable versioned ContentDraft; append-only DB enforcement; status-only-forward supersession | **MET** | Migration `0018_create_content_drafts.py`: PL/pgSQL guard trigger permits exactly two UPDATE shapes (`active→superseded` with pointer NULL; then one-shot NULL→value pointer on the superseded row), forbids DELETE and any content-field change; partial-unique single ACTIVE row per work item; `UNIQUE(work_item_id, version)`. Negative trigger cases (reverse transition, pointer rewrite) verified on real PG (`verify_pg_drafts.py`, all passed). |
| 3 | Claim provenance resolves block → DraftClaimUsage → BriefClaim → ResearchEvidence (ADR 0007) | **MET** | `DraftClaimUsage` rows carry `(draft_id, brief_claim_id, section_key, block_id)` with `UNIQUE(draft_id, brief_claim_id, block_id)`; usages are written only from validated claim refs. Read model `_claim_usage_views` resolves the chain to `research_evidence_ids`; `test_editorial_read_api.py::TestDraftReads` asserts non-empty evidence identities on a draft produced from the REAL Phase 3 chain. PG verification seeds the full genuine chain (4 OFFICIAL sources, commissionable score) — no shortcut rows. |
| 4 | Deterministic Writer envelope fails closed; no draft row from invalid output; semantic faithfulness explicitly delegated | **MET** | `drafts/policies.py` (`writer-validation/1`): known-claim-refs-only, numeric-assertion gate (digits require claim binding; step-enumeration exempt), SOURCE_ASSERTION attribution stems, INFERENCE hedging stems; `require_safe_text` bans URLs/HTML/scripts deterministically. Invalid model output = durable `VALIDATION_FAILED` attempt (`error_class="domain_validation"`) with ZERO draft rows (unit + real-PG failure-truthfulness step). The policy snapshot records `exclusions_mechanically_checked: False` — exclusions and semantic claim-faithfulness are explicitly delegated to Editor/QA; no semantic certainty is claimed. |
| 5 | Required uncertainty/contradiction handling with persisted coverage; disappeared caveats fail | **MET** | `build_required_handling_manifest` derives `note-{i}`/`licensing-{i}`/`staleness-{i}`/`locale-limitations`/`contradiction-{id}`/`claim-{id}` requirements from the brief, pack, contradictions, and claims; `validate_handling_coverage` fails closed on undischarged or unknown refs; the coverage record persists per draft (`uncertainty_coverage`). Removing the coverage callout fails generation AND operator submission (422, zero rows) — tested in both paths. |
| 6 | Originality/copyright guard: no source bodies in projection; verbatim + structure gates as versioned policy | **MET** | Projection carries bounded evidence STATEMENTS (≤500 chars) with ResearchEvidence identities — never `clean_text`, raw payloads, or URLs (`test_projection_is_bounded_and_leak_free` scans the captured request). `writer-originality/1`: normalized longest-common-substring cap (80 chars) vs projected statements; source-structure basis is the brief structure guard, carried honestly as such (not re-proven). Breach raises with an explicit research-not-translation message. |
| 7 | Provider-neutral AI boundary reused; WRITER_DRAFT attempts carry full identity; no raw prompt/output persisted | **MET** | `WriterEngine` goes through the existing `StructuredGenerationService.execute` only; purpose `WRITER_DRAFT` added to the frozen vocabulary with the `ck_ai_generation_attempts_purpose` CHECK widened in 0018 (downgrade REFUSES while writer_draft audit rows exist). Attempt `input_refs` pin brief/work-item/idea/pack/intent ids + claim/handling id sets + engine and policy identities; instructions are the versioned template and are never persisted or hashed. |
| 8 | Deterministic fake-provider tests; gates never call a live provider | **MET** | All writer tests use `FakeStructuredProvider`/`CapturingFake`; the canonical gate (`check.ps1`) and CI run with no provider keys and no network AI calls. The ADR 0009 OpenAI adapter is exercised separately by its own contract tests, unchanged by Phase 4. |
| 9 | Idempotent generation + explicit regeneration; redelivery-safe; audited supersession; rework only after the routing foundation | **MET** | One draft per SUCCEEDED attempt (`UNIQUE(generation_attempt_id)`); same identity reuses durable attempt+draft with zero provider calls; regeneration is explicit `retry_number+1` with a REQUIRED supersede reason over an active draft, producing an audited `DraftStatusEvent` with the replacement pinned. Celery redelivery-in-EDITING validates the pinned `content_draft_id` via the entry event and reuses (real-Redis verified: reused, single draft, no new events, zero dispatches). Rework (`request-rework`/`resolve-changes-requested`) shipped in Task 7 strictly AFTER the Task 6 named responsible-state routing foundation. |
| 10 | SUCCEEDED-attempt/failed-materialization: typed error + retry_number+1 recovery | **MET** | Deterministic persistence rejection of valid output raises `DraftGenerationMaterializationError` with the attempt keeping its REAL status (committed before the terminal failure in the Celery task); a SUCCEEDED attempt without a draft raises `IncompleteDraftMaterializationError`, recovered ONLY by explicit `retry_number+1` (`test_incomplete_materialization_recovers_with_next_retry`). |
| 11 | DRAFTING → EDITING only via WorkflowService after a durable draft commit; SYSTEM actor; draft pinned; queue completion never state | **MET** | `generate_writer_draft` TX A commits the durable draft, TX B performs the explicit SYSTEM `WorkflowService.transition` with `{content_brief_id, content_draft_id, draft_version, content_hash}` in `artifact_refs`, then commits — no downstream dispatch (Editor does not exist). Verified end-to-end on real PG + real Redis including raw broker-message inspection (task name + request_id header, no URL/prompt leak). |
| 12 | Operator drafts: identical validation path, no fake AI attempt, durable manual_input_hash idempotency | **MET** | `create_operator_draft` funnels into the SAME `_create_draft` gates with `generation_attempt=None`; DB CHECKs enforce `(origin='operator') = (generation_attempt_id IS NULL)` and `= (manual_input_hash IS NOT NULL)`; partial-unique `(work_item_id, manual_input_hash) WHERE origin='operator'` with race convergence via IntegrityError re-read. Identical resubmission reuses; changed content is a new version requiring a supersede reason. The Task 7 submit-draft command then applies the same artifact gate (OPERATOR DRAFTING → EDITING with the draft pinned). |
| 13 | Operator can inspect drafts, provenance, coverage, attempts, failures; no raw provider data/secrets/source bodies | **MET** | `/internal/editorial/work-items/{id}/drafts` + `/internal/editorial/drafts/{id}` read models and the admin drafts section + draft detail page (`/editorial/[id]/drafts/[draftId]`). Failed attempts stay visible with `error_class`; missing verdicts render as UNKNOWN, never 0/PASS. Leak tests on both sides (backend FORBIDDEN_STRINGS scan incl. `clean_text`, `redis://`, seeded raw-HTML marker; admin internal-URL assertions). |
| 14 | No publication/approval/scheduling boundary crossed; no Konsepthane production access; failures truthful, never editorial rejection | **MET** | `TestNoGenericEndpoints` bans generic action/state/publish/approve/schedule routes; no Konsepthane credentials, hosts, or clients exist anywhere in the runtime. Execution failures (timeout, provider error, validation) leave the work item in DRAFTING — verified in unit retry-chain tests and the real-PG failure-truthfulness step; REJECTED remains an exclusively human editorial decision. |
| 15 | Real-PG (and broker) verification of the full DRAFTING story, then this audit | **MET** | `verify_pg_drafts.py` (Task 2: migration cycle 0017→0018→0017→0018 with downgrade audit guard, service operations, race, trigger negatives) and `verify_pg_writer_task.py` (Task 5: failure truthfulness, real Redis broker delivery with message inspection, durable draft → SYSTEM EDITING with pins, redelivery idempotency) — both fully passed against real containers. This document is the Task 8 audit. |

**Result: 15/15 criteria MET. The Writer stage is COMPLETE per §21.**

## Honest limitations

Classified per the mandate's separation of feature completion from
production readiness. None of these contradicts a §21 criterion; the
criteria themselves scope several of them out.

### Deferred by design (later Phase 4 / later phases — feature work)

- **Semantic claim-faithfulness is not checked by the Writer stage.**
  Deliberate (§21 criterion 4): the deterministic envelope proves
  structure, claim binding, framing, handling, and originality bounds —
  whether prose faithfully represents the bound evidence is Editor/QA
  territory (Tasks 9+). Any future model-assisted check is a policy
  signal, never Evidence.
- **The rework loop has no consumer yet.** EDITING →
  CHANGES_REQUESTED(responsible=DRAFTING) → DRAFTING works under
  WorkflowService with full audit, but nothing produces editorial
  review verdicts until the Editor exists; today it is an
  operator-driven command.
- **`generate_writer_draft` dispatches nothing downstream** — correct
  until the Editor stage exists; the Editor task will hook the EDITING
  entry when implemented.
- **Brief exclusions are surfaced, not mechanically enforced**
  (`exclusions_mechanically_checked: False` in the persisted policy
  snapshot) — recorded truthfully; enforcement is Editor/QA scope.

### Production-readiness backlog (separate from feature completion)

- **Single-operator boundary**: no authentication/RBAC on
  `/internal/*` or the admin; deployment infrastructure remains the
  access boundary (per the accepted Phase 4 scope decision, governance
  comes after AWAITING_HUMAN_REVIEW exists end-to-end).
- **Real-PG/Redis verification is a scripted per-task ritual**, not a
  CI job; CI proves the suite on SQLite plus migration-content checks.
  A containerized CI verification lane is backlog.
- **Operator draft submission in the admin takes the sections payload
  as JSON** (validated shape-first server-side, full domain gates
  behind it). A structured block editor is UX backlog; the domain
  boundary is unaffected.
- **No provider spend controls** (rate limits/quotas/cost budgets)
  beyond bounded retries and explicit operator commands.
- **Draft read models cap listings** (50 versions, 20 attempts) with a
  truncation flag but no paging; acceptable at single-operator scale.

## Disposition

The Writer stage is closed. Next per the accepted order (§22) and the
autonomous mandate: **Task 9 — Editor architecture (design only)**,
then Editor implementation, QA architecture + implementation, and the
Phase 4 closure audit ending at AWAITING_HUMAN_REVIEW.
