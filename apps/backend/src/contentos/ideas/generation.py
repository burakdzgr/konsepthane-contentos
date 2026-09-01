"""Model-assisted idea candidate generation engine (design §18 command).

EditorialOpportunity -> deterministic bounded research projection ->
structured candidate batch through the provider-neutral AI boundary ->
deterministic validation/originality guards -> immutable MODEL_ASSISTED
Idea rows pinning the exact SUCCEEDED attempt.

The engine depends ONLY on the provider-neutral boundary — it works
identically with the deterministic fake provider and never knows OpenAI
exists. Generation NEVER selects an idea, commissions an opportunity,
transitions workflow, or rebuilds an evidence pack. Provider/validation
failures produce a durable failed attempt and ZERO ideas.

Precondition (accepted design §18): idea generation is an operator command
on a COMMISSIONED opportunity; the engine validates the disposition and
never mutates it.

Idempotency (Task-8 consequence): raw model output is never persisted, so
an exact retry that reuses a stored SUCCEEDED attempt returns the ideas
already materialized for that attempt — the provider is never re-invoked
under the same identity, and a reused attempt with no linked ideas is a
typed IncompleteMaterializationError (recover with retry_number + 1).
"""

import json
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from contentos.ai.dto import GenerationRequest
from contentos.ai.enums import GenerationPurpose, GenerationStatus
from contentos.ai.models import AiGenerationAttempt
from contentos.ai.protocol import StructuredGenerationProvider
from contentos.ai.service import GenerationExecution, StructuredGenerationService
from contentos.ai.validation import StructuredOutputSpec
from contentos.discovery.models import DiscoveryItem
from contentos.fetching.snapshots import FetchSnapshot
from contentos.ideas.enums import ContentType, IdeaOrigin
from contentos.ideas.errors import (
    IncompleteMaterializationError,
    InvalidGenerationAttemptError,
    InvalidIdeaInputError,
    OpportunityNotCommissionedError,
)
from contentos.ideas.generation_schemas import (
    IDEA_CANDIDATE_SCHEMA_NAME,
    IDEA_CANDIDATE_SCHEMA_VERSION,
    MAX_CANDIDATES,
    MIN_CANDIDATES,
    IdeaCandidateBatchV1,
)
from contentos.ideas.models import Idea
from contentos.ideas.originality import evaluate_originality, find_fake_ugc_violations
from contentos.ideas.policy import DEFAULT_IDEA_ORIGINALITY_POLICY, IdeaOriginalityPolicy
from contentos.ideas.repository import IdeaRepository
from contentos.ideas.service import originality_inputs_for_opportunity
from contentos.ideas.values import validate_exclusions, validate_planning_dimensions
from contentos.normalization.models import NormalizedDocument
from contentos.opportunities.enums import OpportunityDisposition
from contentos.opportunities.errors import OpportunityNotFoundError
from contentos.opportunities.models import EditorialOpportunity
from contentos.opportunities.repository import OpportunityRepository
from contentos.research.enums import VerificationStatus
from contentos.research.models import ResearchEvidence
from contentos.sources.models import Source
from contentos.workflow.models import EditorialWorkItem

IDEA_GENERATOR_NAME = "idea-generator"
IDEA_GENERATOR_VERSION = "1"
IDEA_TEMPLATE_NAME = "idea-candidates"
IDEA_TEMPLATE_VERSION = "1"
GENERATION_INPUT_REFS_SCHEMA = "idea-generation/1"

# Deterministic projection bounds. Over-bound artifacts are truncated by the
# stable repository orderings (research inputs: added_at, id; evidence:
# extracted_at, id) — omitted items are simply omitted, never summarized.
MAX_PROJECTED_INPUTS = 10
MAX_PROJECTED_EVIDENCE = 20
MAX_EVIDENCE_STATEMENT_CHARS = 500
MAX_OUTPUT_TOKENS = 8_000

# The rendered instructions are versioned by IDEA_TEMPLATE_NAME/VERSION;
# substantive changes REQUIRE a version bump (they are not hashed).
_TEMPLATE_V1 = """\
You propose editorial content CONCEPTS for Konsepthane, a Turkish practical
celebration/event-planning publication. You receive a research projection
(topic, admitted research titles, evidence statements with status labels,
source diversity, duplicate context) and must propose exactly the requested
number of genuinely distinct content concepts.

Each candidate MUST:
- synthesize across ALL supplied research, never mirror one source;
- state a distinct original angle and why it differs from the sources;
- target the specified audience and a concrete user need;
- stay strictly inside the supplied facts and context;
- respect the locale and market;
- use only the allowed content types;
- provide practical planning value (theme/budget/steps where relevant);
- honor the listed exclusions.

Each candidate MUST NOT:
- translate or paraphrase a single source article or its title;
- copy any source outline or structure;
- claim firsthand or personal experience;
- invent user reviews, ratings, testimonials, or community feedback;
- invent statistics, quotes, or trends not present in the supplied evidence;
- treat this output as factual evidence — it is a proposal only.

Propose the idea only. Do not write the article.
"""


