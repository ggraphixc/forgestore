"""
Outbound Webhook Service

Delivers HTTP POST notifications to a configured webhook URL on key events.
Uses httpx for async delivery with retry logic.
"""

import logging
import json
import asyncio
from typing import Optional

logger = logging.getLogger("forgestore.webhooks")


def _get_webhook_config():
    """Read webhook settings from DB."""
    try:
        from app.database import SessionLocal
        from app.models import Settings as SettingsModel
        db = SessionLocal()
        url_setting = db.query(SettingsModel).filter(SettingsModel.key == "webhook_url").first()
        secret_setting = db.query(SettingsModel).filter(SettingsModel.key == "webhook_secret").first()
        enabled_setting = db.query(SettingsModel).filter(SettingsModel.key == "webhook_enabled").first()
        db.close()
        url = url_setting.value if url_setting and url_setting.value else ""
        secret = secret_setting.value if secret_setting and secret_setting.value else ""
        enabled = not enabled_setting or enabled_setting.value.lower() != "false"
        return url, secret, enabled
    except Exception:
        return "", "", True


def _sign_payload(payload_bytes: bytes, secret: str) -> str:
    """HMAC-SHA256 signature for webhook payload."""
    import hmac
    import hashlib
    if not secret:
        return ""
    return hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()


def dispatch_webhook(event: str, data: dict, retries: int = 3):
    """Send a webhook POST to the configured URL.

    Args:
        event: Event name (e.g., "order.created", "order.status_changed")
        data: Payload dict
        retries: Number of retry attempts on failure
    """
    url, secret, enabled = _get_webhook_config()
    if not enabled or not url:
        return

    payload = {
        "event": event,
        "data": data,
    }
    payload_bytes = json.dumps(payload, default=str).encode()
    headers = {"Content-Type": "application/json"}
    if secret:
        headers["X-Webhook-Signature"] = _sign_payload(payload_bytes, secret)

    def _send():
        import httpx
        for attempt in range(retries):
            try:
                with httpx.Client(timeout=10) as client:
                    resp = client.post(url, content=payload_bytes, headers=headers)
                    if resp.status_code < 300:
                        logger.info("Webhook delivered: %s -> %d", event, resp.status_code)
                        return True
                    else:
                        logger.warning("Webhook %d -> %d: %s", attempt+1, resp.status_code, resp.text[:200])
            except Exception as exc:
                logger.warning("Webhook %d -> error: %s", attempt+1, str(exc))
        logger.error("Webhook failed after %d attempts: %s", retries, event)
        return False

    # Fire and forget in background
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(asyncio.to_thread(_send))
        else:
            loop.run_in_executor(None, _send)
    except RuntimeError:
        asyncio.to_thread(_send)


def notify_order_created(order):
    """Dispatch webhook for new order."""
    dispatch_webhook("order.created", {
        "order_id": order.id,
        "total": order.total_amount,
        "customer_id": order.customer_id,
        "status": order.status,
        "created_at": str(order.created_at),
    })


def notify_order_status_changed(order, old_status: str, new_status: str):
    """Dispatch webhook for order status change."""
    dispatch_webhook("order.status_changed", {
        "order_id": order.id,
        "old_status": old_status,
        "new_status": new_status,
        "total": order.total_amount,
        "updated_at": str(order.updated_at),
    })


def notify_payment_received(order, amount: float):
    """Dispatch webhook for payment received."""
    dispatch_webhook("payment.received", {
        "order_id": order.id,
        "amount": amount,
        "total": order.total_amount,
        "status": order.status,
    })
