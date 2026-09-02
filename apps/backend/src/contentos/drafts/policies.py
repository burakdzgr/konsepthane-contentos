"""Versioned Writer-stage validation and originality policies (Task 3).

Everything here is DETERMINISTIC and fail-closed at persistence — the
truthful enforcement envelope of the accepted Phase 4 design §6/§7:

- `writer-validation/1`: the numeric-assertion gate (digit-bearing text
  requires an eligible claim binding), claim-kind framing rules
  (SOURCE_ASSERTION attribution, INFERENCE hedging), and the
  required-handling coverage rule (no mandatory caveat may disappear).
- `writer-originality/1`: the evidence-statement verbatim-overlap cap
  (no long source excerpts — the model never receives source bodies, so
  the projected evidence statements are the only copyable text) plus the
  source-structure basis carried from the brief's own structure guard.

Semantic claim-faithfulness (entailment) is explicitly NOT claimed here;
that layer belongs to Editor/QA over the DraftClaimUsage -> BriefClaim ->
ResearchEvidence chain. Exclusions remain visible contract: the brief's
free-text exclusions are not mechanically checkable, and the policy
snapshot records that honestly instead of pretending.

Numeric thresholds and marker vocabularies are POLICY configuration,
versioned via these snapshots — never architectural truth.
"""

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from contentos.briefs.enums import BriefClaimKind
from contentos.briefs.models import BriefClaim, ContentBrief
from contentos.drafts.errors import DraftPolicyViolationError
from contentos.evidence_packs.enums import (
    ContradictionResolutionStatus,
    ContradictionSeverity,
)
from contentos.evidence_packs.models import EvidenceContradiction, EvidencePack

WRITER_VALIDATION_NAME = "writer-validation"
WRITER_VALIDATION_VERSION = "1"
WRITER_ORIGINALITY_NAME = "writer-originality"
WRITER_ORIGINALITY_VERSION = "1"

_DIGIT_PATTERN = re.compile(r"\d")
# Leading enumeration on step/list lines is presentation, not a factual
# assertion ("1. Balonları şişirin" / "2) Masayı kurun").
_STEP_NUMBER_PATTERN = re.compile(r"(?m)^\s*\d+[.)]\s")


@dataclass(frozen=True, slots=True)
class WriterValidationPolicy:
    """Deterministic Writer-stage validation configuration."""

    name: str = WRITER_VALIDATION_NAME
    version: str = WRITER_VALIDATION_VERSION
    # A digit-bearing block must reference at least one brief claim unless
    # every digit is a step/list enumeration marker.
    numeric_assertions_require_claim: bool = True
    # Turkish attribution stems: a block relaying a SOURCE_ASSERTION claim
    # must keep source-says framing.
    attribution_markers: tuple[str, ...] = (
        "göre",
        "aktar",
        "belirt",
        "kaynağ",
        "kaynak",
        "rapor",
        "açıkl",
        "ifade",
    )
    # Turkish hedging stems: a block using an INFERENCE claim must keep
    # inference framing; certainty-hardening fails closed.
    hedging_markers: tuple[str, ...] = (
        "olabilir",
        "olabilecek",
        "görünüyor",
        "görünmektedir",
        "muhtemel",
        "tahmin",
        "değerlendir",
        "işaret ediyor",
        "kesin değil",
        "belirsiz",
    )
    # Free-text brief exclusions cannot be checked mechanically; recorded
    # truthfully so nothing pretends otherwise.
    exclusions_mechanically_checked: bool = False

    def snapshot(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "numeric_assertions_require_claim": self.numeric_assertions_require_claim,
            "attribution_markers": list(self.attribution_markers),
            "hedging_markers": list(self.hedging_markers),
            "exclusions_mechanically_checked": self.exclusions_mechanically_checked,
        }


@dataclass(frozen=True, slots=True)
class WriterOriginalityPolicy:
    """Deterministic Writer-stage originality configuration."""

    name: str = WRITER_ORIGINALITY_NAME
    version: str = WRITER_ORIGINALITY_VERSION
    # Longest permitted normalized verbatim overlap between any block text
    # and any projected evidence statement (characters).
    max_verbatim_chars: int = 80

    def snapshot(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "max_verbatim_chars": self.max_verbatim_chars,
        }


