from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import List, Dict, Any
import threading
import logging

logger = logging.getLogger("forgestore.config")


class Settings(BaseSettings):
    # For development, use SQLite. For production, set DATABASE_URL env to PostgreSQL
    database_url: str = "sqlite:///./forgestore.db"
    secret_key: str = "change-this-to-a-very-long-random-secret-key-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440  # 24 hours
    upload_dir: str = "app/static/uploads/products"

    # SMTP Settings for transactional emails
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    from_email: str = "noreply@forgestore.com"

    # Site branding (used in emails, templates)
    site_name: str = "ForgeStore"
    site_tagline: str = "Your One-Stop Marketplace"

    # Base URL for the site (used in emails, etc.)
    site_base_url: str = "http://127.0.0.1:8000"

    # Brevo API (replaces SMTP for sending transactional emails)
    # Generate an API v3 key from Brevo Dashboard -> Settings -> SMTP & API -> API Keys
    brevo_api_key: str = ""

    # Google OAuth
    google_client_id: str = ""
    google_client_secret: str = ""

    # Paystack payment gateway
    paystack_secret_key: str = ""
    paystack_public_key: str = ""

    # Flutterwave payment gateway (alternative to Paystack)
    flutterwave_secret_key: str = ""
    flutterwave_public_key: str = ""
    flutterwave_encryption_key: str = ""

    # Default payment provider ("paystack" or "flutterwave")
    default_payment_provider: str = "paystack"

    # Debug mode (set to "true" in development for detailed logging)
    debug: bool = False

    # Secure cookies: set to "true" in production (requires HTTPS)
    secure_cookies: bool = False

    # CORS: comma-separated allowed origins
    cors_origins: str = "http://127.0.0.1:8000,http://localhost:8000"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

    def validate_production(self):
        """Check that all required production settings are configured.
        Returns a list of warnings (empty if everything is fine).
        """
        warnings = []
        if self.database_url.startswith("sqlite"):
            warnings.append("DATABASE_URL is using SQLite — set to PostgreSQL for production")
        if "change-this-to" in self.secret_key.lower():
            warnings.append("SECRET_KEY is still the default value — generate a strong random key for production")
        if not self.smtp_host or not self.smtp_user:
            warnings.append("SMTP is not configured — transactional emails will print to console only")
        if not self.site_base_url or "127.0.0.1" in self.site_base_url:
            warnings.append("SITE_BASE_URL is set to localhost — update for production")
        if not self.brevo_api_key:
            warnings.append("BREVO_API_KEY is not set — transactional emails will use SMTP or fall back to console")
        if not self.paystack_secret_key:
            warnings.append("PAYSTACK_SECRET_KEY is not set — payment gateway will be unavailable")
        if not self.paystack_public_key:
            warnings.append("PAYSTACK_PUBLIC_KEY is not set — payment checkout page may fail")
        if not self.flutterwave_secret_key:
            warnings.append("FLUTTERWAVE_SECRET_KEY is not set — Flutterwave payment gateway will be unavailable")
        if not self.flutterwave_public_key:
            warnings.append("FLUTTERWAVE_PUBLIC_KEY is not set — Flutterwave checkout may fail")
        return warnings


@lru_cache()
def get_settings() -> Settings:
    settings = Settings()
    if not settings.debug:
        warnings = settings.validate_production()
        if warnings:
            logger.warning("⚠️  Production configuration warnings:")
            for w in warnings:
                logger.warning(f"  • {w}")
    return settings


# ─── Settings Cache ─────────────────────────────────────────────────

_site_settings_cache: Dict[str, str] = {}
_cache_valid = False
_cache_lock = threading.Lock()


def get_site_settings(db, force_refresh: bool = False) -> Dict[str, str]:
    """Get all site settings from DB as a flat dict, used across all templates.
    Cached to avoid querying the DB on every request. Thread-safe.
    """
    global _site_settings_cache, _cache_valid
    with _cache_lock:
        if not _cache_valid or force_refresh:
            from app.models import Settings as SettingsModel
            all_settings = db.query(SettingsModel).all()
            _site_settings_cache = {s.key: s.value for s in all_settings}
            _cache_valid = True
            logger.debug("Settings cache refreshed (%d settings)", len(_site_settings_cache))
    return _site_settings_cache


def invalidate_settings_cache():
    """Invalidate the site settings cache. Call after any settings update."""
    global _cache_valid
    with _cache_lock:
        _cache_valid = False
    logger.info("Settings cache invalidated")


def clear_all_caches():
    """Clear all caches including the env settings lru_cache."""
    get_settings.cache_clear()
    invalidate_settings_cache()
    logger.info("All config caches cleared")


def get_categorized_settings(db) -> Dict[str, List]:
    """Get all site settings organized by category."""
    from app.models import Settings as SettingsModel
    from app.services.ai_service import SETTINGS_DEFINITIONS

    db_settings = {s.key: s.value for s in db.query(SettingsModel).all()}

    # Build categorized dict
    categories: Dict[str, List] = {}
    for sd in SETTINGS_DEFINITIONS:
        cat = sd["category"]
        if cat not in categories:
            categories[cat] = []
        entry = dict(sd)
        entry["value"] = db_settings.get(sd["key"], sd.get("default", ""))
        categories[cat].append(entry)

    return categories
