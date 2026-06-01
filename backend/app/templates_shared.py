from typing import Optional, Dict, Any
from jinja2 import Environment, FileSystemLoader, select_autoescape
from fastapi.responses import HTMLResponse

# Use raw Jinja2 Environment to avoid Starlette 1.0.0 Jinja2Templates compatibility issues
env = Environment(
    loader=FileSystemLoader("app/templates"),
    autoescape=select_autoescape(["html", "xml"]),
    enable_async=False,
)


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


def _get_global_context(db_session):
    """Ensures baseline layout context dependencies are consistently satisfied."""
    try:
        from app.config import get_site_settings
        return get_site_settings(db_session)
    except Exception:
        return _get_fallback_settings()


env.globals["site_settings_fallback"] = _get_fallback_settings
env.globals["get_global_context"] = _get_global_context


def render_template(template_name: str, context: Optional[Dict[str, Any]] = None, status_code: int = 200, **kwargs):
    """Render a Jinja2 template and return an HTMLResponse.

    Supports both dict context (legacy) and keyword arguments.
    Automatically injects site_settings_fallback into every render
    so templates never crash from missing `settings` variable.
    """
    ctx = {}
    if context:
        ctx.update(context)
    if kwargs:
        ctx.update(kwargs)

    # Auto-inject fallback settings if `settings` not already provided
    if "settings" not in ctx:
        ctx["settings"] = _get_fallback_settings()

    template = env.get_template(template_name)
    html = template.render(**ctx)
    return HTMLResponse(content=html, status_code=status_code)
