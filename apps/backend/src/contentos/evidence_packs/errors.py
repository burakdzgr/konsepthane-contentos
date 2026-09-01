"""Typed evidence-pack domain errors; transport-neutral."""


class EvidencePackError(Exception):
    """Base class for evidence-pack domain errors."""


class InvalidPackInputError(EvidencePackError):
    """A selection/assembly input violates the pack contract."""


class EvidenceNotEligibleError(EvidencePackError):
    """Selected evidence does not trace to the opportunity's research inputs."""


class PackNotFoundError(EvidencePackError):
    """No evidence pack exists for the given identity."""


class PackConflictError(EvidencePackError):
    """A concurrent assembly conflicted and could not be recovered."""


class ContradictionNotFoundError(EvidencePackError):
    """No contradiction exists for the given identity."""


class InvalidContradictionError(EvidencePackError):
    """A contradiction record/resolution input violates the contract."""
