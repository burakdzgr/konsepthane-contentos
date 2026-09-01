"""Deterministic evidence-pack assembly, contradictions, and sufficiency.

Assembler identity: ``evidence-pack-assembler`` / ``1``. Membership and
provenance are fully deterministic: the caller explicitly selects evidence
units (by ResearchEvidence id) that must trace to the opportunity's admitted
research inputs; nothing is summarized, invented, or copied.

Reproducibility contract (authoritative, immutable):

- a pack version's persisted ``sufficiency`` + ``sufficiency_detail`` are
  its gate meaning FOREVER — "pack X/version N was READY" never changes;
- contradictions are declared as assembly inputs (or added at reassembly);
  their canonical definitions and resolution states participate in the
  semantic assembly identity;
- resolving a contradiction is an audited mutation of the contradiction row
  only — it NEVER retroactively changes its pack's sufficiency; an explicit
  ``reassemble_pack`` produces a NEW version that carries the contradiction
  state forward into its own immutable rows and snapshot, so the new pack is
  independently explainable later.

Semantic assembly identity (DB-unique per opportunity + assembler):
SHA-256 over the canonical assembly input snapshot covering the selections
(evidence id, role, claim cluster), the FULL policy snapshot, canonical
contradiction state, and the optionally pinned exact idea version. Display
notes and handling recommendations are formally cosmetic/advisory — they
never affect sufficiency — and are the only inputs excluded.

The service flushes; the caller commits.
"""

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from contentos.discovery.models import DiscoveryItem
from contentos.evidence_packs.enums import (
    ContradictionResolutionStatus,
    ContradictionResolver,
    ContradictionSeverity,
    EvidenceItemRole,
    EvidencePackSufficiency,
)
from contentos.evidence_packs.errors import (
    ContradictionNotFoundError,
    EvidenceNotEligibleError,
    InvalidContradictionError,
    InvalidPackInputError,
    PackConflictError,
    PackNotFoundError,
)
from contentos.evidence_packs.models import (
    EvidenceContradiction,
    EvidencePack,
    EvidencePackItem,
)
from contentos.evidence_packs.policy import (
    DEFAULT_EVIDENCE_POLICY,
    EvidenceSufficiencyPolicy,
)
from contentos.evidence_packs.repository import EvidencePackRepository
from contentos.fetching.snapshots import FetchSnapshot
from contentos.ideas.models import Idea
from contentos.normalization.models import NormalizedDocument
from contentos.opportunities.errors import OpportunityNotFoundError
from contentos.opportunities.repository import OpportunityRepository
from contentos.research.models import ResearchEvidence
from contentos.sources.models import Source
from contentos.workflow.models import EditorialWorkItem

EVIDENCE_PACK_ASSEMBLER_NAME = "evidence-pack-assembler"
EVIDENCE_PACK_ASSEMBLER_VERSION = "1"

# Schema 2 added the pinned idea version to the semantic identity.
ASSEMBLY_INPUT_SCHEMA_VERSION = 2

MAX_SELECTIONS = 200
MAX_CLAIM_CLUSTER_LENGTH = 100
MAX_DISPLAY_NOTE_LENGTH = 1000
MAX_CLAIM_KEY_LENGTH = 100
MAX_NATURE_LENGTH = 1000
MAX_HANDLING_LENGTH = 1000
MAX_RESOLUTION_REASON_LENGTH = 1000
MAX_CONTRADICTION_SIDE_SIZE = 20
MAX_CONTRADICTIONS = 50


@dataclass(frozen=True, slots=True)
class EvidenceSelection:
    """One explicit caller selection; provenance stays the evidence row itself."""

    research_evidence_id: uuid.UUID
    role: EvidenceItemRole
    claim_cluster: str
    display_note: str | None = None


@dataclass(frozen=True, slots=True)
class ContradictionDeclaration:
    """One contradiction supplied as an assembly input (starts unresolved)."""

    claim_key: str
    evidence_side_a: tuple[uuid.UUID, ...]
    evidence_side_b: tuple[uuid.UUID, ...]
    nature: str
    severity: ContradictionSeverity
    handling_recommendation: str | None = None


@dataclass(frozen=True, slots=True)
class _ContradictionState:
    """Canonical semantic state of one contradiction at assembly time."""

    claim_key: str
    side_a: tuple[str, ...]
    side_b: tuple[str, ...]
    nature: str
    severity: ContradictionSeverity
    resolution_status: ContradictionResolutionStatus
    handling_recommendation: str | None
    resolution_reason: str | None
    resolved_by: ContradictionResolver | None
    resolved_at: datetime | None


