"""ReviewService: the single validated persistence path for editor reviews.

Deterministic gates only (PHASE4_EDITOR_ARCHITECTURE.md §3 as implemented
in Task 10): the work item must be in EDITING with the reviewed draft
pinned by the validated EDITING entry event; the reviewed draft must be
the ACTIVE draft and must match that pin; its brief must still be the
exact ACCEPTED writing contract; every finding anchor must resolve to
identities of THAT draft (block ids from the body, claim ids from its
relational usages). The verdict is COMPUTED by the versioned deterministic
policy from validated findings — never supplied by a caller and never
model-authored.

The persisted `integrity_gate_result` records exactly what was checked,
including the Task 11 Writer-envelope drift recomputation
(`writer_envelope_recomputed: True` with per-check outcomes); detected
drift becomes BLOCKING deterministic findings rather than silent failure.
The service flushes; the caller owns COMMIT.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from contentos.ai.enums import GenerationPurpose, GenerationStatus
from contentos.ai.hashing import sha256_hex
from contentos.ai.models import AiGenerationAttempt
from contentos.briefs.enums import BriefStatus
from contentos.briefs.repository import BriefRepository
from contentos.core.context import is_valid_request_id
from contentos.drafts.models import ContentDraft
from contentos.drafts.repository import DraftRepository
from contentos.evidence_packs.repository import EvidencePackRepository
from contentos.reviews.enums import (
    FindingSeverity,
    ReviewActorOrigin,
    ReviewStatus,
    ReviewVerdict,
)
from contentos.reviews.errors import (
    InvalidReviewAttemptError,
    ReviewConflictError,
    ReviewInputError,
    ReviewPreconditionError,
)
from contentos.reviews.integrity import DRIFT_FINDING_PREFIX, recompute_writer_envelope
from contentos.reviews.models import (
    EditorialReview,
    EditorialReviewFinding,
    EditorialReviewStatusEvent,
)
from contentos.reviews.policies import DEFAULT_EDITOR_VERDICT_POLICY, EditorVerdictPolicy
from contentos.reviews.repository import ReviewRepository
from contentos.reviews.values import (
    EDITOR_ENGINE_NAME,
    EDITOR_ENGINE_VERSION,
    INTEGRITY_GATE_VERSION,
    MAX_FINDINGS_PER_REVIEW,
    ReviewFindingInput,
)
from contentos.workflow.enums import WorkflowState
from contentos.workflow.repository import WorkflowRepository

MAX_REASON_LENGTH = 1000


@dataclass(frozen=True, slots=True)
class ReviewCreation:
    """`created` is False when an idempotent identity was reused."""

    review: EditorialReview
    created: bool
    superseded_review_id: uuid.UUID | None


class ReviewService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repository = ReviewRepository(session)
        self._drafts = DraftRepository(session)
        self._briefs = BriefRepository(session)
        self._packs = EvidencePackRepository(session)
        self._workflow = WorkflowRepository(session)

    def create_review(
        self,
        work_item_id: uuid.UUID,
        findings: Sequence[ReviewFindingInput],
        *,
        generation_attempt: AiGenerationAttempt | None = None,
        supersede_reason: str | None = None,
        request_id: str | None = None,
        verdict_policy: EditorVerdictPolicy = DEFAULT_EDITOR_VERDICT_POLICY,
    ) -> ReviewCreation:
        validated_request_id = _validate_request_id(request_id)

        # Deterministic gates under the work-item row lock.
        work_item = self._workflow.get_by_id_for_update(work_item_id)
        if work_item is None:
            raise ReviewPreconditionError(f"no editorial work item with id {work_item_id}")
        if work_item.current_state is not WorkflowState.EDITING:
            raise ReviewPreconditionError(
                f"review creation requires EDITING (current: {work_item.current_state.value})"
            )
        draft = self._require_pinned_active_draft(work_item_id)
        brief = self._briefs.get_brief(draft.content_brief_id)
        if brief is None or brief.status is not BriefStatus.ACCEPTED_FOR_DRAFTING:
            status = brief.status.value if brief is not None else "missing"
            raise ReviewPreconditionError(
                "the reviewed draft's brief is no longer the accepted writing "
                f"contract (brief status: {status})"
            )
        if generation_attempt is not None:
            self._validate_attempt(generation_attempt, draft)
            existing = self._repository.get_by_generation_attempt(generation_attempt.id)
            if existing is not None:
                return ReviewCreation(review=existing, created=False, superseded_review_id=None)

        # The drift prefix is service-reserved: caller findings can never
        # impersonate deterministic gate results.
        for candidate in findings:
            key = candidate.finding_key.strip() if isinstance(candidate.finding_key, str) else ""
            if key.startswith(DRIFT_FINDING_PREFIX):
                raise ReviewInputError(
                    f"finding keys with the {DRIFT_FINDING_PREFIX!r} prefix are "
                    "reserved for deterministic gate results"
                )

        # Task 11 drift guard: recompute the Writer envelope from durable
        # rows; drift becomes BLOCKING deterministic findings.
        claims = self._briefs.list_claims(brief.id)
        pack = self._packs.get_pack(brief.evidence_pack_id)
        assert pack is not None  # RESTRICT FKs make this unreachable
        envelope_checks, drift_findings = recompute_writer_envelope(
            brief=brief,
            claims=claims,
            pack=pack,
            contradictions=self._packs.list_contradictions(brief.evidence_pack_id),
            draft=draft,
            usages=self._drafts.list_claim_usages(draft.id),
        )

        cleaned_findings = self._validate_findings(draft, list(drift_findings) + list(findings))
        severities = [FindingSeverity(entry["severity"]) for entry in cleaned_findings]
        verdict: ReviewVerdict = verdict_policy.compute(severities)

        integrity_gate_result = {
            "version": INTEGRITY_GATE_VERSION,
            "checks": {
                "work_item_in_editing": True,
                "entry_pin_resolves_to_active_draft": True,
                "brief_is_accepted_contract": True,
                "finding_anchors_resolve": True,
            },
            "writer_envelope_recomputed": True,
            "writer_envelope": envelope_checks,
        }
        review_scope = {
            "content_draft_id": str(draft.id),
            "draft_version": draft.version,
            "draft_content_hash": draft.content_hash,
            "content_brief_id": str(brief.id),
            "brief_content_hash": brief.content_hash,
            "finding_count": len(cleaned_findings),
        }
        verdict_policy_snapshot = verdict_policy.snapshot()
        content_hash = sha256_hex(
            {
                "work_item_id": str(work_item_id),
                "verdict": verdict.value,
                "findings": cleaned_findings,
                "integrity_gate_result": integrity_gate_result,
                "review_scope": review_scope,
                "verdict_policy": verdict_policy_snapshot,
                "engine": [EDITOR_ENGINE_NAME, EDITOR_ENGINE_VERSION],
            }
        )

        active = self._repository.get_active_review(work_item_id)
        cleaned_supersede_reason: str | None = None
        if active is not None:
            if active.content_hash == content_hash:
                # Identical re-review of the same draft: idempotent reuse.
                return ReviewCreation(review=active, created=False, superseded_review_id=None)
            if supersede_reason is None or not supersede_reason.strip():
                raise ReviewInputError("superseding the active review requires an explicit reason")
            cleaned_supersede_reason = _required_reason(supersede_reason)

        try:
            with self._session.begin_nested():
                if active is not None:
                    active.status = ReviewStatus.SUPERSEDED
                    self._session.flush()
                review = self._repository.insert_review(
                    EditorialReview(
                        work_item_id=work_item_id,
                        content_draft_id=draft.id,
                        content_brief_id=brief.id,
                        version=self._repository.next_version(work_item_id),
                        verdict=verdict,
                        generation_attempt_id=(
                            generation_attempt.id if generation_attempt is not None else None
                        ),
                        engine_name=EDITOR_ENGINE_NAME,
                        engine_version=EDITOR_ENGINE_VERSION,
                        integrity_gate_result=integrity_gate_result,
                        verdict_policy_snapshot=verdict_policy_snapshot,
                        review_scope=review_scope,
                        status=ReviewStatus.ACTIVE,
                        content_hash=content_hash,
                    )
                )
                for entry in cleaned_findings:
                    self._repository.insert_finding(
                        EditorialReviewFinding(
                            review_id=review.id,
                            finding_key=entry["finding_key"],
                            dimension=entry["dimension"],
                            severity=entry["severity"],
                            origin=entry["origin"],
                            block_id=entry["block_id"],
                            brief_claim_id=(
                                uuid.UUID(entry["brief_claim_id"])
                                if entry["brief_claim_id"] is not None
                                else None
                            ),
                            description=entry["description"],
                            recommendation=entry["recommendation"],
                        )
                    )
                if active is not None:
                    assert cleaned_supersede_reason is not None
                    active.superseded_by_review_id = review.id
                    self._repository.append_status_event(
                        EditorialReviewStatusEvent(
                            review_id=active.id,
                            from_status=ReviewStatus.ACTIVE,
                            to_status=ReviewStatus.SUPERSEDED,
                            actor_origin=ReviewActorOrigin.OPERATOR,
                            reason=cleaned_supersede_reason,
                            request_id=validated_request_id,
                            replacement_review_id=review.id,
                            occurred_at=datetime.now(UTC),
                        )
                    )
        except IntegrityError:
            # A concurrent identical creation won the race: converge on it.
            winner: EditorialReview | None = None
            if generation_attempt is not None:
                winner = self._repository.get_by_generation_attempt(generation_attempt.id)
            if winner is None:
                winner = self._repository.get_active_review(work_item_id)
            if winner is not None and winner.content_hash == content_hash:
                return ReviewCreation(review=winner, created=False, superseded_review_id=None)
            raise ReviewConflictError(
                "review persistence conflicted with concurrently written state"
            ) from None

        return ReviewCreation(
            review=review,
            created=True,
            superseded_review_id=active.id if active is not None else None,
        )

    # --- gates --------------------------------------------------------------

    def _require_pinned_active_draft(self, work_item_id: uuid.UUID) -> ContentDraft:
        entry = self._workflow.get_latest_entry_event(work_item_id, WorkflowState.EDITING)
        pinned_raw = (entry.artifact_refs or {}).get("content_draft_id") if entry else None
        if not isinstance(pinned_raw, str):
            raise ReviewPreconditionError(
                "the durable EDITING entry event does not pin a content draft"
            )
        try:
            pinned_id = uuid.UUID(pinned_raw)
        except ValueError:
            raise ReviewPreconditionError(
                "the durable EDITING entry event pins an unparseable draft id"
            ) from None
        active = self._drafts.get_active_draft(work_item_id)
        if active is None:
            raise ReviewPreconditionError("the work item has no ACTIVE content draft to review")
        if active.id != pinned_id:
            raise ReviewConflictError(
                "the ACTIVE draft does not match the draft pinned by the "
                "EDITING entry event; refusing to review ambiguous state"
            )
        return active

    def _validate_attempt(self, attempt: AiGenerationAttempt, draft: ContentDraft) -> None:
        if attempt.purpose is not GenerationPurpose.EDITOR_REVIEW:
            raise InvalidReviewAttemptError(
                f"attempt purpose {attempt.purpose.value!r} cannot back an editor review"
            )
        if attempt.status is not GenerationStatus.SUCCEEDED:
            raise InvalidReviewAttemptError(
                f"only a SUCCEEDED attempt can back a review (status: {attempt.status.value})"
            )
        pinned = attempt.input_refs.get("content_draft_id")
        if pinned != str(draft.id):
            raise InvalidReviewAttemptError(
                "the attempt's pinned draft does not match the reviewed draft"
            )

    def _validate_findings(
        self, draft: ContentDraft, findings: Sequence[ReviewFindingInput]
    ) -> list[dict[str, Any]]:
        if len(findings) > MAX_FINDINGS_PER_REVIEW:
            raise ReviewInputError(f"a review exceeds {MAX_FINDINGS_PER_REVIEW} findings")
        block_ids = {
            block["block_id"]
            for section in draft.body.get("sections", [])
            for block in section.get("blocks", [])
        }
        claim_ids = {
            str(usage.brief_claim_id) for usage in self._drafts.list_claim_usages(draft.id)
        }
        cleaned: list[dict[str, Any]] = []
        seen_keys: set[str] = set()
        for finding in findings:
            entry = finding.cleaned()
            key = entry["finding_key"]
            if key in seen_keys:
                raise ReviewInputError(f"finding key {key!r} is repeated")
            seen_keys.add(key)
            if entry["block_id"] is not None and entry["block_id"] not in block_ids:
                raise ReviewInputError(f"finding {key} anchors unknown block {entry['block_id']!r}")
            if entry["brief_claim_id"] is not None and entry["brief_claim_id"] not in claim_ids:
                raise ReviewInputError(
                    f"finding {key} references a claim the reviewed draft does not use"
                )
            cleaned.append(entry)
        return cleaned


def _validate_request_id(value: str | None) -> str | None:
    if value is None:
        return None
    if not is_valid_request_id(value):
        raise ReviewInputError("request_id is not a valid correlation identifier")
    return value


def _required_reason(value: str) -> str:
    cleaned = value.strip()
    if not cleaned or len(cleaned) > MAX_REASON_LENGTH:
        raise ReviewInputError(f"reason must be 1..{MAX_REASON_LENGTH} characters")
    return cleaned
