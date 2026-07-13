"""
SMS Service — outbound SMS notifications via Termii (Nigeria) or generic HTTP provider.

Settings (from admin Settings table):
  sms_enabled, sms_provider, sms_api_key, sms_sender_id,
  sms_api_url, sms_template_order, sms_template_shipping,
  sms_template_delivery, sms_template_otp

Fallback: console logging when SMS is not configured.
"""

import logging
import json
from typing import Optional

logger = logging.getLogger("forgestore.sms")


def _get_sms_config():
    """Read SMS settings from DB."""
    config = {
        "enabled": False,
        "provider": "termii",
        "api_key": "",
        "sender_id": "ForgeStore",
        "api_url": "https://api.termii.com/api/sms/send",
        "templates": {
            "order": "Your order {order_number} has been confirmed. Total: ₦{total}. Track at {tracking_url}",
            "shipping": "Your order {order_number} has been shipped! Tracking: {tracking_number}. Track: {tracking_url}",
            "delivery": "Your order {order_number} has been delivered. Thank you for shopping with {site_name}!",
            "otp": "Your verification code is {code}. It expires in 5 minutes.",
        },
    }
    try:
        from app.database import SessionLocal
        from app.models import Settings as SettingsModel
        db = SessionLocal()
        key_map = {
            "sms_enabled": "enabled",
            "sms_provider": "provider",
            "sms_api_key": "api_key",
            "sms_sender_id": "sender_id",
            "sms_api_url": "api_url",
            "sms_template_order": ("templates", "order"),
            "sms_template_shipping": ("templates", "shipping"),
            "sms_template_delivery": ("templates", "delivery"),
            "sms_template_otp": ("templates", "otp"),
        }
        for db_key, cfg_key in key_map.items():
            setting = db.query(SettingsModel).filter(SettingsModel.key == db_key).first()
            if setting and setting.value:
                if isinstance(cfg_key, tuple):
                    config[cfg_key[0]][cfg_key[1]] = setting.value
                else:
                    config[cfg_key] = setting.value
        if config["api_key"]:
            config["enabled"] = True
        db.close()
    except Exception:
        pass
    return config


def send_sms(phone: str, message: str) -> bool:
    """Send an SMS message.

    Returns True if sent successfully, False otherwise.
    """
    config = _get_sms_config()
    if not config["enabled"] or not phone:
        logger.info("SMS (console): to=%s message=%s", phone, message)
        return False

    try:
        import httpx

        if config["provider"] == "termii":
            payload = {
                "to": phone,
                "from": config["sender_id"],
                "sms": message,
                "type": "plain",
                "channel": "generic",
                "api_key": config["api_key"],
            }
        else:
            # Generic SMS API (custom URL)
            payload = {
                "to": phone,
                "message": message,
                "sender": config["sender_id"],
            }

        with httpx.Client(timeout=10) as client:
            resp = client.post(
                config["api_url"],
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            if resp.status_code < 300:
                logger.info("SMS sent to %s via %s", phone, config["provider"])
                return True
            else:
                logger.warning("SMS failed %d: %s", resp.status_code, resp.text[:200])
                return False
    except Exception as exc:
        logger.warning("SMS error: %s", str(exc))
        return False


def send_order_confirmation_sms(phone: str, order_number: str, total: float, tracking_url: str = "") -> bool:
    """Send order confirmation SMS."""
    config = _get_sms_config()
    msg = config["templates"]["order"].format(
        order_number=order_number,
        total=f"{total:,.2f}",
        tracking_url=tracking_url or f"{_get_base_url()}/shop/account/orders",
    )
    return send_sms(phone, msg)


def send_shipping_sms(phone: str, order_number: str, tracking_number: str, tracking_url: str = "") -> bool:
    """Send shipping notification SMS."""
    config = _get_sms_config()
    msg = config["templates"]["shipping"].format(
        order_number=order_number,
        tracking_number=tracking_number,
        tracking_url=tracking_url or f"{_get_base_url()}/shop/account/tracking",
    )
    return send_sms(phone, msg)


def send_delivery_sms(phone: str, order_number: str, site_name: str = "ForgeStore") -> bool:
    """Send delivery confirmation SMS."""
    config = _get_sms_config()
    msg = config["templates"]["delivery"].format(
        order_number=order_number,
        site_name=site_name,
    )
    return send_sms(phone, msg)


def send_otp_sms(phone: str, code: str) -> bool:
    """Send OTP verification SMS."""
    config = _get_sms_config()
    msg = config["templates"]["otp"].format(code=code)
    return send_sms(phone, msg)


def _get_base_url() -> str:
    try:
        from app.config import get_settings
        return get_settings().site_base_url.rstrip("/")
    except Exception:
        return "http://localhost:8000"
