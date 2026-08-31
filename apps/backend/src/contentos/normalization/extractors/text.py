"""Deterministic bounded extractor for text/plain payloads."""

import re

from contentos.normalization.extractors.base import (
    MAX_CLEAN_TEXT_CHARS,
    MAX_TITLE_CHARS,
    ExtractedDocument,
    ExtractionContext,
    ExtractorEmptyContentError,
    ExtractorPolicyError,
    decode_payload,
)

_HORIZONTAL_WHITESPACE = re.compile(r"[\t\f\v ]+")


class PlainTextExtractor:
    """Decode strict text and use the first meaningful line as an optional title."""

    name = "text-basic"
    version = "1"
    parser_version = "python-text-v1"
    supported_media_types = frozenset({"text/plain"})

    def extract(self, payload: bytes, context: ExtractionContext) -> ExtractedDocument:
        text = decode_payload(payload, context.content_type, inspect_html=False)
        normalized_lines: list[str] = []
        previous_blank = True
        for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            line = _HORIZONTAL_WHITESPACE.sub(" ", raw_line).strip()
            if line:
                normalized_lines.append(line)
                previous_blank = False
            elif not previous_blank and normalized_lines:
                normalized_lines.append("")
                previous_blank = True
        while normalized_lines and not normalized_lines[-1]:
            normalized_lines.pop()
        clean_text = "\n".join(normalized_lines)
        if not clean_text:
            raise ExtractorEmptyContentError("text payload contains no usable text")
        if len(clean_text) > MAX_CLEAN_TEXT_CHARS:
            raise ExtractorPolicyError("clean text exceeds the extractor limit")
        title = next((line for line in normalized_lines if line), None)
        if title is not None:
            title = title[:MAX_TITLE_CHARS]
        return ExtractedDocument(
            title=title,
            clean_text=clean_text,
            parser_version=self.parser_version,
        )