DEFAULT_WRITER_VALIDATION_POLICY = WriterValidationPolicy()
DEFAULT_WRITER_ORIGINALITY_POLICY = WriterOriginalityPolicy()


@dataclass(frozen=True, slots=True)
class HandlingRequirement:
    """One mandatory uncertainty/caution the draft must discharge."""

    handling_id: str
    kind: str
    description: str
    source: dict[str, Any] = field(default_factory=dict)


def build_required_handling_manifest(
    brief: ContentBrief,
    pack: EvidencePack,
    contradictions: list[EvidenceContradiction],
    claims: list[BriefClaim],
) -> list[HandlingRequirement]:
    """Deterministic manifest from the pinned artifacts (stable ids)."""
    manifest: list[HandlingRequirement] = []
    for index, note in enumerate(brief.uncertainty_notes):
        manifest.append(
            HandlingRequirement(
                handling_id=f"note-{index}",
                kind="uncertainty_note",
                description=str(note),
                source={"brief_id": str(brief.id), "index": index},
            )
        )
    for index, caution in enumerate(pack.licensing_cautions):
        manifest.append(
            HandlingRequirement(
                handling_id=f"licensing-{index}",
                kind="licensing_caution",
                description=str(caution),
                source={"evidence_pack_id": str(pack.id), "index": index},
            )
        )
    for index, staleness_note in enumerate(pack.staleness_notes):
        manifest.append(
            HandlingRequirement(
                handling_id=f"staleness-{index}",
                kind="staleness",
                description=str(staleness_note),
                source={"evidence_pack_id": str(pack.id), "index": index},
            )
        )
    if pack.locale_limitations:
        manifest.append(
            HandlingRequirement(
                handling_id="locale-limitations",
                kind="locale_limitation",
                description=str(pack.locale_limitations),
                source={"evidence_pack_id": str(pack.id)},
            )
        )
    for contradiction in contradictions:
        needs_handling = (
            contradiction.resolution_status is ContradictionResolutionStatus.UNRESOLVED
            and contradiction.severity is not ContradictionSeverity.BLOCKING
        ) or (
            contradiction.resolution_status
            is ContradictionResolutionStatus.RESOLVED_CAUTIOUS_WORDING
        )
        if needs_handling:
            manifest.append(
                HandlingRequirement(
                    handling_id=f"contradiction-{contradiction.id}",
                    kind="contradiction_cautious_wording",
                    description=contradiction.nature,
                    source={"contradiction_id": str(contradiction.id)},
                )
            )
    for claim in claims:
        if claim.handling is not None and claim.handling.strip():
            manifest.append(
                HandlingRequirement(
                    handling_id=f"claim-{claim.id}",
                    kind="claim_handling",
                    description=claim.handling,
                    source={"brief_claim_id": str(claim.id)},
                )
            )
    return manifest


def validate_handling_coverage(
    manifest: list[HandlingRequirement],
    cleaned_body: dict[str, Any],
    policy: WriterValidationPolicy,
) -> dict[str, Any]:
    """Every manifest entry must be discharged; unknown refs fail closed."""
    known = {entry.handling_id: entry for entry in manifest}
    discharged: dict[str, list[str]] = {handling_id: [] for handling_id in known}
    for section in cleaned_body["sections"]:
        for block in section["blocks"]:
            for ref in block["uncertainty_refs"]:
                if ref not in known:
                    raise DraftPolicyViolationError(
                        f"block {block['block_id']} references unknown handling "
                        f"id {ref!r}; only manifest entries may be discharged"
                    )
                discharged[ref].append(block["block_id"])
    missing = [handling_id for handling_id, blocks in discharged.items() if not blocks]
    if missing:
        raise DraftPolicyViolationError(
            "mandatory uncertainty/caution handling disappeared from the draft: "
            + ", ".join(sorted(missing))
        )
    return {
        "status": "evaluated",
        "policy": f"{policy.name}/{policy.version}",
        "total": len(manifest),
        "entries": [
            {
                "id": entry.handling_id,
                "kind": entry.kind,
                "block_ids": discharged[entry.handling_id],
            }
            for entry in manifest
        ],
    }


