"""EvidencePack vocabulary. Values are persistence contracts; never rename."""

from enum import StrEnum


class EvidencePackSufficiency(StrEnum):
    """The explicit sufficiency result; absence of evidence is never a pass.

    BLOCKED is reserved vocabulary: assembler policy v1 defines no
    deterministic policy/licensing block condition and therefore never emits
    it (licensing cautions travel with the pack instead of blocking it).
    """

    READY = "ready"
    INSUFFICIENT = "insufficient"
    CONFLICTED = "conflicted"
    BLOCKED = "blocked"


class EvidenceItemRole(StrEnum):
    """How one evidence unit functions inside the pack."""

    KEY_FACT = "key_fact"
    SUPPORTING = "supporting"
    CONTRADICTING = "contradicting"
    CONTEXT = "context"
    CAUTION = "caution"


class ContradictionSeverity(StrEnum):
    LOW = "low"
    MATERIAL = "material"
    BLOCKING = "blocking"


class ContradictionResolutionStatus(StrEnum):
    """Resolution is an operator/editorial act, never a model output."""

    UNRESOLVED = "unresolved"
    RESOLVED_CAUTIOUS_WORDING = "resolved_cautious_wording"
    RESOLVED_NEEDS_RESEARCH = "resolved_needs_research"
    RESOLVED_EDITORIAL_JUDGMENT = "resolved_editorial_judgment"


class ContradictionResolver(StrEnum):
    """Who resolved a contradiction; only operators may in Phase 3."""

    OPERATOR = "operator"
