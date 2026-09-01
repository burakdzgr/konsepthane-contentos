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


class CompositionPreconditionError(BriefError):
    """A composition precondition failed BEFORE any provider invocation.

    No model tokens are spent composing from an ineligible chain (wrong
    state, uncommissioned opportunity, non-READY pack, stale selection,
    inconsistent upstream)."""


class InvalidCompositionAttemptError(BriefError):
    """The referenced attempt cannot back a composed brief.

    Wrong purpose, non-SUCCEEDED status, or mismatched persisted input
    provenance — the FK alone is never trusted."""


class IncompleteBriefMaterializationError(BriefError):
    """A reused SUCCEEDED composition attempt has no linked brief.

    Raw model output is deliberately never persisted and the provider must
    not be re-invoked under the same attempt identity — request a new
    provider invocation explicitly with retry_number + 1."""


class BriefCompositionMaterializationError(BriefError):
    """Structurally valid AI output was rejected by Task-11 persistence.

    The completed AI attempt keeps its real status (it is NEVER
    retroactively relabeled a provider/validation failure); the
    deterministic persistence-time rejection is reported here instead."""
