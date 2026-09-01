"""Editorial opportunities and Phase 2 -> Phase 3 research promotion.

This module reads Phase 2 primitives (normalization, duplicates, discovery,
sources) and calls the workflow foundation; Phase 2 modules never import it
and `contentos.workflow` never imports back. It stores references only —
never payloads, article bodies, clean text, or evidence text.
"""