@dataclass(frozen=True, slots=True)
class PackAssembly:
    """The durable pack; `created` is False on an idempotent retry."""

    pack: EvidencePack
    created: bool


@dataclass(frozen=True, slots=True)
class SufficiencyResult:
    sufficiency: EvidencePackSufficiency
    detail: dict[str, Any]


class EvidencePackService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repository = EvidencePackRepository(session)
        self._opportunities = OpportunityRepository(session)

    def list_eligible_evidence(self, opportunity_id: uuid.UUID) -> list[ResearchEvidence]:
        """All evidence tracing to the opportunity's admitted research inputs."""
        document_ids = self._input_document_ids(opportunity_id)
        statement = (
            select(ResearchEvidence)
            .where(ResearchEvidence.normalized_document_id.in_(document_ids))
            .order_by(ResearchEvidence.extracted_at, ResearchEvidence.id)
        )
        return list(self._session.execute(statement).scalars())

    def assemble_pack(
        self,
        opportunity_id: uuid.UUID,
        selections: list[EvidenceSelection],
        *,
        policy: EvidenceSufficiencyPolicy = DEFAULT_EVIDENCE_POLICY,
        contradictions: list[ContradictionDeclaration] | None = None,
        idea_id: uuid.UUID | None = None,
    ) -> PackAssembly:
        """Assemble a new pack version from explicit selections and inputs.

        `idea_id` optionally pins the EXACT idea version this pack is built
        for (it must belong to the same opportunity) and participates in the
        semantic assembly identity: the same evidence and policy with a
        different pinned idea is a different pack.
        """
        self._validate_idea(opportunity_id, idea_id)
        cleaned = _validate_selections(selections)
        selected_ids = {selection.research_evidence_id for selection in cleaned}
        states = _states_from_declarations(contradictions or [], selected_ids)

        document_ids = self._input_document_ids(opportunity_id)
        evidence_rows: dict[uuid.UUID, ResearchEvidence] = {}
        for selection in cleaned:
            evidence = self._session.get(ResearchEvidence, selection.research_evidence_id)
            if evidence is None:
                raise EvidenceNotEligibleError(
                    f"no research evidence with id {selection.research_evidence_id}"
                )
            if evidence.normalized_document_id not in document_ids:
                raise EvidenceNotEligibleError(
                    "selected evidence does not trace to the opportunity's research inputs"
                )
            evidence_rows[evidence.id] = evidence

        return self._persist_pack(opportunity_id, cleaned, states, policy, evidence_rows, idea_id)

    def reassemble_pack(
        self,
        pack_id: uuid.UUID,
        *,
        policy: EvidenceSufficiencyPolicy | None = None,
        additional_contradictions: list[ContradictionDeclaration] | None = None,
        idea_id: uuid.UUID | None = None,
        replace_idea: bool = False,
    ) -> PackAssembly:
        """Produce a NEW pack version reflecting current contradiction state.

        The old pack stays exactly as assembled (historically CONFLICTED
        stays CONFLICTED). The new version carries the source pack's
        contradiction definitions with their resolution state frozen at
        reassembly time into its OWN rows, plus any newly declared
        contradictions. The pinned idea version is carried forward unchanged
        unless the caller explicitly passes ``replace_idea=True`` (with the
        new ``idea_id``, or None to unpin). If nothing semantically changed,
        the identity hash matches and the existing version is returned
        instead.
        """
        old_pack = self._repository.get_pack(pack_id)
        if old_pack is None:
            raise PackNotFoundError(f"no evidence pack with id {pack_id}")
        if not replace_idea:
            if idea_id is not None:
                raise InvalidPackInputError(
                    "pass replace_idea=True to change the pinned idea version"
                )
            effective_idea_id = old_pack.idea_id
        else:
            effective_idea_id = idea_id
            self._validate_idea(old_pack.opportunity_id, effective_idea_id)
        resolved_policy = (
            policy
            if policy is not None
            else EvidenceSufficiencyPolicy.from_snapshot(old_pack.policy_snapshot)
        )

        items = self._repository.list_items(pack_id)
        selections = [
            EvidenceSelection(
                research_evidence_id=item.research_evidence_id,
                role=item.role,
                claim_cluster=item.claim_cluster,
                display_note=item.display_note,
            )
            for item in items
        ]
        selected_ids = {item.research_evidence_id for item in items}

        carried = [_state_from_row(row) for row in self._repository.list_contradictions(pack_id)]
        declared = _states_from_declarations(additional_contradictions or [], selected_ids)
        states = carried + declared

        evidence_rows: dict[uuid.UUID, ResearchEvidence] = {}
        for item in items:
            evidence = self._session.get(ResearchEvidence, item.research_evidence_id)
            if evidence is None:  # pragma: no cover - RESTRICT FK guarantees this
                raise EvidenceNotEligibleError("pack evidence is no longer resolvable")
            evidence_rows[evidence.id] = evidence

        return self._persist_pack(
            old_pack.opportunity_id,
            selections,
            states,
            resolved_policy,
            evidence_rows,
            effective_idea_id,
        )

    def resolve_contradiction(
        self,
        contradiction_id: uuid.UUID,
        *,
        resolution_status: ContradictionResolutionStatus,
        reason: str,
    ) -> EvidenceContradiction:
        """Audited operator resolution of one contradiction row.

        This NEVER changes any pack's stored sufficiency: the parent pack
        remains exactly what it was when assembled. Call ``reassemble_pack``
        to produce a new version reflecting the resolution.
        """
        contradiction = self._repository.get_contradiction(contradiction_id)
        if contradiction is None:
            raise ContradictionNotFoundError(f"no contradiction with id {contradiction_id}")
        if not isinstance(resolution_status, ContradictionResolutionStatus):
            raise InvalidContradictionError(
                "resolution_status must be a ContradictionResolutionStatus"
            )
        if resolution_status is ContradictionResolutionStatus.UNRESOLVED:
            raise InvalidContradictionError("a resolution cannot be 'unresolved'")
        if contradiction.resolution_status is not ContradictionResolutionStatus.UNRESOLVED:
            raise InvalidContradictionError(
                "the contradiction is already resolved; declare a new contradiction "
                "at reassembly if the disagreement persists"
            )
        cleaned_reason = _required_text("reason", reason, MAX_RESOLUTION_REASON_LENGTH)

        contradiction.resolution_status = resolution_status
        contradiction.resolution_reason = cleaned_reason
        contradiction.resolved_by = ContradictionResolver.OPERATOR
        contradiction.resolved_at = datetime.now(UTC)
        self._session.flush()
        return contradiction

    # --- internal -----------------------------------------------------------

    def _persist_pack(
        self,
        opportunity_id: uuid.UUID,
        selections: list[EvidenceSelection],
        states: list[_ContradictionState],
        policy: EvidenceSufficiencyPolicy,
        evidence_rows: dict[uuid.UUID, ResearchEvidence],
        idea_id: uuid.UUID | None,
    ) -> PackAssembly:
        assembly_snapshot = _assembly_input_snapshot(selections, states, policy, idea_id)
        assembly_hash = _assembly_input_hash(assembly_snapshot)
        existing = self._repository.get_pack_by_identity(
            opportunity_id,
            EVIDENCE_PACK_ASSEMBLER_NAME,
            EVIDENCE_PACK_ASSEMBLER_VERSION,
            assembly_hash,
        )
        if existing is not None:
            return PackAssembly(pack=existing, created=False)

        context = self._resolve_context(opportunity_id, evidence_rows, policy)
        sufficiency = _evaluate_sufficiency(
            role_counts=_role_counts(selections),
            item_count=len(selections),
            distinct_sources=len(context["source_tiers"]),
            states=states,
            policy=policy,
        )
        try:
            with self._session.begin_nested():
                pack = self._repository.insert_pack(
                    EvidencePack(
                        opportunity_id=opportunity_id,
                        idea_id=idea_id,
                        version=self._repository.next_version(opportunity_id),
                        assembler_name=EVIDENCE_PACK_ASSEMBLER_NAME,
                        assembler_version=EVIDENCE_PACK_ASSEMBLER_VERSION,
                        sufficiency=sufficiency.sufficiency,
                        sufficiency_detail=sufficiency.detail,
                        source_diversity=context["source_diversity"],
                        staleness_notes=context["staleness_notes"],
                        locale_limitations=context["locale_limitations"],
                        licensing_cautions=context["licensing_cautions"],
                        policy_snapshot=policy.snapshot(),
                        assembly_input_snapshot=assembly_snapshot,
                        assembly_input_hash=assembly_hash,
                    )
                )
                for selection in selections:
                    self._repository.insert_item(
                        EvidencePackItem(
                            pack_id=pack.id,
                            research_evidence_id=selection.research_evidence_id,
                            role=selection.role,
                            claim_cluster=selection.claim_cluster,
                            display_note=selection.display_note,
                        )
                    )
                for state in states:
                    self._repository.insert_contradiction(
                        EvidenceContradiction(
                            pack_id=pack.id,
                            claim_key=state.claim_key,
                            evidence_side_a=list(state.side_a),
                            evidence_side_b=list(state.side_b),
                            nature=state.nature,
                            severity=state.severity,
                            resolution_status=state.resolution_status,
                            handling_recommendation=state.handling_recommendation,
                            resolution_reason=state.resolution_reason,
                            resolved_by=state.resolved_by,
                            resolved_at=state.resolved_at,
                        )
                    )
        except IntegrityError:
            winner = self._repository.get_pack_by_identity(
                opportunity_id,
                EVIDENCE_PACK_ASSEMBLER_NAME,
                EVIDENCE_PACK_ASSEMBLER_VERSION,
                assembly_hash,
            )
            if winner is not None:
                return PackAssembly(pack=winner, created=False)
            raise PackConflictError(
                "pack assembly conflicted with concurrently written state"
            ) from None
        return PackAssembly(pack=pack, created=True)

    def _validate_idea(self, opportunity_id: uuid.UUID, idea_id: uuid.UUID | None) -> None:
        if idea_id is None:
            return
        idea = self._session.get(Idea, idea_id)
        if idea is None:
            raise InvalidPackInputError(f"no idea version with id {idea_id}")
        if idea.opportunity_id != opportunity_id:
            raise InvalidPackInputError(
                "the pinned idea version belongs to a different opportunity"
            )

    def _input_document_ids(self, opportunity_id: uuid.UUID) -> set[uuid.UUID]:
        opportunity = self._opportunities.get_by_id(opportunity_id)
        if opportunity is None:
            raise OpportunityNotFoundError(f"no opportunity with id {opportunity_id}")
        inputs = self._opportunities.list_research_inputs(opportunity_id)
        return {research_input.normalized_document_id for research_input in inputs}

    def _resolve_context(
        self,
        opportunity_id: uuid.UUID,
        evidence_rows: dict[uuid.UUID, ResearchEvidence],
        policy: EvidenceSufficiencyPolicy,
    ) -> dict[str, Any]:
        opportunity = self._opportunities.get_by_id(opportunity_id)
        assert opportunity is not None  # validated earlier
        work_item = self._session.get(EditorialWorkItem, opportunity.work_item_id)
        work_item_locale = work_item.locale if work_item is not None else None

        source_tiers: dict[str, str] = {}
        staleness_notes: list[dict[str, Any]] = []
        licensing_cautions: list[dict[str, Any]] = []
        evidence_locales: set[str] = set()
        mismatched: list[dict[str, Any]] = []
        now = datetime.now(UTC)
        staleness_cutoff = now - timedelta(days=policy.staleness_days)

        for evidence in evidence_rows.values():
            source = self._session.get(Source, evidence.source_id)
            document = self._session.get(NormalizedDocument, evidence.normalized_document_id)
            snapshot = self._session.get(FetchSnapshot, evidence.fetch_snapshot_id)
            item = (
                self._session.get(DiscoveryItem, snapshot.discovery_item_id)
                if snapshot is not None
                else None
            )
            if source is not None:
                source_tiers[str(source.id)] = source.trust_tier.value
                if source.trust_tier.value == "reference_only":
                    licensing_cautions.append(
                        {
                            "source_id": str(source.id),
                            "caution": (
                                "reference_only trust tier: expression must never be reused"
                            ),
                        }
                    )
            if evidence.licensing_notes:
                licensing_cautions.append(
                    {
                        "research_evidence_id": str(evidence.id),
                        "caution": evidence.licensing_notes,
                    }
                )
            basis_name = "fetched_at"
            basis = evidence.fetched_at
            if document is not None and document.external_published_at is not None:
                basis_name = "external_published_at"
                basis = document.external_published_at
            if basis is not None and basis < staleness_cutoff:
                staleness_notes.append(
                    {
                        "research_evidence_id": str(evidence.id),
                        "basis": basis_name,
                        "timestamp": basis.isoformat(),
                    }
                )
            if item is not None:
                evidence_locales.add(item.locale)
                if work_item_locale is not None and item.locale != work_item_locale:
                    mismatched.append(
                        {
                            "research_evidence_id": str(evidence.id),
                            "locale": item.locale,
                        }
                    )

        tier_distribution: dict[str, int] = {}
        for tier in source_tiers.values():
            tier_distribution[tier] = tier_distribution.get(tier, 0) + 1
        return {
            "source_tiers": source_tiers,
            "source_diversity": {
                "distinct_sources": len(source_tiers),
                "trust_tiers": dict(sorted(tier_distribution.items())),
                "reference_only_present": "reference_only" in tier_distribution,
            },
            "staleness_notes": sorted(
                staleness_notes, key=lambda note: note["research_evidence_id"]
            ),
            "locale_limitations": {
                "work_item_locale": work_item_locale,
                "evidence_locales": sorted(evidence_locales),
                "mismatches": sorted(mismatched, key=lambda entry: entry["research_evidence_id"]),
            },
            "licensing_cautions": sorted(
                licensing_cautions, key=lambda caution: json.dumps(caution, sort_keys=True)
            ),
        }


