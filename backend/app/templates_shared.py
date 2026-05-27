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


def render_template(template_name: str, context: Optional[Dict[str, Any]] = None, status_code: int = 200, **kwargs):
    """Render a Jinja2 template and return an HTMLResponse.
    
    Supports both dict context (legacy) and keyword arguments.
    """
    ctx = {}
    if context:
        ctx.update(context)
    if kwargs:
        ctx.update(kwargs)
    
    template = env.get_template(template_name)
    html = template.render(**ctx)
    return HTMLResponse(content=html, status_code=status_code)
