"""Strict Writer output schema (`writer-draft/1`).

The model emits EXACTLY the bounded body shape the draft stores (minus
every system-owned field): sections keyed to the brief contract, typed
blocks with inline text, per-block claim and handling references. Ids,
versions, hashes, policy snapshots, coverage results, status, and engine
identity are NOT part of this schema — smuggling is schema-rejected.
Evidence ids are not even in the vocabulary: the model references CLAIMS,
never evidence directly (provenance resolves through the brief).
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from contentos.drafts.values import (
    MAX_BLOCK_ID_LENGTH,
    MAX_BLOCK_TEXT_LENGTH,
    MAX_BLOCKS_PER_SECTION,
    MAX_CLAIM_REFS_PER_BLOCK,
    MAX_HEADING_LENGTH,
    MAX_SECTION_KEY_LENGTH,
    MAX_SECTIONS,
    MAX_TITLE_PROPOSAL_LENGTH,
    MAX_UNCERTAINTY_REF_LENGTH,
    MAX_UNCERTAINTY_REFS_PER_BLOCK,
)

WRITER_DRAFT_SCHEMA_NAME = "writer-draft"
WRITER_DRAFT_SCHEMA_VERSION = "1"
WRITER_DRAFT_INPUT_REFS_SCHEMA = "writer-draft/1"

BlockId = Annotated[
    str,
    StringConstraints(
        min_length=1, max_length=MAX_BLOCK_ID_LENGTH, pattern=r"^[a-z0-9][a-z0-9-]{0,63}$"
    ),
]
BlockText = Annotated[str, StringConstraints(min_length=1, max_length=MAX_BLOCK_TEXT_LENGTH)]
HandlingRef = Annotated[str, StringConstraints(min_length=1, max_length=MAX_UNCERTAINTY_REF_LENGTH)]
ClaimRef = Annotated[str, StringConstraints(min_length=36, max_length=36)]

BlockKindLiteral = Literal[
    "paragraph",
    "list",
    "how_to_step",
    "callout",
    "faq_item",
    "internal_link_need",
    "media_need",
]


class WriterBlockV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    block_id: BlockId
    kind: BlockKindLiteral
    text: BlockText
    claim_refs: list[ClaimRef] = Field(default_factory=list, max_length=MAX_CLAIM_REFS_PER_BLOCK)
    uncertainty_refs: list[HandlingRef] = Field(
        default_factory=list, max_length=MAX_UNCERTAINTY_REFS_PER_BLOCK
    )
    link_need_ref: int | None = Field(default=None, ge=0, le=50)
    media_need_ref: int | None = Field(default=None, ge=0, le=50)


class WriterSectionV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: Annotated[str, StringConstraints(min_length=1, max_length=MAX_SECTION_KEY_LENGTH)]
    heading: Annotated[str, StringConstraints(min_length=1, max_length=MAX_HEADING_LENGTH)]
    blocks: list[WriterBlockV1] = Field(min_length=1, max_length=MAX_BLOCKS_PER_SECTION)


class WriterDraftV1(BaseModel):
    """The whole Writer output contract — never a raw string."""

    model_config = ConfigDict(extra="forbid")

    title_proposal: (
        Annotated[str, StringConstraints(min_length=1, max_length=MAX_TITLE_PROPOSAL_LENGTH)] | None
    ) = None
    sections: list[WriterSectionV1] = Field(min_length=1, max_length=MAX_SECTIONS)