def _evaluate_sufficiency(
    *,
    role_counts: dict[str, int],
    item_count: int,
    distinct_sources: int,
    states: list[_ContradictionState],
    policy: EvidenceSufficiencyPolicy,
) -> SufficiencyResult:
    """Deterministic explicit gate; absence of evidence is never a pass."""
    unresolved_blocking = sorted(
        state.claim_key
        for state in states
        if state.severity is ContradictionSeverity.BLOCKING
        and state.resolution_status is ContradictionResolutionStatus.UNRESOLVED
    )
    key_facts = role_counts.get(EvidenceItemRole.KEY_FACT.value, 0)
    missing: list[str] = []
    if item_count < policy.min_evidence_items:
        missing.append(f"evidence items {item_count} < minimum {policy.min_evidence_items}")
    if distinct_sources < policy.min_distinct_sources:
        missing.append(
            f"distinct sources {distinct_sources} < minimum {policy.min_distinct_sources}"
        )
    if key_facts < policy.min_key_facts:
        missing.append(f"key facts {key_facts} < minimum {policy.min_key_facts}")

    detail: dict[str, Any] = {
        "policy_name": policy.name,
        "policy_version": policy.version,
        "item_count": item_count,
        "distinct_sources": distinct_sources,
        "role_counts": dict(sorted(role_counts.items())),
        "missing": missing,
        "unresolved_blocking_contradictions": unresolved_blocking,
    }
    if unresolved_blocking:
        return SufficiencyResult(EvidencePackSufficiency.CONFLICTED, detail)
    if missing:
        return SufficiencyResult(EvidencePackSufficiency.INSUFFICIENT, detail)
    return SufficiencyResult(EvidencePackSufficiency.READY, detail)


