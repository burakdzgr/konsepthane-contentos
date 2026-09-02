"""WorkflowService: the only domain boundary that transitions editorial state.

Structural validity only: this service answers "is state A allowed to move to
state B under the canonical docs/WORKFLOW.md matrix?" — it never checks
whether opportunity scores, evidence packs, ideas, intent analyses, or briefs
exist. Stage-specific artifact eligibility belongs to the later Phase 3
services that call this one.

Contract (the established Phase 2 service pattern): the service validates,
mutates, and FLUSHES; the caller owns COMMIT. Every committed state change
carries exactly one matching append-only event, written in the same
transaction.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from contentos.core.context import is_valid_request_id
from contentos.workflow.enums import WorkflowActorOrigin, WorkflowState, WorkItemOrigin
from contentos.workflow.errors import (
    InvalidWorkflowInputError,
    InvalidWorkflowTransitionError,
    WorkItemNotFoundError,
)
from contentos.workflow.models import EditorialWorkflowEvent, EditorialWorkItem
from contentos.workflow.repository import WorkflowRepository

# Promotion, not replay (accepted Phase 3 design §1.4): every work item's real
# durable history begins here. Callers can never choose an initial state.
INITIAL_STATE = WorkflowState.IDEA_SCORING

MAX_REASON_LENGTH = 1000
MAX_TITLE_LABEL_LENGTH = 200
MAX_LOCALE_LENGTH = 20

MAX_ARTIFACT_REFS_DEPTH = 4
MAX_ARTIFACT_REFS_ITEMS = 50
MAX_ARTIFACT_REFS_KEY_LENGTH = 100
MAX_ARTIFACT_REFS_STRING_LENGTH = 500

# Named responsible-state routing (PHASE4_WRITER_ARCHITECTURE.md §13): when a
# transition ENTERS CHANGES_REQUESTED, the caller may name the state
# responsible for the rework via the typed ``responsible_state`` parameter.
# The service validates it against this per-review-context vocabulary, records
# it in the validated entry event's artifact_refs under the reserved key, and
# derives the EXIT from that durable record. Entries without a recorded
# responsible state keep the original return-to-origin behavior. This is not a
# generic state setter: the vocabulary is fixed here, never caller-extensible.
RESPONSIBLE_STATE_REF_KEY = "responsible_state"

PERMITTED_RESPONSIBLE_STATES: dict[WorkflowState, frozenset[WorkflowState]] = {
    # From EDITING, rework responsibility may be routed to the upstream
    # production stage only (Writer rework: EDITING -> CHANGES_REQUESTED
    # (responsible=DRAFTING) -> DRAFTING). Later review loops extend this
    # map explicitly; contexts absent here permit NO named responsible state.
    WorkflowState.EDITING: frozenset({WorkflowState.DRAFTING}),
}

# The structural canonical transition matrix from docs/WORKFLOW.md. BLOCKED
# and CHANGES_REQUESTED exits are resolved dynamically from durable history
# (see _allowed_targets), never from a caller-supplied arbitrary target.
STRUCTURAL_TRANSITIONS: dict[WorkflowState, frozenset[WorkflowState]] = {
    WorkflowState.DISCOVERED: frozenset({WorkflowState.RESEARCHING, WorkflowState.REJECTED}),
    WorkflowState.RESEARCHING: frozenset(
        {WorkflowState.NORMALIZED, WorkflowState.BLOCKED, WorkflowState.REJECTED}
    ),
    WorkflowState.NORMALIZED: frozenset({WorkflowState.DUPLICATE_CHECK}),
    WorkflowState.DUPLICATE_CHECK: frozenset(
        {WorkflowState.DUPLICATE, WorkflowState.IDEA_SCORING, WorkflowState.BLOCKED}
    ),
    WorkflowState.DUPLICATE: frozenset({WorkflowState.REJECTED, WorkflowState.RESEARCHING}),
    WorkflowState.IDEA_SCORING: frozenset(
        {WorkflowState.EVIDENCE_BUILDING, WorkflowState.REJECTED, WorkflowState.BLOCKED}
    ),
    WorkflowState.EVIDENCE_BUILDING: frozenset(
        {WorkflowState.SEO_RESEARCH, WorkflowState.BLOCKED, WorkflowState.REJECTED}
    ),
    WorkflowState.SEO_RESEARCH: frozenset({WorkflowState.BRIEFING, WorkflowState.BLOCKED}),
    WorkflowState.BRIEFING: frozenset({WorkflowState.DRAFTING, WorkflowState.CHANGES_REQUESTED}),
    WorkflowState.DRAFTING: frozenset({WorkflowState.EDITING, WorkflowState.BLOCKED}),
    WorkflowState.EDITING: frozenset(
        {WorkflowState.QA_REVIEW, WorkflowState.CHANGES_REQUESTED, WorkflowState.REJECTED}
    ),
    WorkflowState.QA_REVIEW: frozenset(
        {
            WorkflowState.AWAITING_HUMAN_REVIEW,
            WorkflowState.CHANGES_REQUESTED,
            WorkflowState.BLOCKED,
        }
    ),
    WorkflowState.AWAITING_HUMAN_REVIEW: frozenset(
        {WorkflowState.APPROVED, WorkflowState.CHANGES_REQUESTED, WorkflowState.REJECTED}
    ),
    WorkflowState.APPROVED: frozenset({WorkflowState.SCHEDULED, WorkflowState.CHANGES_REQUESTED}),
    WorkflowState.SCHEDULED: frozenset(
        {WorkflowState.PUBLISHING, WorkflowState.APPROVAL_EXPIRED, WorkflowState.BLOCKED}
    ),
    WorkflowState.PUBLISHING: frozenset({WorkflowState.PUBLISHED, WorkflowState.BLOCKED}),
    WorkflowState.PUBLISHED: frozenset({WorkflowState.PINTEREST_PENDING, WorkflowState.MEASURING}),
    WorkflowState.PINTEREST_PENDING: frozenset(
        {WorkflowState.DISTRIBUTED, WorkflowState.BLOCKED, WorkflowState.MEASURING}
    ),
    WorkflowState.DISTRIBUTED: frozenset({WorkflowState.MEASURING}),
    # MEASURING -> MEASURING is an explicit canonical self-loop.
    WorkflowState.MEASURING: frozenset(
        {WorkflowState.REFRESH_CANDIDATE, WorkflowState.ARCHIVED, WorkflowState.MEASURING}
    ),
    WorkflowState.REFRESH_CANDIDATE: frozenset({WorkflowState.RESEARCHING, WorkflowState.ARCHIVED}),
    WorkflowState.APPROVAL_EXPIRED: frozenset(
        {WorkflowState.QA_REVIEW, WorkflowState.AWAITING_HUMAN_REVIEW}
    ),
    # Terminal states with an explicit canonical reopen path only.
    WorkflowState.REJECTED: frozenset({WorkflowState.RESEARCHING}),
    WorkflowState.ARCHIVED: frozenset({WorkflowState.RESEARCHING}),
}


class WorkflowService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repository = WorkflowRepository(session)

    def create_work_item(
        self,
        *,
        origin: WorkItemOrigin,
        title_working_label: str,
        reason: str,
        actor_origin: WorkflowActorOrigin,
        locale: str = "tr-TR",
        market: str = "TR",
        artifact_refs: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> EditorialWorkItem:
        """Create a work item at INITIAL_STATE with its creation event, atomically.

        Phase 2 eligibility is deliberately NOT evaluated here — the intake
        task (Phase 3 Task 3) validates eligibility first and then calls this
        primitive with the exact Phase 2 identities in ``artifact_refs``.
        Promotion idempotency (one work item per promoted research root) is
        likewise Task 3's identity, documented there; this layer creates
        exactly what it is asked to create.
        """
        if not isinstance(origin, WorkItemOrigin):
            raise InvalidWorkflowInputError("origin must be a WorkItemOrigin value")
        cleaned_label = _validate_bounded_text(
            "title_working_label", title_working_label, MAX_TITLE_LABEL_LENGTH
        )
        cleaned_locale = _validate_bounded_text("locale", locale, MAX_LOCALE_LENGTH)
        cleaned_market = market.strip()
        if len(cleaned_market) != 2:
            raise InvalidWorkflowInputError("market must be a two-letter country code")
        cleaned_reason = _validate_bounded_text("reason", reason, MAX_REASON_LENGTH)
        validated_refs = _validate_artifact_refs(artifact_refs)
        validated_request_id = _validate_request_id(request_id)
        _validate_actor_origin(actor_origin)

        now = datetime.now(UTC)
        item = EditorialWorkItem(
            locale=cleaned_locale,
            market=cleaned_market,
            origin=origin,
            current_state=INITIAL_STATE,
            current_state_entered_at=now,
            title_working_label=cleaned_label,
        )
        self._repository.insert_work_item(item)
        self._repository.append_event(
            EditorialWorkflowEvent(
                work_item_id=item.id,
                from_state=None,
                to_state=INITIAL_STATE,
                actor_origin=actor_origin,
                reason=cleaned_reason,
                artifact_refs=validated_refs,
                request_id=validated_request_id,
                occurred_at=now,
            )
        )
        return item

    def transition(
        self,
        work_item_id: uuid.UUID,
        to_state: WorkflowState,
        *,
        actor_origin: WorkflowActorOrigin,
        reason: str,
        artifact_refs: dict[str, Any] | None = None,
        request_id: str | None = None,
        responsible_state: WorkflowState | None = None,
    ) -> EditorialWorkItem:
        """Apply one structurally validated transition under a row lock.

        The transition is validated against the state actually observed under
        the lock, so a raced/stale request fails with a typed error instead of
        appending impossible history.

        ``responsible_state`` is legal ONLY when entering CHANGES_REQUESTED
        and only when the value is in the fixed per-context vocabulary
        (PERMITTED_RESPONSIBLE_STATES); the service records it durably in the
        entry event's artifact_refs and later derives the exit from it.
        """
        if not isinstance(to_state, WorkflowState):
            raise InvalidWorkflowInputError("to_state must be a WorkflowState value")
        _validate_actor_origin(actor_origin)
        cleaned_reason = _validate_bounded_text("reason", reason, MAX_REASON_LENGTH)
        validated_refs = _validate_artifact_refs(artifact_refs)
        if RESPONSIBLE_STATE_REF_KEY in validated_refs:
            raise InvalidWorkflowInputError(
                "artifact_refs may not set 'responsible_state' directly; "
                "use the typed responsible_state parameter"
            )
        if responsible_state is not None:
            if not isinstance(responsible_state, WorkflowState):
                raise InvalidWorkflowInputError("responsible_state must be a WorkflowState value")
            if to_state is not WorkflowState.CHANGES_REQUESTED:
                raise InvalidWorkflowInputError(
                    "responsible_state applies only when entering CHANGES_REQUESTED"
                )
        validated_request_id = _validate_request_id(request_id)

        item = self._repository.get_by_id_for_update(work_item_id)
        if item is None:
            raise WorkItemNotFoundError(f"no editorial work item with id {work_item_id}")

        current = item.current_state
        allowed = self._allowed_targets(item)
        if to_state not in allowed:
            raise InvalidWorkflowTransitionError(
                f"transition '{current.value}' -> '{to_state.value}' is not allowed"
            )
        if responsible_state is not None:
            permitted = PERMITTED_RESPONSIBLE_STATES.get(current, frozenset())
            if responsible_state not in permitted:
                raise InvalidWorkflowTransitionError(
                    f"'{responsible_state.value}' is not a permitted responsible "
                    f"state when entering changes_requested from '{current.value}'"
                )
            validated_refs = {
                **validated_refs,
                RESPONSIBLE_STATE_REF_KEY: responsible_state.value,
            }

        now = datetime.now(UTC)
        if to_state is WorkflowState.BLOCKED:
            item.blocked_reason = cleaned_reason
        elif current is WorkflowState.BLOCKED:
            # Leaving BLOCKED clears the current-row projection; the original
            # reason stays permanently in the immutable event history.
            item.blocked_reason = None
        if to_state is WorkflowState.REJECTED:
            item.rejected_reason = cleaned_reason
        elif current is WorkflowState.REJECTED:
            item.rejected_reason = None

        item.current_state = to_state
        item.current_state_entered_at = now
        self._repository.append_event(
            EditorialWorkflowEvent(
                work_item_id=item.id,
                from_state=current,
                to_state=to_state,
                actor_origin=actor_origin,
                reason=cleaned_reason,
                artifact_refs=validated_refs,
                request_id=validated_request_id,
                occurred_at=now,
            )
        )
        self._session.flush()
        return item

    def resolve_block(
        self,
        work_item_id: uuid.UUID,
        *,
        reason: str,
        request_id: str | None = None,
    ) -> EditorialWorkItem:
        """Explicit operator resolution of BLOCKED back to the prior state.

        The resume target is derived ONLY from durable event history (the
        state the item entered BLOCKED from) — the caller can never supply
        a target. No prior resumable state is a typed conflict.
        """
        item = self._repository.get_by_id(work_item_id)
        if item is None:
            raise WorkItemNotFoundError(f"no editorial work item with id {work_item_id}")
        if item.current_state is not WorkflowState.BLOCKED:
            raise InvalidWorkflowTransitionError(
                f"block resolution requires BLOCKED (current: {item.current_state.value})"
            )
        prior = self._entry_from_state(item.id, WorkflowState.BLOCKED)
        if prior is None:
            raise InvalidWorkflowTransitionError(
                "durable history records no state to resume to from BLOCKED"
            )
        return self.transition(
            work_item_id,
            prior,
            actor_origin=WorkflowActorOrigin.OPERATOR,
            reason=reason,
            request_id=request_id,
        )

    def reject_blocked(
        self,
        work_item_id: uuid.UUID,
        *,
        reason: str,
        request_id: str | None = None,
    ) -> EditorialWorkItem:
        """Explicit operator BLOCKED -> REJECTED with a required reason."""
        item = self._repository.get_by_id(work_item_id)
        if item is None:
            raise WorkItemNotFoundError(f"no editorial work item with id {work_item_id}")
        if item.current_state is not WorkflowState.BLOCKED:
            raise InvalidWorkflowTransitionError(
                f"blocked rejection requires BLOCKED (current: {item.current_state.value})"
            )
        return self.transition(
            work_item_id,
            WorkflowState.REJECTED,
            actor_origin=WorkflowActorOrigin.OPERATOR,
            reason=reason,
            request_id=request_id,
        )

    def _allowed_targets(self, item: EditorialWorkItem) -> frozenset[WorkflowState]:
        current = item.current_state
        if current is WorkflowState.BLOCKED:
            # WORKFLOW.md: resume the prior state after explicit resolution,
            # or REJECTED. The prior state is derived from durable history,
            # never trusted from the caller.
            prior = self._entry_from_state(item.id, WorkflowState.BLOCKED)
            targets = {WorkflowState.REJECTED}
            if prior is not None:
                targets.add(prior)
            return frozenset(targets)
        if current is WorkflowState.CHANGES_REQUESTED:
            # WORKFLOW.md: "return to the named responsible state". The exit
            # target is derived ONLY from the durable entry event: the
            # recorded responsible state when one was named at entry, else
            # return-to-origin (the state the item entered CHANGES_REQUESTED
            # from). Never a caller-supplied target.
            event = self._repository.get_latest_entry_event(
                item.id, WorkflowState.CHANGES_REQUESTED
            )
            if event is None:
                return frozenset()
            recorded = (event.artifact_refs or {}).get(RESPONSIBLE_STATE_REF_KEY)
            if recorded is not None:
                try:
                    return frozenset({WorkflowState(recorded)})
                except ValueError:
                    # Fail closed and loudly: never silently reroute when the
                    # durable record cannot be resolved.
                    raise InvalidWorkflowTransitionError(
                        "durable history records an unrecognized responsible "
                        "state for changes_requested"
                    ) from None
            prior = event.from_state
            return frozenset({prior}) if prior is not None else frozenset()
        return STRUCTURAL_TRANSITIONS.get(current, frozenset())

    def _entry_from_state(
        self, work_item_id: uuid.UUID, entered_state: WorkflowState
    ) -> WorkflowState | None:
        event = self._repository.get_latest_entry_event(work_item_id, entered_state)
        return event.from_state if event is not None else None


def _validate_bounded_text(name: str, value: str, limit: int) -> str:
    if not isinstance(value, str):
        raise InvalidWorkflowInputError(f"{name} must be a string")
    cleaned = value.strip()
    if not cleaned:
        raise InvalidWorkflowInputError(f"{name} must not be empty")
    if len(cleaned) > limit:
        raise InvalidWorkflowInputError(f"{name} exceeds the {limit}-character limit")
    return cleaned


def _validate_actor_origin(value: WorkflowActorOrigin) -> None:
    if not isinstance(value, WorkflowActorOrigin):
        raise InvalidWorkflowInputError("actor_origin must be a WorkflowActorOrigin value")


def _validate_request_id(value: str | None) -> str | None:
    if value is None:
        return None
    if not is_valid_request_id(value):
        raise InvalidWorkflowInputError("request_id is not a valid correlation identifier")
    return value


def _validate_artifact_refs(value: dict[str, Any] | None) -> dict[str, Any]:
    """Bounded JSON-object snapshot: identifiers only, never payloads/secrets."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise InvalidWorkflowInputError("artifact_refs must be a JSON object")

    def walk(node: Any, depth: int) -> None:
        if depth > MAX_ARTIFACT_REFS_DEPTH:
            raise InvalidWorkflowInputError("artifact_refs exceeds the allowed nesting depth")
        if isinstance(node, dict):
            if len(node) > MAX_ARTIFACT_REFS_ITEMS:
                raise InvalidWorkflowInputError("artifact_refs exceeds the allowed item count")
            for key, child in node.items():
                if not isinstance(key, str) or not key.strip():
                    raise InvalidWorkflowInputError("artifact_refs keys must be non-empty strings")
                if len(key) > MAX_ARTIFACT_REFS_KEY_LENGTH:
                    raise InvalidWorkflowInputError("artifact_refs key exceeds the length limit")
                walk(child, depth + 1)
        elif isinstance(node, list):
            if len(node) > MAX_ARTIFACT_REFS_ITEMS:
                raise InvalidWorkflowInputError("artifact_refs exceeds the allowed item count")
            for child in node:
                walk(child, depth + 1)
        elif isinstance(node, str):
            if len(node) > MAX_ARTIFACT_REFS_STRING_LENGTH:
                raise InvalidWorkflowInputError("artifact_refs value exceeds the length limit")
        elif node is not None and not isinstance(node, (int, float, bool)):
            raise InvalidWorkflowInputError("artifact_refs values must be JSON scalars")

    walk(value, 1)
    return value
