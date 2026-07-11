import logging
import logging.config
import os
from datetime import timedelta
from app.utils import utcnow

import dotenv

# Load environment variables from backend/.env
dotenv.load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

from fastapi import FastAPI, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from app.database import init_db, get_db
from app.models import Settings
from app.routers import auth, admin, admin_api, web, web_api
from app.routers import vendor_portal, logistics_portal
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

# New enterprise system routers
from app.routers.api_admin_ext import router as api_admin_ext_router
from app.routers.api_web_ext import router as api_web_ext_router
from app.routers.api_shipment import router as api_shipment_router

app.include_router(api_admin_ext_router)
app.include_router(api_web_ext_router)
app.include_router(api_shipment_router)
app.include_router(vendor_portal.router)
app.include_router(logistics_portal.router)

# New system routers: Chat, Disputes, AI Assistant
from app.routers.chat import router as chat_router
from app.routers.disputes import router as disputes_router
from app.routers.search import router as search_router
from app.routers.orders import router as orders_router
from app.routers.ai_assistant import router as ai_assistant_router
app.include_router(chat_router)
app.include_router(disputes_router)
app.include_router(search_router)
app.include_router(orders_router)
app.include_router(ai_assistant_router)

# Support ticket system
from app.routers.support import router as support_router
app.include_router(support_router)

# Structured logging middleware
from app.core.logger import RequestTimingMiddleware, setup_structured_logging
setup_structured_logging()
app.add_middleware(RequestTimingMiddleware)


