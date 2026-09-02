"""QA constants (PHASE4_QA_ARCHITECTURE.md §3/§4)."""

QA_ENGINE_NAME = "qa"
QA_ENGINE_VERSION = "1"

# v2 (Phase 6 M3): media_needs learns `satisfied` and lists exact unmet
# indexes. Old reports stay truthful under their recorded `qa-gates/1`.
QA_GATE_POLICY_VERSION = "qa-gates/2"

MAX_REASON_LENGTH = 1000
