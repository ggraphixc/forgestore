import logging
import logging.config
import os
from datetime import datetime, timedelta

import dotenv

# Load environment variables from backend/.env
dotenv.load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

from fastapi import FastAPI, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from app.database import init_db, get_db
from app.routers import auth, admin, admin_api, web, web_api
from app.auth import get_current_user_from_cookie
from app.templates_shared import render_template

# ─── Logging Configuration ───────────────────────────────────────────

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "format": "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
        "json": {
            "format": '{"timestamp": "%(asctime)s", "logger": "%(name)s", "level": "%(levelname)s", "message": "%(message)s"}',
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "default",
            "level": "INFO",
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": "logs/forgestore.log",
            "formatter": "json",
            "maxBytes": 10 * 1024 * 1024,  # 10 MB
            "backupCount": 5,
            "level": "INFO",
        },
    },
    "root": {
        "handlers": ["console", "file"],
        "level": "INFO",
    },
    "loggers": {
        "forgestore": {"level": "INFO", "propagate": False},
        "uvicorn": {"level": "INFO", "propagate": False},
        "sqlalchemy.engine": {"level": "WARNING", "propagate": False},
    },
}

os.makedirs("logs", exist_ok=True)
logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger("forgestore")

# ─── Rate Limiter ───────────────────────────────────────────────────

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from app.routers import paystack_webhook
from app.config import get_settings

rate_limiter = Limiter(key_func=get_remote_address)

app = FastAPI(title="ForgeStore", version="1.0.0")
app.state.limiter = rate_limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ─── CORS Middleware ──────────────────────────────────────────────
from fastapi.middleware.cors import CORSMiddleware

_settings = get_settings()
origins = [
    origin.strip()
    for origin in _settings.cors_origins.split(",")
    if origin.strip()
]
# Always allow the site_base_url
if _settings.site_base_url and _settings.site_base_url not in origins:
    origins.append(_settings.site_base_url.rstrip("/"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins if origins else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

logger.info(f"CORS allowed origins: {origins if origins else ['*']}")

# Mount static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Include routers
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(admin_api.router)
app.include_router(web.router)
app.include_router(web_api.router)
app.include_router(paystack_webhook.router)


@app.on_event("startup")
def on_startup():
    init_db()
    logger.info("Database initialized")
    _cleanup_abandoned_carts()


def _cleanup_abandoned_carts():
    """Clean up cart items older than 30 days."""
    from app.database import SessionLocal
    from app.models import CartItem
    try:
        db = SessionLocal()
        cutoff = datetime.utcnow() - timedelta(days=30)
        deleted = db.query(CartItem).filter(
            CartItem.created_at < cutoff
        ).delete()
        db.commit()
        if deleted:
            logger.info("Cleaned up %d abandoned cart(s) older than 30 days", deleted)
        db.close()
    except Exception as e:
        logger.warning("Cart cleanup failed: %s", e)


@app.get("/", response_class=HTMLResponse)
def root(request: Request, db: Session = Depends(get_db)):
    """Redirect to web storefront or admin based on auth status."""
    admin = get_current_user_from_cookie(request, db)
    if admin:
        return RedirectResponse(url="/admin/dashboard", status_code=302)
    return RedirectResponse(url="/shop", status_code=302)


@app.get("/health")
def health():
    return {"status": "ok", "version": "1.0.0"}


@app.get("/api/debug/ip")
async def debug_ip(request: Request):
    """Debug endpoint to show the server's IP info (for Brevo SMTP authorization)."""
    import socket
    hostname = socket.gethostname()
    try:
        server_ip = socket.gethostbyname(hostname)
    except Exception:
        server_ip = "unknown"
    return {
        "hostname": hostname,
        "server_ip": server_ip,
        "client_ip": request.client.host if request.client else "unknown",
        "x_forwarded_for": request.headers.get("x-forwarded-for", ""),
        "x_real_ip": request.headers.get("x-real-ip", ""),
    }
