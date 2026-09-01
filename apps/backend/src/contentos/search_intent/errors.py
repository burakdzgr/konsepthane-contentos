"""Typed transport-neutral search-intent domain errors."""


class SearchIntentError(Exception):
    """Base class for search-intent domain failures."""


class AnalysisNotFoundError(SearchIntentError):
    """No analysis version exists with the given identity."""


class InvalidAnalysisInputError(SearchIntentError):
    """A caller-supplied analysis field violates the bounded contract."""


class IdeaNotSelectedError(SearchIntentError):
    """The supplied idea is not the current effective selection.

    An analysis pins the EXACT selected idea version at analysis time; the
    service never selects an idea itself.
    """


class SignalNotEligibleError(SearchIntentError):
    """A referenced SearchSignal is missing or incompatible.

    Signals are consumed by EXACT observation id only — there is no
    implicit "latest signal" — and must match the analysis locale/market.
    """


class InvalidCannibalizationError(SearchIntentError):
    """The cannibalization input violates the honest truth-state contract."""


class InvalidSynthesisAttemptError(SearchIntentError):
    """The referenced attempt cannot back a search-intent analysis.

    Wrong purpose, non-SUCCEEDED status, or mismatched persisted input
    provenance — the FK alone is never trusted.
    """


class IncompleteAnalysisMaterializationError(SearchIntentError):
    """A reused SUCCEEDED synthesis attempt has no linked analysis.

    Raw model output is deliberately never persisted and the provider must
    not be re-invoked under the same attempt identity — request a new
    provider invocation explicitly with retry_number + 1.
    """


class AnalysisConflictError(SearchIntentError):
    """Concurrent analysis persistence conflicted and could not recover."""
