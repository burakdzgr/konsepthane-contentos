"""Provider-neutral search-signal observation store (Phase 3 foundation).

Search signals are OBSERVATIONS, never current truth: multiple observations
for one subject legitimately coexist, and later consumers (scoring engine
versions, SearchIntentAnalysis) explicitly choose and pin exact signal IDs.
This module never collapses history into one authoritative number, never
touches opportunities/scores/workflow, and holds exactly one operational
provider today: the manual operator.
"""
