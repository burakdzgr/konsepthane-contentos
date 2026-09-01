"""Operator-authored idea creation, revision, and explicit selection.

Transport-neutral: the service validates, runs the deterministic originality
guards, flushes; the caller commits. Nothing here transitions workflow
state, mutates opportunity disposition, touches scores, packs, or signals —
and idea selection is an operator editorial decision, never publication
approval (ADR 0004) and never commissioning.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from contentos.core.context import is_valid_request_id
from contentos.discovery.models import DiscoveryItem
from contentos.fetching.snapshots import FetchSnapshot
from contentos.ideas.enums import (
    ContentType,
    IdeaOrigin,
    IdeaSelectionAction,
    IdeaSelectionActor,
)
from contentos.ideas.errors import (
    FakeUgcRejectionError,
    IdeaNotFoundError,
    IdeaRevisionConflictError,
    InvalidIdeaInputError,
    InvalidSelectionError,
    SelectionConflictError,
)
from contentos.ideas.models import Idea, IdeaSelectionEvent
from contentos.ideas.originality import (
    InputTitle,
    evaluate_originality,
    find_fake_ugc_violations,
)
from contentos.ideas.policy import DEFAULT_IDEA_ORIGINALITY_POLICY, IdeaOriginalityPolicy
from contentos.ideas.repository import IdeaRepository
from contentos.ideas.values import validate_exclusions, validate_planning_dimensions
from contentos.normalization.models import NormalizedDocument
from contentos.opportunities.errors import OpportunityNotFoundError
from contentos.opportunities.models import EditorialOpportunity
from contentos.opportunities.repository import OpportunityRepository
from contentos.workflow.models import EditorialWorkItem

MAX_WORKING_TITLE_LENGTH = 200
MAX_ANGLE_LENGTH = 2000
MAX_AUDIENCE_LENGTH = 500
MAX_VALUE_PROPOSITION_LENGTH = 1000
MAX_RATIONALE_LENGTH = 2000
MAX_SELECTION_REASON_LENGTH = 1000


@dataclass(frozen=True, slots=True)
class IdeaSelectionResult:
    """`created` is False when the command was a semantic no-op."""

    event: IdeaSelectionEvent
    created: bool


class IdeaService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repository = IdeaRepository(session)
        self._opportunities = OpportunityRepository(session)

    # --- authoring ----------------------------------------------------------

    def create_operator_idea(
        self,
        opportunity_id: uuid.UUID,
        *,
        working_title: str,
        angle: str,
        audience: str,
        value_proposition: str,
        rationale: str,
        content_type: ContentType,
        exclusions: list[str] | None = None,
        planning_dimensions: dict[str, Any] | None = None,
        policy: IdeaOriginalityPolicy = DEFAULT_IDEA_ORIGINALITY_POLICY,
    ) -> Idea:
        """Create a NEW independent candidate: fresh logical id, version 1."""
        opportunity = self._opportunities.get_by_id(opportunity_id)
        if opportunity is None:
            raise OpportunityNotFoundError(f"no opportunity with id {opportunity_id}")
        return self._insert_version(
            opportunity,
            logical_idea_id=uuid.uuid4(),
            version=1,
            working_title=working_title,
            angle=angle,
            audience=audience,
            value_proposition=value_proposition,
            rationale=rationale,
            content_type=content_type,
            exclusions=exclusions,
            planning_dimensions=planning_dimensions,
            policy=policy,
        )

    def revise_operator_idea(
        self,
        prior_idea_id: uuid.UUID,
        *,
        working_title: str,
        angle: str,
        audience: str,
        value_proposition: str,
        rationale: str,
        content_type: ContentType,
        exclusions: list[str] | None = None,
        planning_dimensions: dict[str, Any] | None = None,
        policy: IdeaOriginalityPolicy = DEFAULT_IDEA_ORIGINALITY_POLICY,
    ) -> Idea:
        """Create the next immutable version of an existing logical idea.

        The logical identity and owning opportunity come from the prior
        version — a caller can never move a logical idea between
        opportunities. Originality checks rerun against current inputs; the
        old version is untouched. The owning opportunity row is locked so
        concurrent revisions allocate distinct versions.
        """
        prior = self._repository.get_idea(prior_idea_id)
        if prior is None:
            raise IdeaNotFoundError(f"no idea version with id {prior_idea_id}")
        opportunity = self._repository.lock_opportunity(prior.opportunity_id)
        if opportunity is None:  # pragma: no cover - RESTRICT FK guarantees this
            raise OpportunityNotFoundError(f"no opportunity with id {prior.opportunity_id}")
        next_version = self._repository.max_version(prior.logical_idea_id) + 1
        return self._insert_version(
            opportunity,
            logical_idea_id=prior.logical_idea_id,
            version=next_version,
            working_title=working_title,
            angle=angle,
            audience=audience,
            value_proposition=value_proposition,
            rationale=rationale,
            content_type=content_type,
            exclusions=exclusions,
            planning_dimensions=planning_dimensions,
            policy=policy,
        )

    # --- selection ----------------------------------------------------------

    def select_idea(
        self,
        idea_id: uuid.UUID,
        *,
        reason: str,
        request_id: str | None = None,
    ) -> IdeaSelectionResult:
        """Make this EXACT idea version the effective selection.

        Selecting the version that is already effectively selected is a
        semantic no-op (no duplicate event). Selection never touches
        workflow, disposition, or any pack.
        """
        idea, cleaned_reason, validated_request_id = self._selection_inputs(
            idea_id, reason, request_id
        )
        self._repository.lock_opportunity(idea.opportunity_id)
        latest = self._repository.get_latest_selection_event(idea.opportunity_id)
        if (
            latest is not None
            and latest.action is IdeaSelectionAction.SELECTED
            and latest.idea_id == idea.id
        ):
            return IdeaSelectionResult(event=latest, created=False)
        event = self._repository.insert_selection_event(
            IdeaSelectionEvent(
                opportunity_id=idea.opportunity_id,
                idea_id=idea.id,
                action=IdeaSelectionAction.SELECTED,
                actor_origin=IdeaSelectionActor.OPERATOR,
                reason=cleaned_reason,
                request_id=validated_request_id,
                occurred_at=datetime.now(UTC),
            )
        )
        return IdeaSelectionResult(event=event, created=True)

    def deselect_idea(
        self,
        idea_id: uuid.UUID,
        *,
        reason: str,
        request_id: str | None = None,
    ) -> IdeaSelectionResult:
        """Clear the effective selection; the target must BE that selection.

        Deselecting never resurrects a previously selected candidate: after
        DESELECTED nothing is effective until an explicit new SELECTED.
        """
        idea, cleaned_reason, validated_request_id = self._selection_inputs(
            idea_id, reason, request_id
        )
        self._repository.lock_opportunity(idea.opportunity_id)
        latest = self._repository.get_latest_selection_event(idea.opportunity_id)
        effective_id = (
            latest.idea_id
            if latest is not None and latest.action is IdeaSelectionAction.SELECTED
            else None
        )
        if effective_id != idea.id:
            raise SelectionConflictError(
                "only the currently effective selected idea can be deselected"
            )
        event = self._repository.insert_selection_event(
            IdeaSelectionEvent(
                opportunity_id=idea.opportunity_id,
                idea_id=idea.id,
                action=IdeaSelectionAction.DESELECTED,
                actor_origin=IdeaSelectionActor.OPERATOR,
                reason=cleaned_reason,
                request_id=validated_request_id,
                occurred_at=datetime.now(UTC),
            )
        )
        return IdeaSelectionResult(event=event, created=True)

    def get_effective_selection(self, opportunity_id: uuid.UUID) -> Idea | None:
        """Deterministic projection of the append-only event stream.

        Rule: the latest event in monotonic event-id order decides — if it
        is SELECTED, its exact idea version is effective; if it is
        DESELECTED (or no event exists), nothing is effective. Because a
        DESELECTED command must target the current selection, the latest
        event alone fully determines the state.
        """
        if self._opportunities.get_by_id(opportunity_id) is None:
            raise OpportunityNotFoundError(f"no opportunity with id {opportunity_id}")
        latest = self._repository.get_latest_selection_event(opportunity_id)
        if latest is None or latest.action is not IdeaSelectionAction.SELECTED:
            return None
        return self._repository.get_idea(latest.idea_id)

    # --- internal -----------------------------------------------------------

    def _insert_version(
        self,
        opportunity: EditorialOpportunity,
        *,
        logical_idea_id: uuid.UUID,
        version: int,
        working_title: str,
        angle: str,
        audience: str,
        value_proposition: str,
        rationale: str,
        content_type: ContentType,
        exclusions: list[str] | None,
        planning_dimensions: dict[str, Any] | None,
        policy: IdeaOriginalityPolicy,
    ) -> Idea:
        if not isinstance(content_type, ContentType):
            raise InvalidIdeaInputError(
                "content_type must be a ContentType value; it is an editorial "
                "choice and is never inferred from a source article"
            )
        cleaned_title = _required_text("working_title", working_title, MAX_WORKING_TITLE_LENGTH)
        cleaned_angle = _required_text("angle", angle, MAX_ANGLE_LENGTH)
        cleaned_audience = _required_text("audience", audience, MAX_AUDIENCE_LENGTH)
        cleaned_value = _required_text(
            "value_proposition", value_proposition, MAX_VALUE_PROPOSITION_LENGTH
        )
        cleaned_rationale = _required_text("rationale", rationale, MAX_RATIONALE_LENGTH)
        cleaned_exclusions = validate_exclusions(exclusions)
        cleaned_dimensions = validate_planning_dimensions(planning_dimensions)

        violations = find_fake_ugc_violations(
            {
                "working_title": cleaned_title,
                "angle": cleaned_angle,
                "audience": cleaned_audience,
                "value_proposition": cleaned_value,
                "rationale": cleaned_rationale,
            },
            policy,
        )
        if violations:
            described = "; ".join(
                f"{violation['field']} matches {violation['pattern']!r}" for violation in violations
            )
            raise FakeUgcRejectionError(
                f"idea text claims user-generated content but no UGC provenance exists: {described}"
            )

        work_item = self._session.get(EditorialWorkItem, opportunity.work_item_id)
        if work_item is None:  # pragma: no cover - RESTRICT FK guarantees this
            raise OpportunityNotFoundError("opportunity has no resolvable work item")

        input_titles, distinct_sources = self._originality_inputs(opportunity.id)
        evaluation = evaluate_originality(
            working_title=cleaned_title,
            input_titles=input_titles,
            distinct_source_count=distinct_sources,
            policy=policy,
        )

        idea = Idea(
            logical_idea_id=logical_idea_id,
            opportunity_id=opportunity.id,
            version=version,
            working_title=cleaned_title,
            angle=cleaned_angle,
            audience=cleaned_audience,
            value_proposition=cleaned_value,
            content_type=content_type,
            locale=work_item.locale,
            market=work_item.market,
            rationale=cleaned_rationale,
            exclusions=cleaned_exclusions,
            planning_dimensions=cleaned_dimensions,
            originality_status=evaluation.status,
            originality_detail=evaluation.detail,
            originality_policy_snapshot=policy.snapshot(),
            origin=IdeaOrigin.OPERATOR,
        )
        try:
            with self._session.begin_nested():
                self._repository.insert_idea(idea)
        except IntegrityError:
            raise IdeaRevisionConflictError(
                "a concurrent revision allocated this idea version first"
            ) from None
        return idea

    def _originality_inputs(self, opportunity_id: uuid.UUID) -> tuple[list[InputTitle], int]:
        return originality_inputs_for_opportunity(self._session, opportunity_id)

    def _selection_inputs(
        self, idea_id: uuid.UUID, reason: str, request_id: str | None
    ) -> tuple[Idea, str, str | None]:
        idea = self._repository.get_idea(idea_id)
        if idea is None:
            raise IdeaNotFoundError(f"no idea version with id {idea_id}")
        cleaned_reason = _required_selection_reason(reason)
        if request_id is not None and not is_valid_request_id(request_id):
            raise InvalidSelectionError("request_id is not a valid correlation identifier")
        return idea, cleaned_reason, request_id


def originality_inputs_for_opportunity(
    session: Session, opportunity_id: uuid.UUID
) -> tuple[list[InputTitle], int]:
    """Titles and DERIVED distinct-source count for the admitted inputs.

    Source identity comes from the durable provenance chain
    NormalizedDocument -> FetchSnapshot -> DiscoveryItem -> Source; a caller
    can never submit a source count. Shared by the operator path and the
    model-assisted generation engine so both apply IDENTICAL originality
    inputs — never a weaker AI-side variant.
    """
    inputs = OpportunityRepository(session).list_research_inputs(opportunity_id)
    titles: list[InputTitle] = []
    source_ids: set[uuid.UUID] = set()
    for research_input in inputs:
        document = session.get(NormalizedDocument, research_input.normalized_document_id)
        if document is None:  # pragma: no cover - RESTRICT FK guarantees this
            continue
        titles.append(InputTitle(normalized_document_id=document.id, title=document.title))
        snapshot = session.get(FetchSnapshot, document.fetch_snapshot_id)
        if snapshot is None:  # pragma: no cover - RESTRICT FK guarantees this
            continue
        item = session.get(DiscoveryItem, snapshot.discovery_item_id)
        if item is not None:
            source_ids.add(item.source_id)
    return titles, len(source_ids)


def _required_text(name: str, value: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidIdeaInputError(f"{name} must not be empty")
    cleaned = " ".join(value.split())
    if len(cleaned) > limit:
        raise InvalidIdeaInputError(f"{name} exceeds the {limit}-character limit")
    return cleaned


def _required_selection_reason(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidSelectionError("a selection action requires a non-empty reason")
    cleaned = " ".join(value.split())
    if len(cleaned) > MAX_SELECTION_REASON_LENGTH:
        raise InvalidSelectionError(
            f"reason exceeds the {MAX_SELECTION_REASON_LENGTH}-character limit"
        )
    return cleaned
