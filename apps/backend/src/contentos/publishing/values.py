"""Publishing constants (PHASE7_PUBLISHING_ARCHITECTURE.md §3/§4)."""

PACKAGE_SCHEMA_VERSION = "publication-package/1"

# Bounded execution-fact vocabulary. No editorial words: an attempt can
# fail, it can never "reject content".
ATTEMPT_STATUSES = ("succeeded", "transport_error", "rejected_by_api", "timeout")

MAX_ERROR_CLASS_LENGTH = 100
MAX_TRANSPORT_NAME_LENGTH = 100
