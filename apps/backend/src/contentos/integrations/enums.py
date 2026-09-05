"""Provider vocabulary. Values are persistence and API contracts; never rename."""

from enum import StrEnum


class ProviderState(StrEnum):
    """Honest health of one external provider as last observed."""

    HEALTHY = "healthy"
    NOT_CONFIGURED = "not_configured"
    ACCESS_REQUIRED = "access_required"
    RATE_LIMITED = "rate_limited"
    DEGRADED = "degraded"
    ERROR = "error"


class ProviderName(StrEnum):
    """The governed set of external intelligence providers."""

    SEMRUSH = "semrush"
    GOOGLE_SEARCH_CONSOLE = "google_search_console"
    GOOGLE_ANALYTICS = "google_analytics"
    GOOGLE_TRENDS = "google_trends"
    PINTEREST_TRENDS = "pinterest_trends"


# Operator-facing names (Turkish UI keeps product names as they are).
DISPLAY_NAMES: dict[ProviderName, str] = {
    ProviderName.SEMRUSH: "Semrush",
    ProviderName.GOOGLE_SEARCH_CONSOLE: "Google Search Console",
    ProviderName.GOOGLE_ANALYTICS: "Google Analytics 4",
    ProviderName.GOOGLE_TRENDS: "Google Trends",
    ProviderName.PINTEREST_TRENDS: "Pinterest Trends",
}

# The exact environment variables an operator sets per provider (names only;
# values never leave Settings). Shown in the admin as configuration hints.
REQUIRED_ENV: dict[ProviderName, tuple[str, ...]] = {
    ProviderName.SEMRUSH: ("CONTENTOS_SEMRUSH_API_KEY",),
    ProviderName.GOOGLE_SEARCH_CONSOLE: (
        "CONTENTOS_GOOGLE_SERVICE_ACCOUNT_JSON",
        "CONTENTOS_GSC_SITE_URL",
    ),
    ProviderName.GOOGLE_ANALYTICS: (
        "CONTENTOS_GOOGLE_SERVICE_ACCOUNT_JSON",
        "CONTENTOS_GA4_PROPERTY_ID",
    ),
    ProviderName.GOOGLE_TRENDS: ("CONTENTOS_GOOGLE_TRENDS_API_KEY",),
    ProviderName.PINTEREST_TRENDS: ("CONTENTOS_PINTEREST_ACCESS_TOKEN",),
}

OPTIONAL_ENV: dict[ProviderName, tuple[str, ...]] = {
    ProviderName.SEMRUSH: (
        "CONTENTOS_SEMRUSH_DATABASE",
        "CONTENTOS_SEMRUSH_DAILY_BUDGET",
        "CONTENTOS_SEMRUSH_CACHE_HOURS",
    ),
    ProviderName.GOOGLE_SEARCH_CONSOLE: (
        "CONTENTOS_GSC_DAILY_BUDGET",
        "CONTENTOS_GSC_CACHE_HOURS",
    ),
    ProviderName.GOOGLE_ANALYTICS: (
        "CONTENTOS_GA4_KEY_EVENTS",
        "CONTENTOS_GA4_DAILY_BUDGET",
        "CONTENTOS_GA4_CACHE_HOURS",
    ),
    ProviderName.GOOGLE_TRENDS: (
        "CONTENTOS_GOOGLE_TRENDS_API_URL",
        "CONTENTOS_GOOGLE_TRENDS_DAILY_BUDGET",
        "CONTENTOS_GOOGLE_TRENDS_CACHE_HOURS",
    ),
    ProviderName.PINTEREST_TRENDS: (
        "CONTENTOS_PINTEREST_REGION",
        "CONTENTOS_PINTEREST_DAILY_BUDGET",
        "CONTENTOS_PINTEREST_CACHE_HOURS",
    ),
}

# What each provider is FOR — one Turkish sentence the operator sees.
PURPOSES: dict[ProviderName, str] = {
    ProviderName.SEMRUSH: (
        "Dış SEO pazar istihbaratı: arama hacmi, anahtar kelime zorluğu, ilgili "
        "sorgular. Search Console gerçeğinin yerine geçmez."
    ),
    ProviderName.GOOGLE_SEARCH_CONSOLE: (
        "Kendi gerçek performansımız: tıklama, gösterim, TO ve konum."
    ),
    ProviderName.GOOGLE_ANALYTICS: (
        "Site içi davranış: kullanıcı, oturum, görüntüleme, etkileşim."
    ),
    ProviderName.GOOGLE_TRENDS: ("Göreli ilgi eğilimi (0-100 ölçeği); mutlak hacim değildir."),
    ProviderName.PINTEREST_TRENDS: (
        "Görsel/fikir eğilimleri: Pinterest'te yükselen anahtar kelimeler."
    ),
}
