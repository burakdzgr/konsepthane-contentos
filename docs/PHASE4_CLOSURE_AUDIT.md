# Phase 4 Closure Audit (Task 21)

Phase 4 — Content Production (Writer → Editor → QA) — is audited here
against its binding scope and invariants, closing the phase. The phase's
goal: a validated content package reaches `AWAITING_HUMAN_REVIEW`
through governed, auditable, human-controlled machinery. `APPROVED`
belongs to the next (governance) phase by design.

Docs-only; no runtime was changed by this audit.

## What Phase 4 shipped

| Stage | Tasks | Stage audit | Verdict |
| --- | --- | --- | --- |
| Writer architecture + implementation | 1–7 | `PHASE4_WRITER_AUDIT.md` (Task 8) | 15/15 criteria MET |
| Named CHANGES_REQUESTED responsible-state routing | 6 | (within the Writer audit) | MET |
| Editor architecture + implementation | 9–14 | `PHASE4_EDITOR_AUDIT.md` (Task 15) | 10/10 criteria MET |
| QA architecture + implementation | 16–19 | `PHASE4_QA_AUDIT.md` (Task 20) | 7/7 criteria MET |

Schema: migrations `0018`–`0020` (drafts, reviews, QA — all append-only
with guarded supersession and, where the shared attempts table was
touched, audit-protecting downgrades). Worker: three new editorial
tasks (`generate_writer_draft`, `generate_editor_review`,
`run_qa_gates`; 9 total). API/admin: full command + read-model +
screen coverage for drafts, reviews, and QA reports with leak tests.
Suite at closure: 1225 backend + 185 admin tests; CI green on every
commit of the phase.

## The end-to-end proof (real infrastructure)

`verify_pg_full_chain.py` ran the COMPLETE story on
`pgvector/pgvector:pg16` + `redis:7-alpine` in one process:

1. Phase 2/3 seeded through the REAL domain services (4 OFFICIAL
   sources → discovery → fetch → normalization → evidence → promotion
   → genuine commissionable score → commissioning → idea → READY pack
   → intent → composed brief → human acceptance);
2. `generate_writer_draft` via the eager worker: durable draft →
   SYSTEM `DRAFTING → EDITING` with the draft pinned → Editor dispatch;
3. `generate_editor_review`: durable PASS review (drift guard
   recomputed) with NO transition; human `accept-review` transition to
   `QA_REVIEW` with the package pinned;
4. `run_qa_gates` via the real broker (message inspected: task name,
   request_id header, no URL leak): truthful `not_ready` (media gate
   `unsatisfied`) staying in QA_REVIEW; audited human waiver; re-run →
   `ready_for_human_review` → SYSTEM `QA_REVIEW →
   AWAITING_HUMAN_REVIEW` with `{qa_report_id, editorial_review_id,
   content_draft_id, content_hash}` pinned; redelivery reused with no
   new events and no downstream dispatch;
5. **ADR 0007 walk from the terminal package**: every claim usage of
   the terminal draft resolved
   `Draft → DraftClaimUsage → BriefClaim → BriefClaimEvidence →
   ResearchEvidence → NormalizedDocument → FetchSnapshot → Source`
   (2 usages → 2 complete chains). ALL steps passed.

## Binding invariants — verdicts

| Invariant | Verdict | Basis |
| --- | --- | --- |
| The provenance chain stays resolvable end-to-end | **HELD** | RESTRICT FKs + append-only triggers at every hop; relational claim usages mirrored from the body; re-proven by the QA provenance gate on every run and by the terminal walk above. |
| AI output is NEVER ResearchEvidence; AI adds no external facts | **HELD** | Drafts/reviews/attempts live in their own tables and never write evidence rows; the Writer may only phrase projected claims (numeric gate, framing rules, unknown-ref rejection); Editor findings are anchored policy signals with external-knowledge findings forbidden and no fact channel in the rework input; QA involves no model at all. |
| Contradictions/uncertainty/UNKNOWN are never hidden or rendered as 0/PASS | **HELD** | Required-handling manifests fail closed at Writer persistence AND drift re-checks (Editor, QA); score components, verdicts, envelopes, and gates all render UNKNOWN as UNKNOWN (tested in every read surface); the media gate blocks rather than pretending. |
| Execution failure is never an editorial decision | **HELD** | Every failure path (timeout, provider error, validation, materialization) leaves the work item in its state with a durable, visible attempt/report; REJECTED is reachable only through explicit human commands; `QaOutcome`/`ReviewVerdict` contain no failure or rejection labels. |
| Workflow advances ONLY via WorkflowService behind artifact gates | **HELD** | Three artifact-gated SYSTEM transitions (draft→EDITING, ready report→AWAITING_HUMAN_REVIEW — the mechanical gates) and human-actor transitions everywhere judgment is involved (accept-review, rework, waivers, acceptance); queue completion never advances state (redelivery guards tested); no generic endpoints (asserted continuously). |
| Rework routes through the named responsible-state foundation | **HELD** | Fixed per-context vocabularies (EDITING→{DRAFTING}; QA_REVIEW→{DRAFTING, EDITING}); durable recorded responsible states; forgery-proof reserved key; return-to-origin fallback; arbitrary targets impossible (tested at both layers). |
| No publication/approval boundary crossed; no Konsepthane production access | **HELD** | No approval surface exists (banned-route tests + admin assertions); no Konsepthane credentials/hosts anywhere; AWAITING_HUMAN_REVIEW is a stated dead-end awaiting governance. |
| Human control (ADR 0004) | **HELD** | Humans hold: brief acceptance, both EDITING exits, QA waivers, all rework, all rejections. Machines hold only mechanical artifact gates. |

## Consolidated production-readiness backlog (NOT feature gaps)

Carried from the three stage audits, deduplicated:

1. **Authentication/RBAC** on `/internal/*` and the admin (the
   governance phase's entry requirement — APPROVED depends on it).
2. **Real-infrastructure CI lane**: the per-task PG/Redis verification
   scripts should become a containerized CI job (incl.
   `verify_pg_full_chain.py` as the end-to-end smoke).
3. **Provider spend controls** (quotas/budgets) beyond bounded retries.
4. **Unpaged capped listings** in draft/review/report read models.
5. **Admin manual-draft JSON textarea** → structured editor (UX only).
6. **Waiver revocation** as a new audited append.
7. **Recorded test-evidence gap**: the superseded-brief review
   precondition (code-enforced, untested — from the Editor audit).
8. **Media pipeline** and **publish-time internal linking** (roadmap
   features that retire the waiver path and the non-blocking link
   gate).

## Disposition — PHASE 4 CLOSED

The editorial factory now runs governed end-to-end from research intake
to a fully pinned, provenance-resolvable content package awaiting a
human decision. Next per the long-term roadmap: the **governance
phase** — authentication, named authorized reviewers, the
AWAITING_HUMAN_REVIEW decision surface (APPROVED / CHANGES_REQUESTED /
REJECTED with ADR 0004 semantics), and approval-validity mechanics —
beginning with its own architecture document.
