"""DraftService: the single validated persistence path for content drafts.

Both origins funnel through the SAME structural gates (accepted Phase 4
design §6.1/§6.5): the pinned brief must be the exact
ACCEPTED_FOR_DRAFTING version and its work item must be in DRAFTING;
every body claim ref must be a claim of THAT brief; section keys must
satisfy the brief's section contract; URLs/HTML never enter text;
placeholder blocks must reference real brief link/media needs; and the
body's claim references are mirrored 1:1 into relational
`draft_claim_usages` so provenance stays queryable forever.

Idempotency:
- machine path: one draft per SUCCEEDED WRITER_DRAFT attempt
  (`generation_attempt_id` UNIQUE) — a redelivered materialization
  returns the existing draft;
- manual path: `manual_input_hash` (canonical identity over the exact
  brief, body schema, body, claim mapping, coverage, and validation
  policy version) — the same operator submission converges on the same
  durable draft; a substantively changed submission is a NEW version.
`request_id` is correlation metadata only, never business identity.

The service flushes; the caller owns COMMIT. Deeper Writer policies
(numeric-assertion gate, handling-coverage validation, originality
guards) arrive in Phase 4 Task 3 and slot into `_create_draft` without
changing this contract; until then the persisted snapshots truthfully
record structural-only validation and `not_checked` originality.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from contentos.ai.enums import GenerationPurpose, GenerationStatus
from contentos.ai.hashing import sha256_hex
from contentos.ai.models import AiGenerationAttempt
from contentos.briefs.enums import BriefStatus
from contentos.briefs.models import BriefClaim, ContentBrief
from contentos.briefs.repository import BriefRepository
from contentos.core.context import is_valid_request_id
from contentos.drafts.enums import (
    DraftActorOrigin,
    DraftBlockKind,
    DraftOrigin,
    DraftStatus,
)
from contentos.drafts.errors import (
    DraftConflictError,
    DraftInputError,
    DraftPreconditionError,
    InvalidDraftAttemptError,
)
from contentos.drafts.models import ContentDraft, DraftClaimUsage, DraftStatusEvent
from contentos.drafts.policies import (
    DEFAULT_WRITER_ORIGINALITY_POLICY,
    DEFAULT_WRITER_VALIDATION_POLICY,
    WriterOriginalityPolicy,
    WriterValidationPolicy,
    build_required_handling_manifest,
    validate_claim_semantics,
    validate_handling_coverage,
    validate_originality,
)
from contentos.drafts.repository import DraftRepository
from contentos.drafts.values import (
    BODY_SCHEMA_VERSION,
    MANUAL_DRAFT_ENGINE_NAME,
    MANUAL_DRAFT_ENGINE_VERSION,
    MAX_TITLE_PROPOSAL_LENGTH,
    WRITER_ENGINE_NAME,
    WRITER_ENGINE_VERSION,
    DraftBodyInput,
    require_safe_text,
)
from contentos.evidence_packs.repository import EvidencePackRepository
from contentos.research.models import ResearchEvidence
from contentos.workflow.enums import WorkflowState
from contentos.workflow.repository import WorkflowRepository

MAX_REASON_LENGTH = 1000


@dataclass(frozen=True, slots=True)
class DraftCreation:
    """`created` is False when an idempotent identity was reused."""

    draft: ContentDraft
    created: bool
    superseded_draft_id: uuid.UUID | None


class DraftService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repository = DraftRepository(session)
        self._briefs = BriefRepository(session)
        self._packs = EvidencePackRepository(session)
        self._workflow = WorkflowRepository(session)

    # --- public creation paths ----------------------------------------------

    def create_operator_draft(
        self,
        content_brief_id: uuid.UUID,
        body: DraftBodyInput,
        *,
        title_proposal: str | None = None,
        supersede_reason: str | None = None,
        request_id: str | None = None,
        validation_policy: WriterValidationPolicy = DEFAULT_WRITER_VALIDATION_POLICY,
        originality_policy: WriterOriginalityPolicy = DEFAULT_WRITER_ORIGINALITY_POLICY,
    ) -> DraftCreation:
        """Human-authored draft: same gates, no AI attempt (real or fake)."""
        return self._create_draft(
            content_brief_id,
            body,
            origin=DraftOrigin.OPERATOR,
            generation_attempt=None,
            engine_name=MANUAL_DRAFT_ENGINE_NAME,
            engine_version=MANUAL_DRAFT_ENGINE_VERSION,
            title_proposal=title_proposal,
            supersede_reason=supersede_reason,
            request_id=request_id,
            validation_policy=validation_policy,
            originality_policy=originality_policy,
        )

    def create_generated_draft(
        self,
        content_brief_id: uuid.UUID,
        body: DraftBodyInput,
        *,
        generation_attempt: AiGenerationAttempt,
        title_proposal: str | None = None,
        supersede_reason: str | None = None,
        request_id: str | None = None,
        validation_policy: WriterValidationPolicy = DEFAULT_WRITER_VALIDATION_POLICY,
        originality_policy: WriterOriginalityPolicy = DEFAULT_WRITER_ORIGINALITY_POLICY,
    ) -> DraftCreation:
        """Writer-engine draft materialization for one SUCCEEDED attempt."""
        self._validate_attempt(generation_attempt, content_brief_id)
        return self._create_draft(
            content_brief_id,
            body,
            origin=DraftOrigin.WRITER_ENGINE,
            generation_attempt=generation_attempt,
            engine_name=WRITER_ENGINE_NAME,
            engine_version=WRITER_ENGINE_VERSION,
            title_proposal=title_proposal,
            supersede_reason=supersede_reason,
            request_id=request_id,
            validation_policy=validation_policy,
            originality_policy=originality_policy,
        )

    # --- core ---------------------------------------------------------------

    def _create_draft(
        self,
        content_brief_id: uuid.UUID,
        body: DraftBodyInput,
        *,
        origin: DraftOrigin,
        generation_attempt: AiGenerationAttempt | None,
        engine_name: str,
        engine_version: str,
        title_proposal: str | None,
        supersede_reason: str | None,
        request_id: str | None,
        validation_policy: WriterValidationPolicy,
        originality_policy: WriterOriginalityPolicy,
    ) -> DraftCreation:
        validated_request_id = _validate_request_id(request_id)
        cleaned_title = (
            require_safe_text("title_proposal", title_proposal, MAX_TITLE_PROPOSAL_LENGTH)
            if title_proposal is not None
            else None
        )

        brief = self._require_accepted_brief(content_brief_id)
        # Serialize version allocation/supersession on the work-item row and
        # revalidate the stage under the lock.
        work_item = self._workflow.get_by_id_for_update(brief.work_item_id)
        if work_item is None:  # pragma: no cover - RESTRICT FK guarantees this
            raise DraftPreconditionError("the brief has no resolvable work item")
        if work_item.current_state is not WorkflowState.DRAFTING:
            raise DraftPreconditionError(
                "draft creation requires the work item to be in DRAFTING "
                f"(current: {work_item.current_state.value})"
            )

        cleaned_body = body.cleaned()
        self._validate_section_contract(brief, cleaned_body)
        self._validate_need_refs(brief, cleaned_body)
        claims = self._briefs.list_claims(brief.id)
        claims_by_id = {str(claim.id): claim for claim in claims}
        usages = self._validate_claim_refs(claims_by_id, cleaned_body)

        # Writer-stage deterministic policy gates (design section 6/7): the
        # required-handling manifest from the pinned artifacts, coverage,
        # the fact-creation envelope, and the originality guard — all
        # fail-closed BEFORE any draft row exists, for BOTH origins.
        pack = self._packs.get_pack(brief.evidence_pack_id)
        if pack is None:  # pragma: no cover - RESTRICT FK guarantees this
            raise DraftPreconditionError("the brief has no resolvable evidence pack")
        contradictions = self._packs.list_contradictions(pack.id)
        manifest = build_required_handling_manifest(brief, pack, contradictions, claims)
        uncertainty_coverage = validate_handling_coverage(manifest, cleaned_body, validation_policy)
        validate_claim_semantics(cleaned_body, claims_by_id, validation_policy)
        originality_result = validate_originality(
            cleaned_body,
            cleaned_title,
            self._evidence_statements(claims),
            brief,
            originality_policy,
        )
        validation_policy_snapshot: dict[str, Any] = {
            **validation_policy.snapshot(),
            "body_schema": BODY_SCHEMA_VERSION,
        }
        originality_policy_snapshot: dict[str, Any] = originality_policy.snapshot()

        usage_payload = [
            {
                "brief_claim_id": usage[0],
                "section_key": usage[1],
                "block_id": usage[2],
            }
            for usage in usages
        ]
        content_hash = sha256_hex(
            {
                "schema": BODY_SCHEMA_VERSION,
                "work_item_id": str(work_item.id),
                "content_brief_id": str(brief.id),
                "locale": work_item.locale,
                "market": work_item.market,
                "origin": origin.value,
                "engine_name": engine_name,
                "engine_version": engine_version,
                "title_proposal": cleaned_title,
                "body": cleaned_body,
                "claim_usages": usage_payload,
                "uncertainty_coverage": uncertainty_coverage,
                "validation_policy_snapshot": validation_policy_snapshot,
                "originality_policy_snapshot": originality_policy_snapshot,
                "originality_result": originality_result,
            }
        )

        manual_input_hash: str | None = None
        if origin is DraftOrigin.OPERATOR:
            manual_input_hash = sha256_hex(
                {
                    "content_brief_id": str(brief.id),
                    "body_schema_version": BODY_SCHEMA_VERSION,
                    "body": cleaned_body,
                    "claim_usages": usage_payload,
                    "uncertainty_coverage": uncertainty_coverage,
                    "validation_policy_version": validation_policy.version,
                }
            )
            existing = self._repository.get_by_manual_identity(work_item.id, manual_input_hash)
            if existing is not None:
                return DraftCreation(draft=existing, created=False, superseded_draft_id=None)
        else:
            assert generation_attempt is not None
            existing = self._repository.get_by_generation_attempt(generation_attempt.id)
            if existing is not None:
                if existing.content_hash != content_hash:
                    raise DraftConflictError(
                        "this generation attempt already materialized a draft "
                        "with different content; refusing to overwrite it"
                    )
                return DraftCreation(draft=existing, created=False, superseded_draft_id=None)

        active = self._repository.get_active_draft(work_item.id)
        cleaned_supersede_reason: str | None = None
        if active is not None:
            if supersede_reason is None or not supersede_reason.strip():
                raise DraftInputError("superseding the active draft requires an explicit reason")
            cleaned_supersede_reason = _required_reason(supersede_reason)

        try:
            with self._session.begin_nested():
                if active is not None:
                    active.status = DraftStatus.SUPERSEDED
                    self._session.flush()
                draft = self._repository.insert_draft(
                    ContentDraft(
                        work_item_id=work_item.id,
                        content_brief_id=brief.id,
                        version=self._repository.next_version(work_item.id),
                        locale=work_item.locale,
                        market=work_item.market,
                        origin=origin,
                        generation_attempt_id=(
                            generation_attempt.id if generation_attempt is not None else None
                        ),
                        manual_input_hash=manual_input_hash,
                        engine_name=engine_name,
                        engine_version=engine_version,
                        title_proposal=cleaned_title,
                        body=cleaned_body,
                        body_schema_version=BODY_SCHEMA_VERSION,
                        uncertainty_coverage=uncertainty_coverage,
                        validation_policy_snapshot=validation_policy_snapshot,
                        originality_policy_snapshot=originality_policy_snapshot,
                        originality_result=originality_result,
                        status=DraftStatus.ACTIVE,
                        content_hash=content_hash,
                    )
                )
                for brief_claim_id, section_key, block_id in usages:
                    self._repository.insert_claim_usage(
                        DraftClaimUsage(
                            draft_id=draft.id,
                            brief_claim_id=uuid.UUID(brief_claim_id),
                            section_key=section_key,
                            block_id=block_id,
                        )
                    )
                if active is not None:
                    assert cleaned_supersede_reason is not None
                    active.superseded_by_draft_id = draft.id
                    self._repository.append_status_event(
                        DraftStatusEvent(
                            draft_id=active.id,
                            from_status=DraftStatus.ACTIVE,
                            to_status=DraftStatus.SUPERSEDED,
                            actor_origin=DraftActorOrigin.OPERATOR,
                            reason=cleaned_supersede_reason,
                            request_id=validated_request_id,
                            replacement_draft_id=draft.id,
                            occurred_at=datetime.now(UTC),
                        )
                    )
        except IntegrityError:
            # A concurrent identical submission won the race: converge on it.
            winner: ContentDraft | None = None
            if manual_input_hash is not None:
                winner = self._repository.get_by_manual_identity(work_item.id, manual_input_hash)
            elif generation_attempt is not None:
                winner = self._repository.get_by_generation_attempt(generation_attempt.id)
            if winner is not None and winner.content_hash == content_hash:
                return DraftCreation(draft=winner, created=False, superseded_draft_id=None)
            raise DraftConflictError(
                "draft persistence conflicted with concurrently written state"
            ) from None

        return DraftCreation(
            draft=draft,
            created=True,
            superseded_draft_id=active.id if active is not None else None,
        )

    # --- gates --------------------------------------------------------------

    def _require_accepted_brief(self, content_brief_id: uuid.UUID) -> ContentBrief:
        brief = self._briefs.get_brief(content_brief_id)
        if brief is None:
            raise DraftPreconditionError(f"no content brief with id {content_brief_id}")
        if brief.status is not BriefStatus.ACCEPTED_FOR_DRAFTING:
            raise DraftPreconditionError(
                "draft creation requires the EXACT accepted brief version "
                f"(brief status: {brief.status.value})"
            )
        return brief

    def _validate_attempt(self, attempt: AiGenerationAttempt, content_brief_id: uuid.UUID) -> None:
        if attempt.purpose is not GenerationPurpose.WRITER_DRAFT:
            raise InvalidDraftAttemptError(
                f"attempt purpose {attempt.purpose.value!r} cannot back a writer draft"
            )
        if attempt.status is not GenerationStatus.SUCCEEDED:
            raise InvalidDraftAttemptError(
                f"only a SUCCEEDED attempt can back a draft (status: {attempt.status.value})"
            )
        pinned = attempt.input_refs.get("content_brief_id")
        if pinned != str(content_brief_id):
            raise InvalidDraftAttemptError(
                "the attempt's pinned brief does not match this draft's brief"
            )

    def _validate_section_contract(self, brief: ContentBrief, cleaned_body: dict[str, Any]) -> None:
        required_keys = [str(entry.get("key")) for entry in brief.required_sections]
        optional_keys = {str(entry.get("key")) for entry in brief.optional_sections}
        body_keys = [section["key"] for section in cleaned_body["sections"]]
        body_key_set = set(body_keys)

        missing = [key for key in required_keys if key not in body_key_set]
        if missing:
            raise DraftInputError(
                f"the draft is missing required brief sections: {', '.join(missing)}"
            )
        allowed = set(required_keys) | optional_keys
        unknown = [key for key in body_keys if key not in allowed]
        if unknown:
            raise DraftInputError(
                f"the draft contains sections outside the brief contract: {', '.join(unknown)}"
            )

    def _validate_need_refs(self, brief: ContentBrief, cleaned_body: dict[str, Any]) -> None:
        link_needs = len(brief.internal_link_needs)
        media_needs = len(brief.media_needs)
        for section in cleaned_body["sections"]:
            for block in section["blocks"]:
                if block["kind"] == DraftBlockKind.INTERNAL_LINK_NEED.value:
                    if block["link_need_ref"] >= link_needs:
                        raise DraftInputError(
                            f"block {block['block_id']} references internal link need "
                            f"{block['link_need_ref']}, but the brief has {link_needs}"
                        )
                if block["kind"] == DraftBlockKind.MEDIA_NEED.value:
                    if block["media_need_ref"] >= media_needs:
                        raise DraftInputError(
                            f"block {block['block_id']} references media need "
                            f"{block['media_need_ref']}, but the brief has {media_needs}"
                        )

    def _evidence_statements(self, claims: list[BriefClaim]) -> list[str]:
        statements: list[str] = []
        for claim in claims:
            for link in self._briefs.list_claim_evidence(claim.id):
                evidence = self._session.get(ResearchEvidence, link.research_evidence_id)
                if evidence is not None:
                    statements.append(evidence.statement)
        return statements

    def _validate_claim_refs(
        self, claims_by_id: dict[str, BriefClaim], cleaned_body: dict[str, Any]
    ) -> list[tuple[str, str, str]]:
        """Return the 1:1 relational mirror (claim id, section key, block id)."""
        known_claims = set(claims_by_id)
        usages: list[tuple[str, str, str]] = []
        for section in cleaned_body["sections"]:
            for block in section["blocks"]:
                for claim_ref in block["claim_refs"]:
                    if claim_ref not in known_claims:
                        raise DraftInputError(
                            f"block {block['block_id']} references claim {claim_ref}, "
                            "which is not a claim of the pinned brief"
                        )
                    usages.append((claim_ref, section["key"], block["block_id"]))
        return usages


def _validate_request_id(value: str | None) -> str | None:
    if value is None:
        return None
    if not is_valid_request_id(value):
        raise DraftInputError("request_id is not a valid correlation identifier")
    return value


def _required_reason(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise DraftInputError("reason must not be empty")
    if len(cleaned) > MAX_REASON_LENGTH:
        raise DraftInputError(f"reason exceeds the {MAX_REASON_LENGTH}-character limit")
    return cleaned
