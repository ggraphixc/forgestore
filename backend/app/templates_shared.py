from typing import Optional, Dict, Any
from jinja2 import Environment, FileSystemLoader, select_autoescape
from fastapi.responses import HTMLResponse

# Use raw Jinja2 Environment to avoid Starlette 1.0.0 Jinja2Templates compatibility issues
env = Environment(
    loader=FileSystemLoader("app/templates"),
    autoescape=select_autoescape(["html", "xml"]),
    enable_async=False,
)


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
