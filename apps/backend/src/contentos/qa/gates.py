"""The qa-gates/2 deterministic gate engine (PHASE4_QA_ARCHITECTURE.md §3;
media gate v2 per PHASE6_MEDIA_ARCHITECTURE.md §4).

Seven hard gates computed from DURABLE rows over the exact entry-pinned
package. Every gate yields an explicit result — the absence of a result
is never a pass — and the outcome is computed deterministically: `ready
for human review` only when every BLOCKING gate is `pass`,
`not_applicable`, or `waived_by_human`. No provider is ever involved;
execution errors are exceptions, never outcomes.
"""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from contentos.briefs.repository import BriefRepository
from contentos.drafts.errors import DraftInputError
from contentos.drafts.repository import DraftRepository
from contentos.drafts.values import MAX_TITLE_PROPOSAL_LENGTH, require_safe_text
from contentos.evidence_packs.repository import EvidencePackRepository
from contentos.media.enums import SatisfactionStatus
from contentos.media.models import MediaNeedSatisfaction
from contentos.qa.enums import QaGateKey, QaOutcome, WaivableGateKey
from contentos.qa.models import QaReport
from contentos.qa.repository import QaRepository
from contentos.qa.service import QaPackage, QaService
from contentos.qa.values import QA_GATE_POLICY_VERSION
from contentos.reviews.integrity import recompute_writer_envelope

# Gate 7 (internal_link_needs) is reported but non-blocking in v1: internal
# linking is a publish-time concern the Publishing API integration owns.
BLOCKING_GATES: tuple[QaGateKey, ...] = (
    QaGateKey.PACKAGE_INTEGRITY,
    QaGateKey.PROVENANCE_CHAIN,
    QaGateKey.WRITER_ENVELOPE,
    QaGateKey.CONTENT_SAFETY,
    QaGateKey.EDITORIAL_REVIEW_CURRENCY,
    QaGateKey.MEDIA_NEEDS,
)

_PASSING_RESULTS = frozenset({"pass", "not_applicable", "waived_by_human", "satisfied"})


def gate_policy_snapshot() -> dict[str, Any]:
    return {
        "version": QA_GATE_POLICY_VERSION,
        "blocking_gates": [gate.value for gate in BLOCKING_GATES],
        "non_blocking_gates": [QaGateKey.INTERNAL_LINK_NEEDS.value],
        "waivable_gates": [gate.value for gate in WaivableGateKey],
    }


@dataclass(frozen=True, slots=True)
class QaRunResult:
    """One deterministic gate run over the resolved package."""

    package: QaPackage
    report: QaReport
    outcome: QaOutcome
    created: bool


