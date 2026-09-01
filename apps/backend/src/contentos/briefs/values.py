"""Typed bounded draft-input DTOs for the writing contract.

`BriefDraftInput` is a persistence/gate input — never a public API and
never an LLM prompt. Task 12's composition engine will build this DTO
automatically from upstream artifacts; Task 11 validates and persists it.
No arbitrary dicts, no article prose, no giant JSON.
"""

import uuid
from dataclasses import dataclass, field
from typing import Any

from contentos.briefs.enums import BriefClaimKind
from contentos.briefs.errors import BriefInputError

MAX_INTENT_SUMMARY_LENGTH = 2000
MAX_CONTENT_OBJECTIVE_LENGTH = 1000
MAX_TITLE_DIRECTION_LENGTH = 200
MAX_TITLE_CONSTRAINTS = 10
MAX_TITLE_CONSTRAINT_LENGTH = 300

MAX_SECTIONS = 30
MAX_SECTION_KEY_LENGTH = 50
MAX_SECTION_HEADING_LENGTH = 200
MAX_SECTION_PURPOSE_LENGTH = 500

MAX_EXCLUSIONS = 40
MAX_EXCLUSION_LENGTH = 300
MAX_UNCERTAINTY_NOTES = 30
MAX_UNCERTAINTY_NOTE_LENGTH = 500
MAX_LINK_NEEDS = 20
MAX_MEDIA_NEEDS = 20
MAX_NEED_TEXT_LENGTH = 300
MAX_FAQ_QUESTIONS = 15
MAX_FAQ_QUESTION_LENGTH = 300
MAX_ACCEPTANCE_CRITERIA = 30
MAX_CRITERION_KEY_LENGTH = 50
MAX_CRITERION_TEXT_LENGTH = 500

MAX_CLAIMS = 60
MAX_CLAIM_KEY_LENGTH = 100
MAX_CLAIM_TEXT_LENGTH = 1000
MAX_CLAIM_HANDLING_LENGTH = 500
MAX_CLAIM_EVIDENCE_LINKS = 20

# The automated composer identity (Task 12). Distinct forever from the
# manual path's `manual-brief-input`; a manual draft can never claim it.
BRIEF_COMPOSER_NAME = "brief-composer"
BRIEF_COMPOSER_VERSION = "1"


@dataclass(frozen=True, slots=True)
class BriefSection:
    """One ordered section contract (order is semantically meaningful)."""

    key: str
    heading_guidance: str
    purpose: str

    def cleaned(self) -> dict[str, str]:
        return {
            "key": _required_text("section key", self.key, MAX_SECTION_KEY_LENGTH),
            "heading_guidance": _required_text(
                "section heading_guidance", self.heading_guidance, MAX_SECTION_HEADING_LENGTH
            ),
            "purpose": _required_text("section purpose", self.purpose, MAX_SECTION_PURPOSE_LENGTH),
        }


@dataclass(frozen=True, slots=True)
class InternalLinkNeed:
    """A linking NEED — never a resolved/published URL."""

    topic: str
    purpose: str

    def cleaned(self) -> dict[str, str]:
        return {
            "topic": _required_text("link-need topic", self.topic, MAX_NEED_TEXT_LENGTH),
            "purpose": _required_text("link-need purpose", self.purpose, MAX_NEED_TEXT_LENGTH),
        }


@dataclass(frozen=True, slots=True)
class MediaNeed:
    """A media NEED — never an asset, URL, or license claim."""

    role: str
    purpose: str
    constraints: str | None = None

    def cleaned(self) -> dict[str, str | None]:
        return {
            "role": _required_text("media-need role", self.role, MAX_NEED_TEXT_LENGTH),
            "purpose": _required_text("media-need purpose", self.purpose, MAX_NEED_TEXT_LENGTH),
            "constraints": _optional_text(
                "media-need constraints", self.constraints, MAX_NEED_TEXT_LENGTH
            ),
        }


@dataclass(frozen=True, slots=True)
class AcceptanceCriterion:
    """One measurable done-condition for the future draft."""

    key: str
    requirement: str

    def cleaned(self) -> dict[str, str]:
        return {
            "key": _required_text("criterion key", self.key, MAX_CRITERION_KEY_LENGTH),
            "requirement": _required_text(
                "criterion requirement", self.requirement, MAX_CRITERION_TEXT_LENGTH
            ),
        }


@dataclass(frozen=True, slots=True)
class BriefClaimInput:
    """One claim contract plus its exact ResearchEvidence links."""

    claim_key: str
    claim_text: str
    claim_kind: BriefClaimKind
    handling: str | None = None
    evidence_ids: tuple[uuid.UUID, ...] = ()


@dataclass(frozen=True, slots=True)
class BriefDraftInput:
    """The complete typed writing-contract input for one draft version."""

    intent_summary: str
    content_objective: str
    required_sections: tuple[BriefSection, ...]
    claims: tuple[BriefClaimInput, ...]
    optional_sections: tuple[BriefSection, ...] = ()
    title_direction: str | None = None
    title_constraints: tuple[str, ...] = ()
    practical_requirements: dict[str, Any] | None = None
    extra_exclusions: tuple[str, ...] = ()
    uncertainty_notes: tuple[str, ...] = ()
    internal_link_needs: tuple[InternalLinkNeed, ...] = ()
    media_needs: tuple[MediaNeed, ...] = ()
    faq_questions: tuple[str, ...] = ()
    acceptance_criteria: tuple[AcceptanceCriterion, ...] = field(default=())


def clean_sections(name: str, sections: tuple[BriefSection, ...]) -> list[dict[str, str]]:
    if len(sections) > MAX_SECTIONS:
        raise BriefInputError(f"{name} exceeds the limit of {MAX_SECTIONS} sections")
    cleaned: list[dict[str, str]] = []
    seen_keys: set[str] = set()
    for section in sections:
        entry = section.cleaned()
        if entry["key"] in seen_keys:
            raise BriefInputError(f"{name} contains duplicate section key {entry['key']!r}")
        seen_keys.add(entry["key"])
        cleaned.append(entry)
    return cleaned


def clean_string_list(
    name: str, values: tuple[str, ...], *, max_items: int, max_length: int
) -> list[str]:
    """Bounded, order-preserving, exact-duplicate-deduplicating text list."""
    if len(values) > max_items:
        raise BriefInputError(f"{name} exceeds the limit of {max_items} entries")
    cleaned: list[str] = []
    for value in values:
        entry = _required_text(name, value, max_length)
        if entry not in cleaned:
            cleaned.append(entry)
    return cleaned


def _required_text(name: str, value: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BriefInputError(f"{name} must not be empty")
    cleaned = " ".join(value.split())
    if len(cleaned) > limit:
        raise BriefInputError(f"{name} exceeds the {limit}-character limit")
    return cleaned


def _optional_text(name: str, value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    return _required_text(name, value, limit)
