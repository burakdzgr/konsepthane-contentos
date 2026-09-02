"""Deterministic Writer-envelope drift guard (Task 11 of the Editor plan).

Recomputes, from DURABLE rows only, whether the reviewed draft still
satisfies the Writer-stage envelope it was persisted under: the brief's
section contract, the 1:1 mirror between body claim references and the
relational DraftClaimUsage rows (with every reference belonging to the
accepted brief), and the required-handling coverage manifest rebuilt from
the CURRENT brief/pack/contradiction rows.

Detected drift is not silent and not an execution failure: each failed
check becomes one BLOCKING deterministic finding (origin `deterministic`,
reserved `drift-` key prefix), which the verdict policy then turns into a
`revise` verdict. The recomputation itself never calls a provider.
"""

from typing import Any

from contentos.briefs.models import BriefClaim, ContentBrief
from contentos.drafts.errors import DraftPolicyViolationError
from contentos.drafts.models import ContentDraft, DraftClaimUsage
from contentos.drafts.policies import (
    DEFAULT_WRITER_VALIDATION_POLICY,
    build_required_handling_manifest,
    validate_handling_coverage,
)
from contentos.evidence_packs.models import EvidenceContradiction, EvidencePack
from contentos.reviews.enums import FindingDimension, FindingOrigin, FindingSeverity
from contentos.reviews.values import ReviewFindingInput

DRIFT_FINDING_PREFIX = "drift-"


def _drift_finding(key: str, dimension: FindingDimension, description: str) -> ReviewFindingInput:
    return ReviewFindingInput(
        finding_key=f"{DRIFT_FINDING_PREFIX}{key}",
        dimension=dimension,
        severity=FindingSeverity.BLOCKING,
        origin=FindingOrigin.DETERMINISTIC,
        description=description,
        recommendation=(
            "Taslak, yazar aşamasına geri yönlendirilip güncel sözleşmeye "
            "göre yeniden üretilmelidir."
        ),
    )


def recompute_writer_envelope(
    *,
    brief: ContentBrief,
    claims: list[BriefClaim],
    pack: EvidencePack,
    contradictions: list[EvidenceContradiction],
    draft: ContentDraft,
    usages: list[DraftClaimUsage],
) -> tuple[dict[str, Any], list[ReviewFindingInput]]:
    """Returns (envelope check record, deterministic drift findings)."""
    checks: dict[str, str] = {}
    findings: list[ReviewFindingInput] = []
    sections = draft.body.get("sections", [])

    # 1) Structure contract vs the accepted brief.
    required_keys = [str(entry.get("key")) for entry in brief.required_sections]
    optional_keys = {str(entry.get("key")) for entry in brief.optional_sections}
    body_keys = [section.get("key") for section in sections]
    missing = [key for key in required_keys if key not in set(body_keys)]
    unknown = [key for key in body_keys if key not in set(required_keys) | optional_keys]
    if missing or unknown:
        checks["structure_contract"] = "drift"
        parts = []
        if missing:
            parts.append(f"eksik zorunlu bölümler: {', '.join(sorted(missing))}")
        if unknown:
            parts.append(f"sözleşme dışı bölümler: {', '.join(sorted(str(k) for k in unknown))}")
        findings.append(
            _drift_finding(
                "structure-contract",
                FindingDimension.OBJECTIVE_FIT,
                "Taslak gövdesi brief'in bölüm sözleşmesini artık karşılamıyor "
                f"({'; '.join(parts)}).",
            )
        )
    else:
        checks["structure_contract"] = "ok"

    # 2) Claim-reference integrity: body refs mirror the relational usages
    #    1:1 and every reference belongs to the accepted brief's claims.
    brief_claim_ids = {str(claim.id) for claim in claims}
    body_refs = {
        (str(block.get("block_id")), str(ref))
        for section in sections
        for block in section.get("blocks", [])
        for ref in block.get("claim_refs", [])
    }
    usage_refs = {(usage.block_id, str(usage.brief_claim_id)) for usage in usages}
    outside_brief = {ref for _, ref in body_refs if ref not in brief_claim_ids}
    if body_refs != usage_refs or outside_brief:
        checks["claim_ref_integrity"] = "drift"
        findings.append(
            _drift_finding(
                "claim-integrity",
                FindingDimension.CLAIM_FAITHFULNESS,
                "Taslağın gövdesindeki iddia referansları, kalıcı "
                "DraftClaimUsage kayıtlarıyla veya kabul edilen brief'in "
                "iddialarıyla birebir örtüşmüyor.",
            )
        )
    else:
        checks["claim_ref_integrity"] = "ok"

    # 3) Handling coverage vs the manifest rebuilt from CURRENT rows.
    manifest = build_required_handling_manifest(brief, pack, contradictions, claims)
    try:
        validate_handling_coverage(manifest, draft.body, DEFAULT_WRITER_VALIDATION_POLICY)
        checks["handling_coverage"] = "ok"
    except DraftPolicyViolationError as error:
        checks["handling_coverage"] = "drift"
        findings.append(
            _drift_finding(
                "handling-coverage",
                FindingDimension.UNCERTAINTY_FRAMING,
                "Zorunlu belirsizlik/çekince kapsaması güncel manifestoya "
                f"göre artık sağlanmıyor: {error}",
            )
        )

    return checks, findings
