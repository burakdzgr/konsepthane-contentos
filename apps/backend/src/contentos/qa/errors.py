"""Typed QA domain errors; transport-neutral."""


class QaError(Exception):
    """Base class for QA domain errors."""


class QaInputError(QaError):
    """A waiver or report input violates the bounded QA contract."""


class QaReportNotFoundError(QaError):
    """No QA report exists for the given identity."""


class QaPreconditionError(QaError):
    """The durable workflow/package state does not admit a QA run (work
    item not in QA_REVIEW, entry pins missing, or the pinned package no
    longer resolves to the ACTIVE pass review over the ACTIVE draft)."""


class QaPackageError(QaError):
    """The QA_REVIEW entry pins exist but the package is ambiguous or
    contradicts durable state; refusing to evaluate ambiguous state."""


class QaConflictError(QaError):
    """Durable QA state conflicts with the requested persistence and could
    not be resolved idempotently; nothing was overwritten."""
