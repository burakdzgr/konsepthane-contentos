"""Typed transport-neutral brief domain errors."""


class BriefError(Exception):
    """Base class for brief domain failures."""


class BriefNotFoundError(BriefError):
    """No brief version exists with the given identity."""


class BriefInputError(BriefError):
    """A caller-supplied draft field violates the bounded contract."""


class BriefConflictError(BriefError):
    """Same brief identity with materially different content, or a
    concurrent persistence conflict that could not be recovered."""


class BriefUpstreamMismatchError(BriefError):
    """The pinned upstream artifacts do not form one consistent chain."""


class BriefClaimEvidenceError(BriefError):
    """The claim/evidence map violates its deterministic contract."""


class BriefProvenanceError(BriefError):
    """A pinned provenance chain no longer resolves (ADR 0007 gate)."""


class BriefStructureGuardError(BriefError):
    """The deterministic structural copyright guard blocks acceptance."""


class BriefAcceptanceGateError(BriefError):
    """An acceptance gate failed; the brief stays DRAFT."""


class BriefStatusConflictError(BriefError):
    """The requested status action contradicts durable status history."""