def _role_counts(selections: list[EvidenceSelection]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for selection in selections:
        counts[selection.role.value] = counts.get(selection.role.value, 0) + 1
    return counts


def _validate_selections(selections: list[EvidenceSelection]) -> list[EvidenceSelection]:
    if not selections:
        raise InvalidPackInputError("a pack needs at least one evidence selection")
    if len(selections) > MAX_SELECTIONS:
        raise InvalidPackInputError("too many evidence selections")
    cleaned: list[EvidenceSelection] = []
    seen: set[uuid.UUID] = set()
    for selection in selections:
        if not isinstance(selection.role, EvidenceItemRole):
            raise InvalidPackInputError("role must be an EvidenceItemRole value")
        if selection.research_evidence_id in seen:
            raise InvalidPackInputError("the same evidence unit cannot be selected twice")
        seen.add(selection.research_evidence_id)
        cleaned.append(
            EvidenceSelection(
                research_evidence_id=selection.research_evidence_id,
                role=selection.role,
                claim_cluster=_required_text(
                    "claim_cluster", selection.claim_cluster, MAX_CLAIM_CLUSTER_LENGTH
                ),
                display_note=_optional_text(
                    "display_note", selection.display_note, MAX_DISPLAY_NOTE_LENGTH
                ),
            )
        )
    return cleaned


def _states_from_declarations(
    declarations: list[ContradictionDeclaration], selected_ids: set[uuid.UUID]
) -> list[_ContradictionState]:
    if len(declarations) > MAX_CONTRADICTIONS:
        raise InvalidContradictionError("too many contradiction declarations")
    states: list[_ContradictionState] = []
    for declaration in declarations:
        if not isinstance(declaration.severity, ContradictionSeverity):
            raise InvalidContradictionError("severity must be a ContradictionSeverity")
        side_a = _validate_side("evidence_side_a", list(declaration.evidence_side_a), selected_ids)
        side_b = _validate_side("evidence_side_b", list(declaration.evidence_side_b), selected_ids)
        if set(side_a) & set(side_b):
            raise InvalidContradictionError("the two sides of a contradiction must be disjoint")
        states.append(
            _ContradictionState(
                claim_key=_required_text("claim_key", declaration.claim_key, MAX_CLAIM_KEY_LENGTH),
                side_a=tuple(side_a),
                side_b=tuple(side_b),
                nature=_required_text("nature", declaration.nature, MAX_NATURE_LENGTH),
                severity=declaration.severity,
                resolution_status=ContradictionResolutionStatus.UNRESOLVED,
                handling_recommendation=_optional_text(
                    "handling_recommendation",
                    declaration.handling_recommendation,
                    MAX_HANDLING_LENGTH,
                ),
                resolution_reason=None,
                resolved_by=None,
                resolved_at=None,
            )
        )
    return states


def _state_from_row(row: EvidenceContradiction) -> _ContradictionState:
    return _ContradictionState(
        claim_key=row.claim_key,
        side_a=tuple(sorted(str(value) for value in row.evidence_side_a)),
        side_b=tuple(sorted(str(value) for value in row.evidence_side_b)),
        nature=row.nature,
        severity=row.severity,
        resolution_status=row.resolution_status,
        handling_recommendation=row.handling_recommendation,
        resolution_reason=row.resolution_reason,
        resolved_by=row.resolved_by,
        resolved_at=row.resolved_at,
    )


def _validate_side(name: str, side: list[uuid.UUID], member_ids: set[uuid.UUID]) -> list[str]:
    if not isinstance(side, list) or not side:
        raise InvalidContradictionError(f"{name} must be a non-empty list")
    if len(side) > MAX_CONTRADICTION_SIDE_SIZE:
        raise InvalidContradictionError(f"{name} exceeds the size limit")
    cleaned: list[str] = []
    for evidence_id in side:
        if not isinstance(evidence_id, uuid.UUID):
            raise InvalidContradictionError(f"{name} entries must be evidence UUIDs")
        if evidence_id not in member_ids:
            raise InvalidContradictionError(
                f"{name} references evidence that is not part of this pack's selection"
            )
        if str(evidence_id) in cleaned:
            raise InvalidContradictionError(f"{name} contains duplicate entries")
        cleaned.append(str(evidence_id))
    return sorted(cleaned)


def _assembly_input_snapshot(
    selections: list[EvidenceSelection],
    states: list[_ContradictionState],
    policy: EvidenceSufficiencyPolicy,
    idea_id: uuid.UUID | None,
) -> dict[str, Any]:
    """The WHOLE semantic assembly identity (stored for reproducibility).

    Cosmetic/advisory inputs (display notes, handling recommendations) are
    the only exclusions: they never affect sufficiency or gate meaning.
    """
    return {
        "schema": ASSEMBLY_INPUT_SCHEMA_VERSION,
        "assembler_name": EVIDENCE_PACK_ASSEMBLER_NAME,
        "assembler_version": EVIDENCE_PACK_ASSEMBLER_VERSION,
        "idea_id": str(idea_id) if idea_id is not None else None,
        "policy": policy.snapshot(),
        "selections": sorted(
            [
                {
                    "research_evidence_id": str(selection.research_evidence_id),
                    "role": selection.role.value,
                    "claim_cluster": selection.claim_cluster,
                }
                for selection in selections
            ],
            key=lambda entry: entry["research_evidence_id"],
        ),
        "contradictions": sorted(
            [
                {
                    "claim_key": state.claim_key,
                    "side_a": list(state.side_a),
                    "side_b": list(state.side_b),
                    "nature": state.nature,
                    "severity": state.severity.value,
                    "resolution_status": state.resolution_status.value,
                }
                for state in states
            ],
            key=lambda entry: json.dumps(entry, sort_keys=True, ensure_ascii=False),
        ),
    }


def _assembly_input_hash(snapshot: dict[str, Any]) -> str:
    serialized = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _required_text(name: str, value: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidPackInputError(f"{name} must not be empty")
    cleaned = " ".join(value.split())
    if len(cleaned) > limit:
        raise InvalidPackInputError(f"{name} exceeds the {limit}-character limit")
    return cleaned


def _optional_text(name: str, value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    return _required_text(name, value, limit)
