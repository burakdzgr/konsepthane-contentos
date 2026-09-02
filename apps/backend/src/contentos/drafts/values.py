"""Typed bounded body DTOs for the writer-draft content contract.

`DraftBodyInput` is the ONLY shape a draft body can take before
persistence: ordered sections keyed to the accepted brief's section
contract, typed blocks carrying inline-Markdown text plus explicit claim
and uncertainty references. Never arbitrary JSON, never HTML, never URLs
(links and media exist only as placeholder needs referencing the brief).

Both draft origins (Writer engine and operator) funnel through this DTO
so the structural gates are identical.
"""

import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from contentos.drafts.enums import DraftBlockKind
from contentos.drafts.errors import DraftInputError

# The versioned canonical body schema. Canonicalization/shape changes MUST
# bump this so historical bodies keep their original meaning.
BODY_SCHEMA_VERSION = "writer-draft-body/1"

# Engine identities. The automated Writer identity is distinct forever
# from the manual path's identity; a manual draft can never claim it.
WRITER_ENGINE_NAME = "writer"
WRITER_ENGINE_VERSION = "1"
MANUAL_DRAFT_ENGINE_NAME = "manual-draft-input"
MANUAL_DRAFT_ENGINE_VERSION = "1"

# Task-2 structural validation identity (persisted in the validation
# policy snapshot until the Task-3 writer-validation policy supersedes it).
STRUCTURAL_VALIDATION_NAME = "writer-structural"
STRUCTURAL_VALIDATION_VERSION = "1"

MAX_TITLE_PROPOSAL_LENGTH = 200
MAX_SECTIONS = 30
MAX_SECTION_KEY_LENGTH = 50
MAX_HEADING_LENGTH = 200
MAX_BLOCKS_PER_SECTION = 60
MAX_TOTAL_BLOCKS = 300
MAX_BLOCK_ID_LENGTH = 64
MAX_BLOCK_TEXT_LENGTH = 5000
MAX_CLAIM_REFS_PER_BLOCK = 10
MAX_UNCERTAINTY_REFS_PER_BLOCK = 10
MAX_UNCERTAINTY_REF_LENGTH = 100

_BLOCK_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")

# Deterministic URL/HTML/script ban for every human-visible text field.
# Links and media never live in draft text: they are placeholder needs.
_FORBIDDEN_TEXT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"https?://", re.IGNORECASE), "URLs are forbidden in draft text"),
    (re.compile(r"\bwww\.", re.IGNORECASE), "URLs are forbidden in draft text"),
    (re.compile(r"<\s*[a-zA-Z!/]"), "HTML markup is forbidden in draft text"),
    (re.compile(r"javascript\s*:", re.IGNORECASE), "script content is forbidden in draft text"),
    (re.compile(r"data\s*:\s*text/html", re.IGNORECASE), "embedded HTML is forbidden"),
)

_PLACEHOLDER_KINDS = frozenset({DraftBlockKind.INTERNAL_LINK_NEED, DraftBlockKind.MEDIA_NEED})


def require_safe_text(name: str, value: str, limit: int) -> str:
    """Bounded, non-empty, URL/HTML/script-free text."""
    if not isinstance(value, str):
        raise DraftInputError(f"{name} must be a string")
    cleaned = value.strip()
    if not cleaned:
        raise DraftInputError(f"{name} must not be empty")
    if len(cleaned) > limit:
        raise DraftInputError(f"{name} exceeds the {limit}-character limit")
    for pattern, message in _FORBIDDEN_TEXT_PATTERNS:
        if pattern.search(cleaned):
            raise DraftInputError(f"{name}: {message}")
    return cleaned


