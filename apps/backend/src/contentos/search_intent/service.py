"""Search-intent composition: deterministic path + optional AI synthesis.

Two EXPLICIT surfaces — callers always know which they request:

- ``compose_deterministic``: fully usable without AI; the semantic intent
  fields arrive through the typed ``IntentComposition`` DTO (no hidden
  heuristic pretends to infer intent from sparse signals);
- ``synthesize``: optional model assistance through the provider-neutral
  boundary (purpose INTENT_SYNTHESIS); the model proposes ONLY semantic
  fields — every system-owned fact stays deterministic.

Shared invariants: the analysis pins the EXACT currently selected idea
version; SearchSignals are consumed by exact observation id only (no
implicit latest) and are frozen into `known_signal_refs`; missing signals
are durable data (UNKNOWN never becomes zero); cannibalization defaults to
NOT_CHECKED and internal states require the exact references examined;
KNOWN_CONFLICT is refused (no published-inventory contract exists);
locale/market derive from the parent work item. Creating an analysis never
touches workflow, disposition, selection, signals, packs, or evidence.

The service flushes; the caller commits.
"""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from contentos.ai.dto import GenerationRequest
from contentos.ai.enums import GenerationPurpose, GenerationStatus
from contentos.ai.hashing import sha256_hex
from contentos.ai.models import AiGenerationAttempt
from contentos.ai.protocol import StructuredGenerationProvider
from contentos.ai.service import StructuredGenerationService
from contentos.ai.validation import StructuredOutputSpec
from contentos.ideas.models import Idea
from contentos.ideas.repository import IdeaRepository
from contentos.ideas.service import IdeaService
from contentos.opportunities.errors import OpportunityNotFoundError
from contentos.opportunities.models import EditorialOpportunity
from contentos.opportunities.repository import OpportunityRepository
from contentos.search_intent.enums import CannibalizationStatus
from contentos.search_intent.errors import (
    AnalysisConflictError,
    IdeaNotSelectedError,
    IncompleteAnalysisMaterializationError,
    InvalidAnalysisInputError,
    InvalidSynthesisAttemptError,
    SignalNotEligibleError,
)
from contentos.search_intent.generation_schemas import (
    SEARCH_INTENT_SYNTHESIS_SCHEMA_NAME,
    SEARCH_INTENT_SYNTHESIS_SCHEMA_VERSION,
    SearchIntentSynthesisV1,
)
from contentos.search_intent.models import SearchIntentAnalysis
from contentos.search_intent.repository import SearchIntentRepository
from contentos.search_intent.values import (
    MAX_INTENT_LENGTH,
    MAX_QUERY_CONCEPT_LENGTH,
    MAX_QUERY_CONCEPTS,
    MAX_SECONDARY_INTENTS,
    NOT_CHECKED_INPUT,
    CannibalizationInput,
    IntentComposition,
    InternalReference,
    build_cannibalization_basis,
    validate_related_references,
    validate_semantic_list,
)
from contentos.signals.enums import SearchSignalType
from contentos.signals.models import SearchSignal
from contentos.workflow.models import EditorialWorkItem

SEARCH_INTENT_ENGINE_NAME = "search-intent-analyzer"
SEARCH_INTENT_ENGINE_VERSION = "1"
SEARCH_INTENT_INPUT_SCHEMA_VERSION = 1
SEARCH_INTENT_TEMPLATE_NAME = "search-intent-synthesis"
SEARCH_INTENT_TEMPLATE_VERSION = "1"
SYNTHESIS_INPUT_REFS_SCHEMA = "search-intent-synthesis/1"

MAX_SIGNALS = 50
MAX_SYNTHESIS_OUTPUT_TOKENS = 4_000

# Versioned by SEARCH_INTENT_TEMPLATE_NAME/VERSION; substantive changes
# REQUIRE a version bump (instructions are never hashed or persisted).
_TEMPLATE_V1 = """\
You synthesize the SEARCH INTENT for one Konsepthane editorial concept from
the supplied context ONLY (the selected idea, exact recorded search-signal
observations, and the explicit missing-signal list).

You MUST:
- synthesize only from the supplied context;
- treat query concepts as editorial/search CONCEPTS, never measured demand;
- respect the locale and market;
- output only the requested structured semantic fields.

You MUST NOT:
- invent search volume, trend direction, ranking positions, or SERP
  observations;
- invent keyword difficulty, CPC, or competition metrics;
- invent competitor or site inventory;
- claim any site-wide cannibalization status;
- write the content itself.
"""


