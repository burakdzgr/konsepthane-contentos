# Phase 6 Media Audit (Task M6)

Phase 6 — Media — is audited here against the exit criteria of
`PHASE6_MEDIA_ARCHITECTURE.md` §6, closing the phase. The phase's goal:
the QA `media_needs` gate gains its fourth honest answer — `satisfied`
— backed by durable, provenance-carrying, human-bound assets.

Docs-only; no runtime was changed by this audit.

## What Phase 6 shipped

| Task | Content | Verified by |
| --- | --- | --- |
| M1 | Media foundation: migration `0023` (media_assets immutable + content-addressed, media_need_satisfactions with guarded supersession + partial-unique ACTIVE, append-only human-only events), `MediaStore`, `MediaService` | 7 unit tests + `verify_pg_media.py` on real PG 16 |
| M2 | Commands + read models: multipart upload, satisfy/unsatisfy, coverage read model, authenticated byte streaming; python-multipart | 5 API tests incl. leak assertions |
| M3 | QA gate v2 (`qa-gates/2`): `satisfied` + exact `unmet_indexes` everywhere; old reports stay under their recorded version | 5 gate tests incl. the v1-survival proof |
| M4 | AI image generation: migration `0024` (media_image purpose + downgrade guard), `media-image/1` envelope over the FULL ai boundary, `MediaImageEngine`, the 10th editorial task + queue command, OpenAI Images adapter | 9 tests + `verify_pg_media_image.py` on real PG 16 |
| M5 | Admin media surface: coverage section, byte proxy, state-gated upload-and-bind / bind / generate / unbind | 11 admin tests |

Schema head: `0024`. Suite at closure: 1279 backend + 227 admin tests;
CI green on every commit of the phase.

## §6 exit criteria — verdicts

1. **Assets durable, content-addressed, immutable,
   provenance-carrying, with required alt text and licensing posture;
   bytes only in the ContentOS-owned store.** **MET.** `media_assets`:
   UNIQUE lowercase sha256 (identical bytes converge by construction),
   immutable by trigger (PG-verified negative), CHECK-required
   non-blank `alt_text` and `license_note`, origin CHECK binding
   `ai_generated` to a UNIQUE `generation_attempt_id` and
   `human_upload` to a named `created_by_user_id`. Bytes live under
   `media_store_root` (atomic writes, integrity-checked reads, key
   hygiene tested); no Konsepthane path exists anywhere in the code
   or configuration.

2. **Needs satisfied ONLY by explicit audited human commands; AI
   generation alone satisfies nothing.** **MET.** The single write
   path is `MediaService.satisfy_need/unsatisfy_need` — named ACTIVE
   user, required reason, append-only `media_satisfaction_events`
   (actor NOT NULL — no SYSTEM vocabulary exists in the tables),
   two-shape guarded supersession with the one-shot pointer and the
   partial-unique ACTIVE row (both PG-verified). `MediaImageEngine`
   and the upload route create ASSETS only; tests assert zero
   satisfactions and an untouched workflow after generation.

3. **The media gate reports satisfied / unsatisfied with exact unmet
   indexes / waived_by_human / not_applicable truthfully under a
   bumped policy version.** **MET.** `_media_needs` v2 derives
   coverage from ACTIVE satisfactions of the ACTIVE brief; every
   non-satisfied shape carries `unmet_indexes` (the waiver hides
   nothing); `satisfied` joined the passing set so full coverage
   reaches READY without a waiver. Reports persist the snapshot at run
   time — a pre-M3 `qa-gates/1` report superseded by a v2 run keeps
   its own version and results (tested).

4. **The AI boundary holds for images.** **MET.** The image path IS
   the structured-generation path: purpose-tagged attempts with safe
   metadata only, identity hashing + idempotent reuse (one invocation
   proven), prompts and raw payloads never persisted, provider keys
   only in server settings. The `media-image/1` domain validator
   decodes the bytes and proves they match the declared type and the
   store bound — a provider's word is never trusted. Failures are
   durable attempt facts; the task's precondition path is a truthful
   no-op, never a workflow effect. Migration `0024`'s downgrade guard
   refuses to invalidate media_image audit history (PG-verified).

5. **Satisfaction commands are state-bounded; QA re-runs stay
   explicit.** **MET.** `PERMITTED_MEDIA_STATES` = {DRAFTING, EDITING,
   QA_REVIEW, CHANGES_REQUESTED}; a package under terminal review is
   frozen (service, route, engine, task and admin all tested for the
   409/truthful-note path). No satisfy/unsatisfy/generate path calls
   the QA engine; the admin notices say so explicitly.

6. **Read models/admin expose coverage with leak tests; bytes served
   only through the authenticated route.** **MET.** The coverage page
   carries per-need satisfaction (honest null), actor display names,
   asset metadata and history; tests assert no store paths, no
   credential material, no backend URL. Bytes flow backend-store →
   operator-authenticated backend route → the admin's OWN
   session-gated proxy route → the browser; the store layout is
   internal at every hop.

7. **Migrations verified on real PostgreSQL; deterministic tests
   throughout.** **MET.** `verify_pg_media.py`: 0023 cycle over a
   populated chain, full service lifecycle, all trigger negatives, the
   ACTIVE-uniqueness negative. `verify_pg_media_image.py`: 0024 cycle
   with the CHECK inspected on PG, a real engine run with a provenance
   asset and idempotent reuse, and the downgrade guard refusing over
   real audit history. 32 deterministic media tests run in every suite.

8. **A media closure audit against these criteria.** **MET** — this
   document.

## Binding invariants — spot re-verification

- **ADR 0004 (human control)**: extended, not diluted — binding an
  asset to a need is a named human act; the machine produces
  candidates only.
- **ADR 0007 (provenance)**: untouched — media adds a parallel
  provenance chain (asset → attempt → refs) without altering the
  claim/evidence chain; the QA provenance gate is unchanged.
- **Failure ≠ editorial decision**: generation failures are attempt
  rows; no media path can BLOCK, REJECT, or transition anything.
- **No Konsepthane access / no publication**: the phase added no
  publish/schedule surface (`test_no_publication_command` still pins
  the route space) and no external filesystem or host.

## Production-readiness backlog additions (NOT feature gaps)

1. **Production object store** behind the `MediaStore` interface (the
   local volume is v1 by design); store garbage collection for assets
   never bound (no deletion path exists — deliberate, revisit with
   retention rules).
2. **Image dimension extraction** (width/height stay honestly NULL in
   v1).
3. **Upload streaming**: uploads are bounded (10 MiB) but buffered in
   memory; fine for the internal tool, revisit before any exposure.
4. Carried forward unchanged: real-infra CI lane, session hygiene,
   spend controls, capped listings, secrets management.

## Verdict

Phase 6 — Media — is **CLOSED**: 8/8 exit criteria MET, both
migrations verified on real PostgreSQL, and the QA media gate can now
say `satisfied` and mean it. Next per the roadmap: the **Publishing
phase** (architecture first), which must consume
`DecisionService.require_current_approval` and the versioned +
authenticated + idempotent Publishing API contract (the open
integration questions in `docs/memory/CURRENT_STATE.md`).
