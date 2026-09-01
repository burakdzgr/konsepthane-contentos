"""Canonical editorial workflow aggregate (Phase 3 foundation).

Owns the durable EditorialWorkItem spine and its append-only transition
events. This module knows the canonical WORKFLOW.md state machine and
nothing else: no Phase 2 lookups, no opportunity/evidence/brief gates, no
queue awareness. Stage-specific eligibility lives in later Phase 3 modules.
"""
