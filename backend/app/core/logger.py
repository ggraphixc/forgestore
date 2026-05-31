"""
Structured JSON Observability Logger — production-grade logging with request context.

Outputs structured JSON logs to both stderr and a rotating log file.
Every log entry includes: timestamp, level, module, message, request_id,
route, user_id, duration_ms, and extra context fields.
"""
import sys
import os
import json
import time
import logging
import logging.handlers
import uuid
from contextvars import ContextVar
from typing import Optional

# Context variables for request-scoped logging
request_id_var: ContextVar[str] = ContextVar("request_id", default="")
user_id_var: ContextVar[str] = ContextVar("user_id", default="")
route_var: ContextVar[str] = ContextVar("route", default="")


class JSONFormatter(logging.Formatter):
    """Formats log records as structured JSON lines."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add request context
        req_id = request_id_var.get("")
        if req_id:
            log_entry["request_id"] = req_id
        uid = user_id_var.get("")
        if uid:
            log_entry["user_id"] = uid
        rt = route_var.get("")
        if rt:
            log_entry["route"] = rt

        # Add extra fields from record
        for key in ("duration_ms", "status_code", "method", "path",
                     "error_type", "provider", "order_id", "vendor_id",
                     "amount", "event_type"):
            val = getattr(record, key, None)
            if val is not None:
                log_entry[key] = val

        # Add exception info
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
                "traceback": self.formatException(record.exc_info),
            }

        return json.dumps(log_entry, default=str, ensure_ascii=False)


def setup_structured_logging(
    log_dir: str = "logs",
    log_file: str = "forgestore_production.log",
    level: str = "INFO",
):
    """
    Configure structured JSON logging to stderr and a rotating file.
    Call once at application startup.
    """
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, log_file)

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove existing handlers
    for h in root.handlers[:]:
        root.removeHandler(h)

    formatter = JSONFormatter()

    # Stderr handler
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(formatter)
    stderr_handler.setLevel(logging.INFO)
    root.addHandler(stderr_handler)

    # Rotating file handler (10MB, 5 backups)
    file_handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)
    root.addHandler(file_handler)

    # Silence noisy libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    logging.info("Structured JSON logging initialized — file: %s", log_path)


def log_request_context(request_id: str = None, user_id: str = None, route: str = None):
    """Set request-scoped context variables for the current execution."""
    if request_id:
        request_id_var.set(request_id)
    if user_id:
        user_id_var.set(user_id)
    if route:
        route_var.set(route)


def generate_request_id() -> str:
    """Generate a short unique request tracking ID."""
    return uuid.uuid4().hex[:12]


class RequestTimingMiddleware:
    """ASGI middleware that adds request_id, timing, and structured log entry per request."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        req_id = generate_request_id()
        start = time.monotonic()
        path = scope.get("path", "")
        method = scope.get("method", "")

        log_request_context(request_id=req_id, route=f"{method} {path}")

        status_code = 500

        async def send_wrapper(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 500)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = round((time.monotonic() - start) * 1000, 1)
            logger = logging.getLogger("forgestore.request")
            logger.info(
                "Request completed",
                extra={
                    "request_id": req_id,
                    "method": method,
                    "path": path,
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                },
            )
