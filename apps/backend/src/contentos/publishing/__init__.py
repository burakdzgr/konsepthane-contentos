"""Phase 7 publishing domain: the ContentOS side of publication.

Publish exactly what was approved, or nothing: immutable, hashed
publication packages assembled ONLY from the pinned approved artifacts
under the `require_current_approval` guard. Konsepthane is reachable
only through the versioned + authenticated + idempotent Publishing API
(the transport boundary); no filesystem or database of production is
ever touched.
"""
