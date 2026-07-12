from typing import Optional, Dict, Any
from contextvars import ContextVar
from jinja2 import Environment, FileSystemLoader, select_autoescape
from fastapi.responses import HTMLResponse

# Use raw Jinja2 Environment to avoid Starlette 1.0.0 Jinja2Templates compatibility issues
env = Environment(
    loader=FileSystemLoader("app/templates"),
    autoescape=select_autoescape(["html", "xml"]),
    enable_async=False,
)

# Context variable for automatic DB session injection into templates
_current_db: ContextVar = ContextVar('_current_db', default=None)


def set_current_db(db):
    """Set the current DB session for template rendering. Called per-request."""
    _current_db.set(db)


def get_current_db():
    """Get the current DB session from context."""
    return _current_db.get()


def _escapejs(value):
    """Escape a string for JavaScript string literal inclusion (safe for single/double quoted strings)."""
    if value is None:
        return ''
    value = str(value)
    value = value.replace('\\', '\\\\')
    value = value.replace("'", "\\'")
    value = value.replace('"', '\\"')
    value = value.replace('\n', '\\n')
    value = value.replace('\r', '\\r')
    value = value.replace('\t', '\\t')
    value = value.replace('</', '<\\/')
    return value


env.filters['escapejs'] = _escapejs


def _get_fallback_settings():
    """Return Pydantic settings as a plain dict for global template use."""
    from app.config import get_settings
    s = get_settings()
    return {
        "site_name": s.site_name,
        "site_tagline": s.site_tagline,
        "site_base_url": s.site_base_url,
        "brevo_api_key": s.brevo_api_key,
        "mail_from_email": s.mail_from_email,
        "debug": s.debug,
        "default_payment_provider": s.default_payment_provider,
    }


def _get_full_settings_from_db(db):
    """Get full site settings from the database."""
    try:
        from app.config import get_site_settings
        return get_site_settings(db)
    except Exception:
        return _get_fallback_settings()


env.globals["site_settings_fallback"] = _get_fallback_settings


def _format_price_global(amount: float, currency: str = "NGN") -> str:
    """Jinja2 global: format price with full i18n support from DB settings."""
    symbols = {"NGN": "₦", "USD": "$", "GBP": "£", "EUR": "€"}
    symbol = symbols.get(currency, "₦")
    position = "before"
    decimal_places = 2
    thousand_sep = ","
    decimal_sep = "."
    db = get_current_db()
    if db is not None:
        try:
            from app.services.ai_service import get_setting
            symbol = get_setting(db, "currency_symbol", symbol)
            position = get_setting(db, "currency_symbol_position", "before")
            decimal_places = int(get_setting(db, "currency_decimal_places", "2"))
            thousand_sep = get_setting(db, "currency_thousand_separator", ",")
            decimal_sep = get_setting(db, "currency_decimal_separator", ".")
        except Exception:
            pass
    formatted = f"{amount:,.{decimal_places}f}"
    if thousand_sep != "," or decimal_sep != ".":
        formatted = formatted.replace(",", "T").replace(".", "D")
        formatted = formatted.replace("T", thousand_sep).replace("D", decimal_sep)
    if position == "after":
        return f"{formatted}{symbol}"
    return f"{symbol}{formatted}"


env.globals["format_price"] = _format_price_global


def render_template(template_name: str, context: Optional[Dict[str, Any]] = None, status_code: int = 200, **kwargs):
    """Render a Jinja2 template and return an HTMLResponse.

    Automatically injects full site settings from DB into every render.
    DB session is obtained from contextvars (set per-request by middleware).
    Templates always have access to settings.* for branding, features, etc.
    """
    ctx = {}
    if context:
        ctx.update(context)
    if kwargs:
        ctx.update(kwargs)

    # Auto-inject settings if `settings` not already provided
    if "settings" not in ctx:
        db = get_current_db()
        if db is not None:
            ctx["settings"] = _get_full_settings_from_db(db)
        else:
            ctx["settings"] = _get_fallback_settings()

    template = env.get_template(template_name)
    html = template.render(**ctx)
    return HTMLResponse(content=html, status_code=status_code)
