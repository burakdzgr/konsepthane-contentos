"""EvidencePack foundation (Phase 3): provenance-preserving research packs.

A pack is an editorial research artifact assembled from existing
ResearchEvidence rows. It is never copied source text, a source dump, a URL
list, or an AI summary treated as evidence: every item carries a mandatory
NOT NULL RESTRICT reference to its ResearchEvidence row, so the full
ADR 0007 chain (evidence -> document -> snapshot -> item -> source) stays
resolvable for every consumer. Phase 2 modules never import this one.
"""
