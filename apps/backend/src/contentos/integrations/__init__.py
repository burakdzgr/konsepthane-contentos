"""External intelligence providers (Semrush, Google Search Console, GA4,
Google Trends, Pinterest Trends).

Every provider is an adapter over the vendor's OFFICIAL API, constructed
from Settings, and degrades to an honest state (`not_configured`,
`access_required`, `rate_limited`, `degraded`, `error`) instead of
fabricating data. Nothing here scrapes a website. Observations are
persisted as provenance-complete SearchSignal rows; secrets never leave
Settings.
"""