def validate_claim_semantics(
    cleaned_body: dict[str, Any],
    claims_by_id: dict[str, BriefClaim],
    policy: WriterValidationPolicy,
) -> None:
    """The deterministic fact-creation envelope (design §6)."""
    for section in cleaned_body["sections"]:
        for block in section["blocks"]:
            text = block["text"]
            block_id = block["block_id"]
            claim_refs = block["claim_refs"]

            if policy.numeric_assertions_require_claim and not claim_refs:
                scannable = _STEP_NUMBER_PATTERN.sub("", text)
                if _DIGIT_PATTERN.search(scannable):
                    raise DraftPolicyViolationError(
                        f"block {block_id} contains a numeric assertion without "
                        "an eligible brief-claim binding (the model's own "
                        "numbers are never facts)"
                    )

            folded = text.casefold()
            kinds = {claims_by_id[ref].claim_kind for ref in claim_refs}
            if BriefClaimKind.SOURCE_ASSERTION in kinds and not _contains_any(
                folded, policy.attribution_markers
            ):
                raise DraftPolicyViolationError(
                    f"block {block_id} relays a source assertion without "
                    "attribution framing; it may never be restated as bare fact"
                )
            if BriefClaimKind.INFERENCE in kinds and not _contains_any(
                folded, policy.hedging_markers
            ):
                raise DraftPolicyViolationError(
                    f"block {block_id} uses an inference claim without inference "
                    "framing; uncertainty may not be hardened into fact"
                )


def validate_originality(
    cleaned_body: dict[str, Any],
    title_proposal: str | None,
    evidence_statements: list[str],
    brief: ContentBrief,
    policy: WriterOriginalityPolicy,
) -> dict[str, Any]:
    """Verbatim-overlap cap + the source-structure basis, truthfully."""
    normalized_statements = [
        _normalize(statement) for statement in evidence_statements if statement
    ]
    max_observed = 0
    worst_block: str | None = None
    texts: list[tuple[str, str]] = []
    if title_proposal is not None:
        texts.append(("title_proposal", title_proposal))
    for section in cleaned_body["sections"]:
        texts.append((f"heading:{section['key']}", section["heading"]))
        for block in section["blocks"]:
            texts.append((block["block_id"], block["text"]))

    for anchor, raw_text in texts:
        normalized = _normalize(raw_text)
        for statement in normalized_statements:
            overlap = _longest_common_substring(normalized, statement)
            if overlap > max_observed:
                max_observed = overlap
                worst_block = anchor
    if max_observed > policy.max_verbatim_chars:
        raise DraftPolicyViolationError(
            f"draft text at {worst_block} copies {max_observed} consecutive "
            "characters from a projected evidence statement (limit "
            f"{policy.max_verbatim_chars}); RESEARCH, DO NOT "
            "TRANSLATE-AND-REPUBLISH"
        )

    brief_guard_outcome = brief.structure_guard_result.get("outcome", "not_reported")
    return {
        "outcome": "passed",
        "policy": f"{policy.name}/{policy.version}",
        "checks": {
            "verbatim_overlap": {
                "max_observed_chars": max_observed,
                "limit_chars": policy.max_verbatim_chars,
            },
            "source_structure": {
                # Source outlines are not part of the Writer projection by
                # design; the brief's own structure guard is the durable
                # source-structure basis and is carried, not re-proven.
                "basis": "brief-structure-guard",
                "brief_guard_outcome": brief_guard_outcome,
            },
        },
    }


def _contains_any(folded_text: str, markers: tuple[str, ...]) -> bool:
    return any(marker.casefold() in folded_text for marker in markers)


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold()).strip()


def _longest_common_substring(left: str, right: str) -> int:
    if not left or not right:
        return 0
    match = SequenceMatcher(None, left, right, autojunk=False).find_longest_match(
        0, len(left), 0, len(right)
    )
    return match.size