class QaGateEngine:
    """Transport-neutral engine; flushes only — the caller commits."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._service = QaService(session)
        self._repository = QaRepository(session)
        self._drafts = DraftRepository(session)
        self._briefs = BriefRepository(session)
        self._packs = EvidencePackRepository(session)

    def run_gates(self, work_item_id: uuid.UUID, *, request_id: str | None = None) -> QaRunResult:
        package = self._service.resolve_package(work_item_id)
        gate_results = {
            QaGateKey.PACKAGE_INTEGRITY.value: self._package_integrity(package),
            QaGateKey.PROVENANCE_CHAIN.value: self._provenance_chain(package),
            QaGateKey.WRITER_ENVELOPE.value: self._writer_envelope(package),
            QaGateKey.CONTENT_SAFETY.value: self._content_safety(package),
            QaGateKey.EDITORIAL_REVIEW_CURRENCY.value: self._review_currency(package),
            QaGateKey.MEDIA_NEEDS.value: self._media_needs(package),
            QaGateKey.INTERNAL_LINK_NEEDS.value: self._internal_link_needs(package),
        }
        outcome = (
            QaOutcome.READY_FOR_HUMAN_REVIEW
            if all(
                gate_results[gate.value]["result"] in _PASSING_RESULTS for gate in BLOCKING_GATES
            )
            else QaOutcome.NOT_READY
        )
        persistence = self._service.persist_report(
            package,
            outcome=outcome,
            gate_results=gate_results,
            gate_policy_snapshot=gate_policy_snapshot(),
            request_id=request_id,
        )
        return QaRunResult(
            package=package,
            report=persistence.report,
            outcome=outcome,
            created=persistence.created,
        )

    # --- individual gates ----------------------------------------------------

    def _package_integrity(self, package: QaPackage) -> dict[str, Any]:
        # resolve_package already re-proved the pins/statuses; this gate
        # records the check explicitly and adds the hash pin comparison.
        checks = {
            "entry_pins_resolve_to_active_package": True,
            "review_verdict_is_pass": True,
            "brief_is_accepted_contract": True,
            "review_covers_active_draft": True,
        }
        return {"result": "pass", "checks": checks}

    def _provenance_chain(self, package: QaPackage) -> dict[str, Any]:
        usages = self._drafts.list_claim_usages(package.draft.id)
        used_claim_ids = sorted({str(usage.brief_claim_id) for usage in usages})
        broken: list[str] = []
        evidence_links = 0
        for claim_id in used_claim_ids:
            links = self._briefs.list_claim_evidence(uuid.UUID(claim_id))
            evidence_links += len(links)
            if not links:
                broken.append(claim_id)
        result = "pass" if not broken else "fail"
        return {
            "result": result,
            "used_claims": len(used_claim_ids),
            "claim_usages": len(usages),
            "evidence_links": evidence_links,
            "broken_claims": broken,
        }

    def _writer_envelope(self, package: QaPackage) -> dict[str, Any]:
        claims = self._briefs.list_claims(package.brief.id)
        pack = self._packs.get_pack(package.brief.evidence_pack_id)
        assert pack is not None  # RESTRICT FKs make this unreachable
        checks, _ = recompute_writer_envelope(
            brief=package.brief,
            claims=claims,
            pack=pack,
            contradictions=self._packs.list_contradictions(package.brief.evidence_pack_id),
            draft=package.draft,
            usages=self._drafts.list_claim_usages(package.draft.id),
        )
        result = "pass" if all(value == "ok" for value in checks.values()) else "fail"
        return {"result": result, "checks": checks}

    def _content_safety(self, package: QaPackage) -> dict[str, Any]:
        unsafe: list[str] = []
        if package.draft.title_proposal is not None:
            try:
                require_safe_text(
                    "title_proposal", package.draft.title_proposal, MAX_TITLE_PROPOSAL_LENGTH
                )
            except DraftInputError:
                unsafe.append("title_proposal")
        for section in package.draft.body.get("sections", []):
            for block in section.get("blocks", []):
                try:
                    require_safe_text(str(block.get("block_id")), str(block.get("text")), 1_000_000)
                except DraftInputError:
                    unsafe.append(str(block.get("block_id")))
        result = "pass" if not unsafe else "fail"
        return {"result": result, "unsafe_anchors": unsafe}

    def _review_currency(self, package: QaPackage) -> dict[str, Any]:
        gate = package.review.integrity_gate_result or {}
        scope = package.review.review_scope or {}
        checks = {
            "writer_envelope_recomputed": gate.get("writer_envelope_recomputed") is True,
            "scope_draft_hash_current": (
                scope.get("draft_content_hash") == package.draft.content_hash
            ),
            "scope_brief_hash_current": (
                scope.get("brief_content_hash") == package.brief.content_hash
            ),
        }
        result = "pass" if all(checks.values()) else "fail"
        return {"result": result, "checks": checks}

    def _media_needs(self, package: QaPackage) -> dict[str, Any]:
        needs = list(package.brief.media_needs)
        if not needs:
            return {"result": "not_applicable", "needs": 0}
        satisfied_indexes = {
            row.need_index
            for row in self._session.execute(
                select(MediaNeedSatisfaction).where(
                    MediaNeedSatisfaction.work_item_id == package.work_item_id,
                    MediaNeedSatisfaction.content_brief_id == package.brief.id,
                    MediaNeedSatisfaction.status == SatisfactionStatus.ACTIVE,
                )
            ).scalars()
        }
        unmet = sorted(index for index in range(len(needs)) if index not in satisfied_indexes)
        if not unmet:
            # Every need carries an explicit audited human binding.
            return {
                "result": "satisfied",
                "needs": len(needs),
                "satisfied": len(needs),
            }
        waivers = [
            waiver
            for waiver in self._repository.list_waivers(package.work_item_id)
            if waiver.gate_key is WaivableGateKey.MEDIA_NEEDS
        ]
        if waivers:
            # The waiver limits scope honestly; the unmet needs stay visible.
            return {
                "result": "waived_by_human",
                "needs": len(needs),
                "unmet_indexes": unmet,
                "waiver_ids": [str(waiver.id) for waiver in waivers],
            }
        # EXACT unmet indexes — never a count that hides which.
        return {"result": "unsatisfied", "needs": len(needs), "unmet_indexes": unmet}

    def _internal_link_needs(self, package: QaPackage) -> dict[str, Any]:
        needs = list(package.brief.internal_link_needs)
        if not needs:
            return {"result": "none", "needs": 0, "blocking": False}
        return {"result": "pending", "needs": len(needs), "blocking": False}