class MaintenanceModeMiddleware:
    """Block non-admin access when maintenance_mode setting is enabled."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        from app.database import SessionLocal
        from app.models import Settings as SettingsModel
        from app.auth import get_current_user_from_cookie
        is_maintenance = False
        try:
            db = SessionLocal()
            setting = db.query(SettingsModel).filter(SettingsModel.key == "maintenance_mode").first()
            is_maintenance = setting and setting.value == "true"
            db.close()
        except Exception:
            pass

        if is_maintenance:
            admin = None
            try:
                from starlette.requests import Request as StarletteRequest
                request = StarletteRequest(scope, receive)
                db2 = SessionLocal()
                admin = get_current_user_from_cookie(request, db2)
                db2.close()
            except Exception:
                pass

            if not admin:
                from fastapi.responses import HTMLResponse
                try:
                    from app.config import get_settings
                    cfg = get_settings()
                    from app.templates_shared import render_template
                    return await render_template("maintenance.html", {
                        "request": request,
                        "site_name": cfg.site_name,
                        "admin": None,
                    })
                except Exception:
                    return await HTMLResponse(
                        '<html><body style="font-family:sans-serif;text-align:center;padding:4rem;"><h1>Maintenance</h1><p>We\'ll be back soon.</p></body></html>',
                        status_code=503,
                    ).__call__(scope, receive, send)

        return await self.app(scope, receive, send)


app.add_middleware(MaintenanceModeMiddleware)


@app.get("/ws", include_in_schema=False)
async def websocket_endpoint(request: Request):
    """WebSocket endpoint for real-time updates.
    Use the WebSocket URL: ws://host/ws?channel=CHANNEL_NAME
    """
    from fastapi.responses import HTMLResponse
    # SSO-based WebSocket handshake handled via app/core/websocket_manager.py
    return HTMLResponse("WebSocket endpoint active — use WebSocket protocol")


@app.on_event("startup")
def on_startup():
    init_db()
    logger.info("Database initialized")
    _run_migrations()
    _seed_default_settings()
    _cleanup_abandoned_carts()


def _run_migrations():
    """Run pending database migrations on startup."""
    try:
        from migrations.run_migration import run_pending_migrations
        run_pending_migrations(print_func=logger.info)
        logger.info("Pending migrations applied successfully")
    except ImportError as e:
        logger.warning("Migrations module not available: %s", e)
    except Exception as e:
        logger.warning("Migration runner failed (may be harmless): %s", e)


def _seed_default_settings():
    """Seed any missing settings with their default values from SETTINGS_DEFINITIONS."""
    try:
        from app.database import SessionLocal
        from app.services.ai_service import SETTINGS_DEFINITIONS
        db = SessionLocal()
        try:
            existing_keys = {row[0] for row in db.query(Settings.key).all()}
            to_add = []
            for sd in SETTINGS_DEFINITIONS:
                if sd["key"] not in existing_keys:
                    to_add.append(Settings(
                        key=sd["key"],
                        value=sd.get("default", ""),
                        category=sd["category"],
                        setting_type=sd["type"],
                        label=sd["label"],
                        description=sd.get("description", ""),
                        options=sd.get("options"),
                    ))
            if to_add:
                db.bulk_save_objects(to_add)
                db.commit()
                logger.info("Seeded %d default settings", len(to_add))
        finally:
            db.close()
    except Exception as e:
        logger.warning("Settings seeding failed (may be harmless): %s", e)


def _cleanup_abandoned_carts():
    """Clean up cart items older than 30 days."""
    from app.database import SessionLocal
    from app.models import CartItem
    try:
        db = SessionLocal()
        cutoff = utcnow() - timedelta(days=30)
        deleted = db.query(CartItem).filter(
            CartItem.created_at < cutoff
        ).delete()
        db.commit()
        if deleted:
            logger.info("Cleaned up %d abandoned cart(s) older than 30 days", deleted)
        db.close()
    except Exception as e:
        logger.warning("Cart cleanup failed: %s", e)


# ===== WebSocket Event Handler =====
from app.core.websocket_manager import ws_manager


@app.websocket("/ws/{channel:path}")
async def websocket_route(websocket, channel: str = ""):
    """WebSocket endpoint for real-time event streaming.
    
    Channels:
        - admin:orders    — Order status updates
        - admin:shipments — Shipment tracking updates
        - admin:alerts    — Admin dashboard alerts
        - order:{id}      — Specific order tracking (customer)
        - shipment:{id}   — Specific shipment tracking
        - chat:{product_id} — Live product chat
    """
    from fastapi import WebSocket
    await ws_manager.connect(websocket, channel)
    try:
        while True:
            # Keep connection alive — handle incoming pings or messages
            data = await websocket.receive_text()
            # Client can send "ping" to keep alive
            if data == "ping":
                await websocket.send_text('{"type":"pong"}')
    except Exception:
        pass
    finally:
        await ws_manager.disconnect(websocket)


@app.get("/", response_class=HTMLResponse)
def root(request: Request, db: Session = Depends(get_db)):
    """Redirect to correct portal based on auth status and role."""
    admin = get_current_user_from_cookie(request, db)
    if admin:
        role = admin.role.value if hasattr(admin.role, 'value') else admin.role
        if role == "RETAILER":
            return RedirectResponse(url="/vendor/dashboard", status_code=302)
        elif role == "LOGISTICS":
            return RedirectResponse(url="/logistics/dashboard", status_code=302)
        else:
            return RedirectResponse(url="/admin/dashboard", status_code=302)
    return RedirectResponse(url="/shop", status_code=302)


@app.get("/health")
def health():
    return {"status": "ok", "version": "1.0.0"}


@app.get("/api/debug/ip")
def debug_ip():
    """Detect the server's public outbound IP (for Brevo SMTP authorization).
    Makes an outbound HTTP request to api.ipify.org — this shows the
    actual IP address that Brevo's SMTP server sees when we connect.
    """
    import requests
    try:
        outbound_ip = requests.get("https://api.ipify.org", timeout=5).text.strip()
    except Exception as e:
        outbound_ip = f"could not determine: {e}"
    return {
        "outbound_ip": outbound_ip,
        "note": "Authorize this IP in Brevo Dashboard → Settings → Security → Authorized IPs",
    }