@dataclass(frozen=True, slots=True)
class DeterministicAnalysisResult:
    analysis: SearchIntentAnalysis
    created: bool


@dataclass(frozen=True, slots=True)
class SynthesisResult:
    """AI path outcome; failed attempts stay durable with no analysis."""

    attempt: AiGenerationAttempt
    status: GenerationStatus
    analysis: SearchIntentAnalysis | None
    attempt_created: bool
    analysis_created: bool


@dataclass(frozen=True, slots=True)
class _AnalysisContext:
    opportunity: EditorialOpportunity
    work_item: EditorialWorkItem
    idea: Idea
    signal_snapshots: list[dict[str, Any]]
    missing_signals: list[str]
    cannibalization_status: CannibalizationStatus
    cannibalization_basis: dict[str, Any]
    related_references: list[dict[str, str]]


class SearchIntentService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repository = SearchIntentRepository(session)
        self._opportunities = OpportunityRepository(session)
        self._ideas = IdeaRepository(session)
        self._generation = StructuredGenerationService(session)

    # --- deterministic path -------------------------------------------------

    def compose_deterministic(
        self,
        opportunity_id: uuid.UUID,
        *,
        idea_id: uuid.UUID,
        composition: IntentComposition,
        signal_ids: list[uuid.UUID] | None = None,
        cannibalization: CannibalizationInput = NOT_CHECKED_INPUT,
        related_references: list[InternalReference] | None = None,
    ) -> DeterministicAnalysisResult:
        context = self._resolve_context(
            opportunity_id, idea_id, signal_ids or [], cannibalization, related_references
        )
        semantic = composition.cleaned()
        snapshot = self._input_snapshot(
            context, mode="deterministic", composition=semantic, attempt_identity=None
        )
        snapshot_hash = sha256_hex(snapshot)
        existing = self._repository.get_by_identity(
            opportunity_id,
            SEARCH_INTENT_ENGINE_NAME,
            SEARCH_INTENT_ENGINE_VERSION,
            snapshot_hash,
        )
        if existing is not None:
            return DeterministicAnalysisResult(analysis=existing, created=False)
        analysis = self._persist(context, semantic, snapshot, snapshot_hash, None)
        return DeterministicAnalysisResult(analysis=analysis, created=True)

    # --- optional model-assisted path ---------------------------------------

    def synthesize(
        self,
        opportunity_id: uuid.UUID,
        *,
        idea_id: uuid.UUID,
        provider: StructuredGenerationProvider,
        signal_ids: list[uuid.UUID] | None = None,
        cannibalization: CannibalizationInput = NOT_CHECKED_INPUT,
        related_references: list[InternalReference] | None = None,
        retry_number: int = 0,
    ) -> SynthesisResult:
        context = self._resolve_context(
            opportunity_id, idea_id, signal_ids or [], cannibalization, related_references
        )
        request = self._build_synthesis_request(context, retry_number)
        spec: StructuredOutputSpec[SearchIntentSynthesisV1] = StructuredOutputSpec(
            schema_name=SEARCH_INTENT_SYNTHESIS_SCHEMA_NAME,
            schema_version=SEARCH_INTENT_SYNTHESIS_SCHEMA_VERSION,
            model_type=SearchIntentSynthesisV1,
            domain_validator=_synthesis_domain_validator,
        )
        execution = self._generation.execute(request, spec, provider)

        if execution.status is not GenerationStatus.SUCCEEDED:
            return SynthesisResult(
                attempt=execution.attempt,
                status=execution.status,
                analysis=None,
                attempt_created=execution.created,
                analysis_created=False,
            )
        if execution.created:
            assert execution.payload is not None
            semantic = _semantic_from_payload(execution.payload)
            snapshot = self._input_snapshot(
                context,
                mode="model_assisted",
                composition=None,
                attempt_identity=execution.attempt.attempt_identity_hash,
            )
            analysis = self._persist(
                context, semantic, snapshot, sha256_hex(snapshot), execution.attempt
            )
            return SynthesisResult(
                attempt=execution.attempt,
                status=execution.status,
                analysis=analysis,
                attempt_created=True,
                analysis_created=True,
            )
        return self._resolve_reused_attempt(execution.attempt, context)

    # --- internal -----------------------------------------------------------

    def _resolve_reused_attempt(
        self, attempt: AiGenerationAttempt, context: _AnalysisContext
    ) -> SynthesisResult:
        _validate_synthesis_attempt(attempt, context.opportunity.id, context.idea.id)
        # Serialize materialization on the attempt row (read lock only).
        self._session.execute(
            select(AiGenerationAttempt.id)
            .where(AiGenerationAttempt.id == attempt.id)
            .with_for_update()
        )
        analysis = self._repository.get_by_synthesis_attempt(attempt.id)
        if analysis is not None:
            return SynthesisResult(
                attempt=attempt,
                status=attempt.status,
                analysis=analysis,
                attempt_created=False,
                analysis_created=False,
            )
        raise IncompleteAnalysisMaterializationError(
            "this SUCCEEDED synthesis attempt has no materialized analysis "
            "and its raw output was (by design) never persisted; request a "
            "new provider invocation explicitly with retry_number + 1"
        )

    def _persist(
        self,
        context: _AnalysisContext,
        semantic: dict[str, Any],
        snapshot: dict[str, Any],
        snapshot_hash: str,
        attempt: AiGenerationAttempt | None,
    ) -> SearchIntentAnalysis:
        if attempt is not None:
            _validate_synthesis_attempt(attempt, context.opportunity.id, context.idea.id)
        try:
            with self._session.begin_nested():
                self._repository.lock_opportunity(context.opportunity.id)
                analysis = self._repository.add(
                    SearchIntentAnalysis(
                        opportunity_id=context.opportunity.id,
                        idea_id=context.idea.id,
                        version=self._repository.next_version(context.opportunity.id),
                        primary_intent=semantic["primary_intent"],
                        secondary_intents=semantic["secondary_intents"],
                        target_audience=context.idea.audience,
                        query_concepts=semantic["query_concepts"],
                        page_purpose=semantic["page_purpose"],
                        likely_format=semantic["likely_format"],
                        known_signal_refs=context.signal_snapshots,
                        missing_signals=context.missing_signals,
                        cannibalization_status=context.cannibalization_status,
                        cannibalization_basis=context.cannibalization_basis,
                        related_references=context.related_references,
                        locale=context.work_item.locale,
                        market=context.work_item.market,
                        engine_name=SEARCH_INTENT_ENGINE_NAME,
                        engine_version=SEARCH_INTENT_ENGINE_VERSION,
                        synthesis_attempt_id=attempt.id if attempt is not None else None,
                        input_snapshot=snapshot,
                        input_snapshot_hash=snapshot_hash,
                    )
                )
        except IntegrityError:
            winner = self._repository.get_by_identity(
                context.opportunity.id,
                SEARCH_INTENT_ENGINE_NAME,
                SEARCH_INTENT_ENGINE_VERSION,
                snapshot_hash,
            )
            if winner is not None:
                return winner
            raise AnalysisConflictError(
                "analysis persistence conflicted with concurrently written state"
            ) from None
        return analysis

    def _resolve_context(
        self,
        opportunity_id: uuid.UUID,
        idea_id: uuid.UUID,
        signal_ids: list[uuid.UUID],
        cannibalization: CannibalizationInput,
        related_references: list[InternalReference] | None,
    ) -> _AnalysisContext:
        opportunity = self._opportunities.get_by_id(opportunity_id)
        if opportunity is None:
            raise OpportunityNotFoundError(f"no opportunity with id {opportunity_id}")
        work_item = self._session.get(EditorialWorkItem, opportunity.work_item_id)
        if work_item is None:  # pragma: no cover - RESTRICT FK guarantees this
            raise OpportunityNotFoundError("opportunity has no resolvable work item")

        # The analysis pins the EXACT currently selected idea version.
        effective = IdeaService(self._session).get_effective_selection(opportunity_id)
        if effective is None:
            raise IdeaNotSelectedError("no idea is currently selected for this opportunity")
        if effective.id != idea_id:
            raise IdeaNotSelectedError(
                "the supplied idea is not the current effective selection "
                f"(effective: {effective.id})"
            )
        idea = effective

        signal_snapshots, missing = self._resolve_signals(signal_ids, work_item)
        basis = build_cannibalization_basis(cannibalization)
        return _AnalysisContext(
            opportunity=opportunity,
            work_item=work_item,
            idea=idea,
            signal_snapshots=signal_snapshots,
            missing_signals=missing,
            cannibalization_status=cannibalization.status,
            cannibalization_basis=basis,
            related_references=self._validated_related(related_references),
        )

    def _resolve_signals(
        self, signal_ids: list[uuid.UUID], work_item: EditorialWorkItem
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Exact observation consumption: no implicit latest, ever."""
        if len(signal_ids) > MAX_SIGNALS:
            raise InvalidAnalysisInputError("too many signals selected")
        if len(set(signal_ids)) != len(signal_ids):
            raise InvalidAnalysisInputError("the same signal cannot be selected twice")
        snapshots: list[dict[str, Any]] = []
        provided_types: set[SearchSignalType] = set()
        for signal_id in signal_ids:
            signal = self._session.get(SearchSignal, signal_id)
            if signal is None:
                raise SignalNotEligibleError(f"no search signal with id {signal_id}")
            if signal.locale != work_item.locale or signal.market != work_item.market:
                raise SignalNotEligibleError(
                    "signal locale/market does not match the analysis context "
                    f"({signal.locale}/{signal.market} vs "
                    f"{work_item.locale}/{work_item.market})"
                )
            provided_types.add(signal.signal_type)
            snapshots.append(
                {
                    "signal_id": str(signal.id),
                    "signal_type": signal.signal_type.value,
                    "subject": signal.subject,
                    "provider": signal.provider,
                    # The exact canonical value, frozen; QUERY_SET internal
                    # order is semantic and preserved as stored.
                    "value": signal.value,
                    "confidence": signal.confidence,
                    "observed_at": signal.observed_at.isoformat(),
                    "as_of": signal.as_of.isoformat() if signal.as_of is not None else None,
                }
            )
        # Deterministic snapshot order: exact observation identity.
        snapshots.sort(key=lambda entry: entry["signal_id"])
        # UNKNOWN != ZERO: what was not supplied is durably named missing.
        missing = sorted(
            signal_type.value
            for signal_type in SearchSignalType
            if signal_type not in provided_types
        )
        return snapshots, missing

    def _validated_related(
        self, references: list[InternalReference] | None
    ) -> list[dict[str, str]]:
        persisted = validate_related_references(references)
        for entry in persisted:
            self._require_reference_exists(entry["kind"], uuid.UUID(entry["id"]))
        return persisted

    def _require_reference_exists(self, kind: str, reference_id: uuid.UUID) -> None:
        model = {
            "opportunity": EditorialOpportunity,
            "work_item": EditorialWorkItem,
            "idea": Idea,
            "analysis": SearchIntentAnalysis,
        }[kind]
        if self._session.get(model, reference_id) is None:
            raise InvalidAnalysisInputError(f"referenced {kind} {reference_id} does not exist")

    def _input_snapshot(
        self,
        context: _AnalysisContext,
        *,
        mode: str,
        composition: dict[str, Any] | None,
        attempt_identity: str | None,
    ) -> dict[str, Any]:
        """The WHOLE semantic analysis identity (stored for reproducibility)."""
        return {
            "schema": SEARCH_INTENT_INPUT_SCHEMA_VERSION,
            "engine_name": SEARCH_INTENT_ENGINE_NAME,
            "engine_version": SEARCH_INTENT_ENGINE_VERSION,
            "opportunity_id": str(context.opportunity.id),
            "idea_id": str(context.idea.id),
            "composition_mode": mode,
            "composition": composition,
            "synthesis_attempt_identity_hash": attempt_identity,
            "signals": context.signal_snapshots,
            "missing_signals": context.missing_signals,
            "cannibalization_status": context.cannibalization_status.value,
            "cannibalization_basis": context.cannibalization_basis,
            "related_references": context.related_references,
        }

    def _build_synthesis_request(
        self, context: _AnalysisContext, retry_number: int
    ) -> GenerationRequest:
        idea = context.idea
        input_refs = {
            "schema": SYNTHESIS_INPUT_REFS_SCHEMA,
            "opportunity_id": str(context.opportunity.id),
            "work_item_id": str(context.opportunity.work_item_id),
            "idea_id": str(idea.id),
            "signal_ids": [entry["signal_id"] for entry in context.signal_snapshots],
            "analyzer_name": SEARCH_INTENT_ENGINE_NAME,
            "analyzer_version": SEARCH_INTENT_ENGINE_VERSION,
            "cannibalization_status": context.cannibalization_status.value,
            "cannibalization_checked_references": [
                f"{entry['kind']}:{entry['id']}"
                for entry in context.cannibalization_basis.get("checked_references", [])
            ],
            "related_references": [
                f"{entry['kind']}:{entry['id']}" for entry in context.related_references
            ],
        }
        input_projection = {
            "idea": {
                "working_title": idea.working_title,
                "angle": idea.angle,
                "audience": idea.audience,
                "value_proposition": idea.value_proposition,
                "content_type": idea.content_type.value,
                "exclusions": idea.exclusions,
                "planning_dimensions": idea.planning_dimensions,
            },
            "locale": context.work_item.locale,
            "market": context.work_item.market,
            "signals": context.signal_snapshots,
            "missing_signals": context.missing_signals,
            "cannibalization_scope_note": (
                "published inventory is not accessible; overlap knowledge is "
                "ContentOS-internal only"
            ),
            "related_references": context.related_references,
        }
        return GenerationRequest(
            purpose=GenerationPurpose.INTENT_SYNTHESIS,
            schema_name=SEARCH_INTENT_SYNTHESIS_SCHEMA_NAME,
            schema_version=SEARCH_INTENT_SYNTHESIS_SCHEMA_VERSION,
            template_name=SEARCH_INTENT_TEMPLATE_NAME,
            template_version=SEARCH_INTENT_TEMPLATE_VERSION,
            input_refs=input_refs,
            input_projection=input_projection,
            generation_bounds={"max_output_tokens": MAX_SYNTHESIS_OUTPUT_TOKENS},
            retry_number=retry_number,
            instructions=_TEMPLATE_V1,
        )


def _semantic_from_payload(payload: SearchIntentSynthesisV1) -> dict[str, Any]:
    """Normalize the schema-valid model proposal into persisted fields."""
    return {
        "primary_intent": " ".join(payload.primary_intent.split()),
        "secondary_intents": validate_semantic_list(
            "secondary_intents",
            payload.secondary_intents,
            max_items=MAX_SECONDARY_INTENTS,
            max_length=MAX_INTENT_LENGTH,
        ),
        "query_concepts": validate_semantic_list(
            "query_concepts",
            payload.query_concepts,
            max_items=MAX_QUERY_CONCEPTS,
            max_length=MAX_QUERY_CONCEPT_LENGTH,
        ),
        "page_purpose": " ".join(payload.page_purpose.split()),
        "likely_format": " ".join(payload.likely_format.split()),
    }


def _synthesis_domain_validator(payload: SearchIntentSynthesisV1) -> str | None:
    """Deterministic batch rejection for domain-invalid synthesis output.

    Duplicate/blank entries reject the whole attempt. No regex pretends to
    detect every hallucinated metric — the schema bounds plus the template
    prohibitions are the honest deterministic protections here.
    """
    try:
        _semantic_from_payload(payload)
    except InvalidAnalysisInputError:
        return "invalid_semantic_fields"
    return None


def _validate_synthesis_attempt(
    attempt: AiGenerationAttempt, opportunity_id: uuid.UUID, idea_id: uuid.UUID
) -> None:
    """Never trust the FK or the caller: revalidate the durable attempt."""
    if attempt.purpose is not GenerationPurpose.INTENT_SYNTHESIS:
        raise InvalidSynthesisAttemptError(
            f"attempt purpose {attempt.purpose.value!r} cannot back a search-intent analysis"
        )
    if attempt.status is not GenerationStatus.SUCCEEDED:
        raise InvalidSynthesisAttemptError(
            f"only a SUCCEEDED attempt can back an analysis (got {attempt.status.value!r})"
        )
    refs = attempt.input_refs
    if (
        refs.get("schema") != SYNTHESIS_INPUT_REFS_SCHEMA
        or refs.get("opportunity_id") != str(opportunity_id)
        or refs.get("idea_id") != str(idea_id)
    ):
        raise InvalidSynthesisAttemptError(
            "the attempt's persisted input provenance does not match this opportunity/idea context"
        )
