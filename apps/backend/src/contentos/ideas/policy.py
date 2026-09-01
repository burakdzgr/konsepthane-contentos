"""Explicit, versioned deterministic idea-originality policy.

Task 1 deliberately froze no universal originality thresholds. Every
threshold used by the Task 7 guards therefore lives in a NAMED, VERSIONED
policy object whose exact snapshot is persisted on each idea version — no
hidden constants, no invisible universal editorial truth. Callers may supply
another policy (for example a stricter one for a risk class or content
type); the default below is the initial operational policy only.
"""

from dataclasses import dataclass, field
from typing import Any

from contentos.duplicates.signals import TITLE_SIMILARITY_METRIC
from contentos.ideas.errors import InvalidIdeaInputError

MAX_FAKE_UGC_PATTERNS = 50
MAX_FAKE_UGC_PATTERN_LENGTH = 100

# Bounded casefolded substrings that claim user-generated content. Phase 3
# has no UGC ingestion/provenance, so any match is a deterministic hard
# rejection. Deliberately literal: this is a policy list, not semantic
# detection, and makes no claim to catch every paraphrase.
_DEFAULT_FAKE_UGC_PATTERNS = (
    "gerçek kullanıcı yorum",
    "gerçek yorum",
    "kullanıcı yorumları",
    "okuyucu yorumları",
    "müşteri yorumları",
    "ziyaretçi yorumları",
    "annelerden tavsiye",
    "annelerin tavsiye",
    "gerçek anne",
    "gerçek deneyimler",
    "müşteri deneyimi",
    "kullanıcı puanları",
    "kullanıcı değerlendirme",
    "müşterilerimiz anlatıyor",
    "testimonial",
)


@dataclass(frozen=True, slots=True)
class IdeaOriginalityPolicy:
    """One complete deterministic originality policy version."""

    name: str
    version: str
    min_distinct_sources: int
    title_similarity_failure_threshold: float
    fake_ugc_patterns: tuple[str, ...] = field(default=_DEFAULT_FAKE_UGC_PATTERNS)

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.version.strip():
            raise InvalidIdeaInputError("originality policy needs a name and a version")
        if self.min_distinct_sources < 1:
            raise InvalidIdeaInputError("min_distinct_sources must be at least 1")
        if not 0.0 < self.title_similarity_failure_threshold <= 1.0:
            raise InvalidIdeaInputError("title_similarity_failure_threshold must be within (0, 1]")
        if len(self.fake_ugc_patterns) > MAX_FAKE_UGC_PATTERNS:
            raise InvalidIdeaInputError("too many fake-UGC patterns")
        for pattern in self.fake_ugc_patterns:
            if not pattern.strip() or len(pattern) > MAX_FAKE_UGC_PATTERN_LENGTH:
                raise InvalidIdeaInputError("fake-UGC patterns must be non-empty and bounded")

    def snapshot(self) -> dict[str, Any]:
        """The complete policy provenance persisted on every idea version."""
        return {
            "policy_name": self.name,
            "policy_version": self.version,
            "min_distinct_sources": self.min_distinct_sources,
            "title_similarity_failure_threshold": self.title_similarity_failure_threshold,
            "title_similarity_metric": TITLE_SIMILARITY_METRIC,
            "fake_ugc_patterns": list(self.fake_ugc_patterns),
            "note": (
                "initial operational policy; thresholds are operational choices, "
                "not universal editorial truth"
            ),
        }


DEFAULT_IDEA_ORIGINALITY_POLICY = IdeaOriginalityPolicy(
    name="default",
    version="1",
    min_distinct_sources=2,
    title_similarity_failure_threshold=0.90,
)
