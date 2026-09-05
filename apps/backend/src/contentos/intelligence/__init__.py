"""Intelligence signals: ONE bounded durable store for role-specific signal
families extracted deterministically from normalized documents.

SOURCE -> ROLE-SPECIFIC SIGNAL EXTRACTION -> SIGNALS -> IDEA INTELLIGENCE ->
DEDUP/CLUSTERING -> OPPORTUNITY. Inspiration signals live in
``contentos.inspiration``; provider search/trend observations live in
``contentos.signals``. Everything else lands here, PII-free and bounded.
"""
