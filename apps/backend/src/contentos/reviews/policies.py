"""Deterministic editor verdict policy (`editor-verdict/1`).

The verdict is COMPUTED from validated findings — the model never
authors it. There is no reject verdict (REJECTED is human-only) and no
verdict for execution failure (failures never become editorial state).
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from contentos.reviews.enums import FindingSeverity, ReviewVerdict

EDITOR_VERDICT_POLICY_VERSION = "editor-verdict/1"


@dataclass(frozen=True, slots=True)
class EditorVerdictPolicy:
    version: str = EDITOR_VERDICT_POLICY_VERSION
    # Severities that force a revise verdict; minor findings persist as
    # visible signals for QA without blocking.
    revise_severities: tuple[FindingSeverity, ...] = field(
        default=(FindingSeverity.BLOCKING, FindingSeverity.MAJOR)
    )

    def compute(self, severities: Sequence[FindingSeverity]) -> ReviewVerdict:
        if any(severity in self.revise_severities for severity in severities):
            return ReviewVerdict.REVISE
        return ReviewVerdict.PASS

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "revise_severities": [severity.value for severity in self.revise_severities],
        }


DEFAULT_EDITOR_VERDICT_POLICY = EditorVerdictPolicy()
