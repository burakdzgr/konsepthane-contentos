"""Explicit, versioned evidence-sufficiency policy.

The assembler never imposes one invisible universal editorial truth: callers
pass an explicit `EvidenceSufficiencyPolicy`, whose full thresholds are
persisted in the pack's policy snapshot AND participate in the semantic
assembly identity — changing any threshold or the policy name/version
produces a NEW pack version, never a silent reinterpretation.

`DEFAULT_EVIDENCE_POLICY` is a named, versioned initial operational policy
for tests and early operation; it is not universal truth. The 180-day
staleness threshold belongs to the policy, not to hidden code.
"""

from dataclasses import dataclass
from typing import Any

from contentos.evidence_packs.errors import InvalidPackInputError


@dataclass(frozen=True, slots=True)
class EvidenceSufficiencyPolicy:
    """One explicit sufficiency policy; frozen and fully snapshot-persisted."""

    name: str
    version: str
    min_evidence_items: int
    min_distinct_sources: int
    min_key_facts: int
    staleness_days: int

    def snapshot(self) -> dict[str, Any]:
        return {
            "policy_name": self.name,
            "policy_version": self.version,
            "min_evidence_items": self.min_evidence_items,
            "min_distinct_sources": self.min_distinct_sources,
            "min_key_facts": self.min_key_facts,
            "staleness_days": self.staleness_days,
            "conflicted_rule": ("any UNRESOLVED contradiction with severity 'blocking'"),
            "blocked_rule": ("reserved; this policy defines no deterministic block condition"),
            "note": "explicit operational policy; not universal truth",
        }

    @classmethod
    def from_snapshot(cls, snapshot: dict[str, Any]) -> "EvidenceSufficiencyPolicy":
        try:
            return cls(
                name=str(snapshot["policy_name"]),
                version=str(snapshot["policy_version"]),
                min_evidence_items=int(snapshot["min_evidence_items"]),
                min_distinct_sources=int(snapshot["min_distinct_sources"]),
                min_key_facts=int(snapshot["min_key_facts"]),
                staleness_days=int(snapshot["staleness_days"]),
            )
        except (KeyError, TypeError, ValueError):
            raise InvalidPackInputError(
                "the stored policy snapshot cannot be reconstructed"
            ) from None


DEFAULT_EVIDENCE_POLICY = EvidenceSufficiencyPolicy(
    name="default",
    version="1",
    min_evidence_items=3,
    min_distinct_sources=2,
    min_key_facts=1,
    staleness_days=180,
)