@dataclass(frozen=True, slots=True)
class DraftBlock:
    """One typed content block; `block_id` is the stable provenance anchor."""

    block_id: str
    kind: DraftBlockKind
    text: str
    claim_refs: tuple[uuid.UUID, ...] = ()
    uncertainty_refs: tuple[str, ...] = ()
    # Placeholder blocks reference an entry INDEX of the accepted brief's
    # internal_link_needs / media_needs lists — never a URL or asset.
    link_need_ref: int | None = None
    media_need_ref: int | None = None

    def cleaned(self) -> dict[str, Any]:
        if not isinstance(self.kind, DraftBlockKind):
            raise DraftInputError("block kind must be a DraftBlockKind value")
        block_id = self.block_id.strip() if isinstance(self.block_id, str) else ""
        if not _BLOCK_ID_PATTERN.fullmatch(block_id):
            raise DraftInputError(
                "block_id must be a lowercase slug (a-z, 0-9, '-') of at most "
                f"{MAX_BLOCK_ID_LENGTH} characters"
            )
        text = require_safe_text(f"block {block_id} text", self.text, MAX_BLOCK_TEXT_LENGTH)

        if len(self.claim_refs) > MAX_CLAIM_REFS_PER_BLOCK:
            raise DraftInputError(f"block {block_id} exceeds {MAX_CLAIM_REFS_PER_BLOCK} claim refs")
        claim_refs: list[str] = []
        for ref in self.claim_refs:
            if not isinstance(ref, uuid.UUID):
                raise DraftInputError(f"block {block_id} claim refs must be UUIDs")
            claim_refs.append(str(ref))
        if len(set(claim_refs)) != len(claim_refs):
            raise DraftInputError(f"block {block_id} repeats a claim ref")

        if len(self.uncertainty_refs) > MAX_UNCERTAINTY_REFS_PER_BLOCK:
            raise DraftInputError(
                f"block {block_id} exceeds {MAX_UNCERTAINTY_REFS_PER_BLOCK} uncertainty refs"
            )
        uncertainty_refs = [
            require_safe_text(f"block {block_id} uncertainty ref", ref, MAX_UNCERTAINTY_REF_LENGTH)
            for ref in self.uncertainty_refs
        ]
        if len(set(uncertainty_refs)) != len(uncertainty_refs):
            raise DraftInputError(f"block {block_id} repeats an uncertainty ref")

        if self.kind in _PLACEHOLDER_KINDS and claim_refs:
            raise DraftInputError(f"placeholder block {block_id} cannot carry claim refs")
        for ref_name, ref_value, required_kind in (
            ("link_need_ref", self.link_need_ref, DraftBlockKind.INTERNAL_LINK_NEED),
            ("media_need_ref", self.media_need_ref, DraftBlockKind.MEDIA_NEED),
        ):
            if self.kind is required_kind:
                if not isinstance(ref_value, int) or isinstance(ref_value, bool) or ref_value < 0:
                    raise DraftInputError(
                        f"block {block_id} ({self.kind.value}) requires a non-negative {ref_name}"
                    )
            elif ref_value is not None:
                raise DraftInputError(
                    f"block {block_id}: {ref_name} is only valid on {required_kind.value} blocks"
                )

        payload: dict[str, Any] = {
            "block_id": block_id,
            "kind": self.kind.value,
            "text": text,
            "claim_refs": claim_refs,
            "uncertainty_refs": uncertainty_refs,
        }
        if self.kind is DraftBlockKind.INTERNAL_LINK_NEED:
            payload["link_need_ref"] = self.link_need_ref
        if self.kind is DraftBlockKind.MEDIA_NEED:
            payload["media_need_ref"] = self.media_need_ref
        return payload


@dataclass(frozen=True, slots=True)
class DraftSection:
    """One ordered section; `key` must satisfy the brief's section contract."""

    key: str
    heading: str
    blocks: tuple[DraftBlock, ...]

    def cleaned(self) -> dict[str, Any]:
        key = self.key.strip() if isinstance(self.key, str) else ""
        if not key or len(key) > MAX_SECTION_KEY_LENGTH:
            raise DraftInputError(f"section key must be 1..{MAX_SECTION_KEY_LENGTH} characters")
        heading = require_safe_text(f"section {key} heading", self.heading, MAX_HEADING_LENGTH)
        if not self.blocks:
            raise DraftInputError(f"section {key} must contain at least one block")
        if len(self.blocks) > MAX_BLOCKS_PER_SECTION:
            raise DraftInputError(f"section {key} exceeds {MAX_BLOCKS_PER_SECTION} blocks")
        return {
            "key": key,
            "heading": heading,
            "blocks": [block.cleaned() for block in self.blocks],
        }


@dataclass(frozen=True, slots=True)
class DraftBodyInput:
    """The whole bounded body; the ONLY persistable draft content shape."""

    sections: tuple[DraftSection, ...] = field(default_factory=tuple)

    def cleaned(self) -> dict[str, Any]:
        if not self.sections:
            raise DraftInputError("a draft body must contain at least one section")
        if len(self.sections) > MAX_SECTIONS:
            raise DraftInputError(f"a draft body exceeds {MAX_SECTIONS} sections")
        sections = [section.cleaned() for section in self.sections]

        section_keys = [section["key"] for section in sections]
        if len(set(section_keys)) != len(section_keys):
            raise DraftInputError("section keys must be unique within a draft")

        block_ids: list[str] = []
        total_blocks = 0
        for section in sections:
            for block in section["blocks"]:
                block_ids.append(block["block_id"])
                total_blocks += 1
        if total_blocks > MAX_TOTAL_BLOCKS:
            raise DraftInputError(f"a draft body exceeds {MAX_TOTAL_BLOCKS} blocks")
        if len(set(block_ids)) != len(block_ids):
            raise DraftInputError("block ids must be unique across the whole draft")

        return {"schema": BODY_SCHEMA_VERSION, "sections": sections}