@dataclass(frozen=True, slots=True)
class IdeaGenerationResult:
    """Typed engine outcome; failures keep their durable attempt row."""

    attempt: AiGenerationAttempt
    status: GenerationStatus
    ideas: list[Idea]
    attempt_created: bool
    ideas_created: bool


class IdeaGenerationEngine:
    """Transport-neutral engine; flushes only — the caller commits."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._opportunities = OpportunityRepository(session)
        self._ideas = IdeaRepository(session)
        self._generation = StructuredGenerationService(session)

    def generate_candidates(
        self,
        opportunity_id: uuid.UUID,
        *,
        provider: StructuredGenerationProvider,
        candidate_count: int = 3,
        policy: IdeaOriginalityPolicy = DEFAULT_IDEA_ORIGINALITY_POLICY,
        retry_number: int = 0,
    ) -> IdeaGenerationResult:
        opportunity = self._opportunities.get_by_id(opportunity_id)
        if opportunity is None:
            raise OpportunityNotFoundError(f"no opportunity with id {opportunity_id}")
        if opportunity.disposition is not OpportunityDisposition.COMMISSIONED:
            raise OpportunityNotCommissionedError(
                "idea generation is an operator command on a COMMISSIONED "
                f"opportunity; this one is {opportunity.disposition.value}"
            )
        if (
            not isinstance(candidate_count, int)
            or isinstance(candidate_count, bool)
            or not MIN_CANDIDATES <= candidate_count <= MAX_CANDIDATES
        ):
            raise InvalidIdeaInputError(
                f"candidate_count must be between {MIN_CANDIDATES} and {MAX_CANDIDATES}"
            )
        work_item = self._session.get(EditorialWorkItem, opportunity.work_item_id)
        if work_item is None:  # pragma: no cover - RESTRICT FK guarantees this
            raise OpportunityNotFoundError("opportunity has no resolvable work item")

        request = self._build_request(opportunity, work_item, candidate_count, policy, retry_number)
        spec: StructuredOutputSpec[IdeaCandidateBatchV1] = StructuredOutputSpec(
            schema_name=IDEA_CANDIDATE_SCHEMA_NAME,
            schema_version=IDEA_CANDIDATE_SCHEMA_VERSION,
            model_type=IdeaCandidateBatchV1,
            domain_validator=_batch_domain_validator(candidate_count, policy),
        )
        execution = self._generation.execute(request, spec, provider)

        if execution.status is not GenerationStatus.SUCCEEDED:
            return IdeaGenerationResult(
                attempt=execution.attempt,
                status=execution.status,
                ideas=[],
                attempt_created=execution.created,
                ideas_created=False,
            )
        if execution.created:
            assert execution.payload is not None
            ideas = self._materialize(
                execution.attempt, opportunity, work_item, execution.payload, policy
            )
            return IdeaGenerationResult(
                attempt=execution.attempt,
                status=execution.status,
                ideas=ideas,
                attempt_created=True,
                ideas_created=True,
            )
        return self._resolve_reused_attempt(execution, opportunity)

    # --- internal -----------------------------------------------------------

    def _resolve_reused_attempt(
        self,
        execution: GenerationExecution[IdeaCandidateBatchV1],
        opportunity: EditorialOpportunity,
    ) -> IdeaGenerationResult:
        attempt = execution.attempt
        _validate_attempt_for_opportunity(attempt, opportunity.id)
        # Serialize materialization on the attempt row (a read lock — the
        # append-only trigger stays untouched) so a concurrent winner's
        # batch becomes visible before we decide anything.
        self._session.execute(
            select(AiGenerationAttempt.id)
            .where(AiGenerationAttempt.id == attempt.id)
            .with_for_update()
        )
        ideas = self._ideas.list_by_generation_attempt(attempt.id)
        if ideas:
            return IdeaGenerationResult(
                attempt=attempt,
                status=attempt.status,
                ideas=ideas,
                attempt_created=False,
                ideas_created=False,
            )
        raise IncompleteMaterializationError(
            "this SUCCEEDED attempt has no materialized ideas and its raw "
            "output was (by design) never persisted; request a new provider "
            "invocation explicitly with retry_number + 1"
        )

    def _materialize(
        self,
        attempt: AiGenerationAttempt,
        opportunity: EditorialOpportunity,
        work_item: EditorialWorkItem,
        batch: IdeaCandidateBatchV1,
        policy: IdeaOriginalityPolicy,
    ) -> list[Idea]:
        """Atomically persist the whole validated batch (all or nothing)."""
        _validate_attempt_for_opportunity(attempt, opportunity.id)
        input_titles, distinct_sources = originality_inputs_for_opportunity(
            self._session, opportunity.id
        )
        ideas: list[Idea] = []
        with self._session.begin_nested():
            for candidate in batch.candidates:
                evaluation = evaluate_originality(
                    working_title=candidate.working_title,
                    input_titles=input_titles,
                    distinct_source_count=distinct_sources,
                    policy=policy,
                )
                idea = Idea(
                    logical_idea_id=uuid.uuid4(),
                    opportunity_id=opportunity.id,
                    version=1,
                    working_title=_normalized(candidate.working_title),
                    angle=_normalized(candidate.angle),
                    audience=_normalized(candidate.audience),
                    value_proposition=_normalized(candidate.value_proposition),
                    content_type=candidate.content_type,
                    locale=work_item.locale,
                    market=work_item.market,
                    rationale=_normalized(candidate.rationale),
                    exclusions=validate_exclusions(candidate.exclusions),
                    planning_dimensions=validate_planning_dimensions(
                        candidate.planning_dimensions.to_dimensions()
                    ),
                    originality_status=evaluation.status,
                    originality_detail=evaluation.detail,
                    originality_policy_snapshot=policy.snapshot(),
                    origin=IdeaOrigin.MODEL_ASSISTED,
                    generation_attempt_id=attempt.id,
                )
                self._session.add(idea)
                ideas.append(idea)
            self._session.flush()
        return ideas

    def _build_request(
        self,
        opportunity: EditorialOpportunity,
        work_item: EditorialWorkItem,
        candidate_count: int,
        policy: IdeaOriginalityPolicy,
        retry_number: int,
    ) -> GenerationRequest:
        inputs = self._opportunities.list_research_inputs(opportunity.id)
        projected_inputs = inputs[:MAX_PROJECTED_INPUTS]
        document_entries: list[dict[str, object]] = []
        document_ids: list[str] = []
        duplicate_decision_ids: list[str] = []
        source_labels: dict[uuid.UUID, str] = {}
        source_context: list[dict[str, object]] = []
        for research_input in projected_inputs:
            document = self._session.get(NormalizedDocument, research_input.normalized_document_id)
            if document is None:  # pragma: no cover - RESTRICT FK guarantees this
                continue
            document_ids.append(str(document.id))
            duplicate_decision_ids.append(str(research_input.duplicate_decision_id))
            source = self._resolve_source(document)
            if source is not None and source.id not in source_labels:
                source_labels[source.id] = f"kaynak-{len(source_labels) + 1}"
                source_context.append(
                    {
                        "label": source_labels[source.id],
                        "trust_tier": source.trust_tier.value,
                    }
                )
            document_entries.append(
                {
                    "document_id": str(document.id),
                    "title": document.title,
                    "role": research_input.role.value,
                    "source": source_labels.get(source.id) if source is not None else None,
                }
            )

        evidence_rows = list(
            self._session.execute(
                select(ResearchEvidence)
                .where(
                    ResearchEvidence.normalized_document_id.in_(
                        [uuid.UUID(document_id) for document_id in document_ids]
                    )
                )
                .order_by(ResearchEvidence.extracted_at, ResearchEvidence.id)
            ).scalars()
        )
        # RETRACTED evidence is deterministically excluded and counted.
        usable = [
            row
            for row in evidence_rows
            if row.verification_status is not VerificationStatus.RETRACTED
        ]
        excluded_retracted = len(evidence_rows) - len(usable)
        projected_evidence = usable[:MAX_PROJECTED_EVIDENCE]
        evidence_entries = [
            {
                "evidence_id": str(row.id),
                "statement": row.statement[:MAX_EVIDENCE_STATEMENT_CHARS],
                "type": row.evidence_type.value,
                "verification_status": row.verification_status.value,
                "document_id": str(row.normalized_document_id),
            }
            for row in projected_evidence
        ]

        score = self._opportunities.get_effective_score(opportunity.id)
        score_summary = (
            {
                "band": score.overall_band.value,
                "eligibility": score.eligibility.value,
            }
            if score is not None
            else None
        )

        input_refs = {
            "schema": GENERATION_INPUT_REFS_SCHEMA,
            "opportunity_id": str(opportunity.id),
            "work_item_id": str(opportunity.work_item_id),
            "generator_name": IDEA_GENERATOR_NAME,
            "generator_version": IDEA_GENERATOR_VERSION,
            "candidate_count": candidate_count,
            "research_input_ids": [str(entry.id) for entry in projected_inputs],
            "normalized_document_ids": document_ids,
            "research_evidence_ids": [entry["evidence_id"] for entry in evidence_entries],
            "duplicate_decision_ids": duplicate_decision_ids,
            "opportunity_score_id": str(score.id) if score is not None else None,
            "originality_policy_name": policy.name,
            "originality_policy_version": policy.version,
        }
        input_projection = {
            "topic_summary": opportunity.topic_summary,
            "locale": work_item.locale,
            "market": work_item.market,
            "documents": document_entries,
            "sources": source_context,
            "distinct_source_count": len(source_labels),
            "evidence": evidence_entries,
            "excluded_retracted_evidence": excluded_retracted,
            "duplicate_context": {
                "update_of_reference": opportunity.update_of_reference,
            },
            "score_summary": score_summary,
            "allowed_content_types": [content_type.value for content_type in ContentType],
            "originality_policy": {
                "min_distinct_sources": policy.min_distinct_sources,
                "title_similarity_failure_threshold": (policy.title_similarity_failure_threshold),
            },
            "candidate_count": candidate_count,
        }
        return GenerationRequest(
            purpose=GenerationPurpose.IDEA_CANDIDATES,
            schema_name=IDEA_CANDIDATE_SCHEMA_NAME,
            schema_version=IDEA_CANDIDATE_SCHEMA_VERSION,
            template_name=IDEA_TEMPLATE_NAME,
            template_version=IDEA_TEMPLATE_VERSION,
            input_refs=input_refs,
            input_projection=input_projection,
            generation_bounds={
                "candidate_count": candidate_count,
                "max_output_tokens": MAX_OUTPUT_TOKENS,
            },
            retry_number=retry_number,
            instructions=_TEMPLATE_V1,
        )

    def _resolve_source(self, document: NormalizedDocument) -> Source | None:
        snapshot = self._session.get(FetchSnapshot, document.fetch_snapshot_id)
        if snapshot is None:  # pragma: no cover - RESTRICT FK guarantees this
            return None
        item = self._session.get(DiscoveryItem, snapshot.discovery_item_id)
        if item is None:  # pragma: no cover - RESTRICT FK guarantees this
            return None
        return self._session.get(Source, item.source_id)


def _validate_attempt_for_opportunity(
    attempt: AiGenerationAttempt, opportunity_id: uuid.UUID
) -> None:
    """Never trust the FK or the caller: revalidate the durable attempt."""
    if attempt.purpose is not GenerationPurpose.IDEA_CANDIDATES:
        raise InvalidGenerationAttemptError(
            f"attempt purpose {attempt.purpose.value!r} cannot back idea candidates"
        )
    if attempt.status is not GenerationStatus.SUCCEEDED:
        raise InvalidGenerationAttemptError(
            f"only a SUCCEEDED attempt can back ideas (got {attempt.status.value!r})"
        )
    refs = attempt.input_refs
    if (
        refs.get("schema") != GENERATION_INPUT_REFS_SCHEMA
        or refs.get("opportunity_id") != str(opportunity_id)
        or refs.get("generator_name") != IDEA_GENERATOR_NAME
    ):
        raise InvalidGenerationAttemptError(
            "the attempt's persisted input provenance does not match this "
            "opportunity/generator context"
        )


def _batch_domain_validator(
    candidate_count: int, policy: IdeaOriginalityPolicy
) -> "_BatchValidator":
    return _BatchValidator(candidate_count=candidate_count, policy=policy)


@dataclass(frozen=True, slots=True)
class _BatchValidator:
    """Deterministic batch-wide domain validation (Task-8 hook).

    Rejects the WHOLE batch (attempt VALIDATION_FAILED, zero artifacts) for
    hard no-artifact violations: wrong candidate count, exact duplicate
    candidates, fake-UGC claims, or structurally invalid bounded fields.
    Ordinary originality assessment (near-copy titles, source diversity) is
    deliberately NOT here — it is recorded per persisted idea, exactly as
    in the operator path.
    """

    candidate_count: int
    policy: IdeaOriginalityPolicy

    def __call__(self, batch: IdeaCandidateBatchV1) -> str | None:
        if len(batch.candidates) != self.candidate_count:
            return "candidate_count_mismatch"
        seen: set[str] = set()
        for candidate in batch.candidates:
            fingerprint = json.dumps(
                candidate.model_dump(mode="json"), sort_keys=True, ensure_ascii=False
            )
            if fingerprint in seen:
                return "duplicate_candidates"
            seen.add(fingerprint)
            violations = find_fake_ugc_violations(
                {
                    "working_title": candidate.working_title,
                    "angle": candidate.angle,
                    "audience": candidate.audience,
                    "value_proposition": candidate.value_proposition,
                    "rationale": candidate.rationale,
                },
                self.policy,
            )
            if violations:
                return "fake_ugc"
            try:
                validate_exclusions(candidate.exclusions)
                validate_planning_dimensions(candidate.planning_dimensions.to_dimensions())
            except InvalidIdeaInputError:
                return "invalid_candidate_fields"
        return None


def _normalized(value: str) -> str:
    return " ".join(value.split())
