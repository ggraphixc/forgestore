"""
Unified Notification Engine — Brevo HTTPS Email + Meta WhatsApp Cloud API

Resolution order for each channel:
  1. Environment variables (BREVO_API_KEY, WHATSAPP_ACCESS_TOKEN)
  2. Console stdout dump (dev fallback when no API key or fallback enabled)

All email transmission via HTTPS POST to Brevo v3 endpoint.
All WhatsApp transmission via Meta Graph API v17.0 (free-form messages within 24h window).
"""
import os
import sys
import httpx
import logging

logger = logging.getLogger("app.notifications")


# ─── Brevo Email ──────────────────────────────────────────────────

async def send_platform_email(to_email: str, subject: str, html_content: str):
    """Asynchronously transmits transactional notifications via Brevo API v3 endpoints."""
    api_key = os.getenv("BREVO_API_KEY", "").strip()
    from_email = os.getenv("MAIL_FROM_EMAIL", "ggraphixc@gmail.com").strip()
    console_fallback = os.getenv("MAIL_CONSOLE_FALLBACK", "False").lower() in ("true", "1", "t")

    if console_fallback or not api_key:
        sys.stdout.write(f"\n=== [EMAIL FALLBACK] ===\nTo: {to_email}\nSubject: {subject}\nBody:\n{html_content}\n")
        sys.stdout.flush()
        return

    url = "https://api.brevo.com/v3/smtp/email"
    headers = {
        "api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = {
        "sender": {"name": "ForgeStore Support", "email": from_email},
        "to": [{"email": to_email}],
        "subject": subject,
        "htmlContent": html_content,
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(url, headers=headers, json=payload)
            if res.status_code in (200, 201, 202):
                logger.info("Email successfully delivered to %s via Brevo API.", to_email)
            else:
                logger.error("Brevo transaction rejected: %d - %s", res.status_code, res.text)
    except Exception as exc:
        logger.error("Failed to reach Brevo API gateway infrastructure: %s", str(exc))


# ─── Meta WhatsApp Cloud API ──────────────────────────────────────

async def send_whatsapp_message(to_phone: str, body_text: str):
    """
    Send a free-form WhatsApp text message via Meta Cloud API.
    Works within the 24-hour customer service window.
    Expects recipient phone in international format (e.g., '2348012345678').
    """
    token = os.getenv("WHATSAPP_ACCESS_TOKEN", "").strip()
    phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip()
    console_fallback = os.getenv("WHATSAPP_CONSOLE_FALLBACK", "False").lower() in ("true", "1", "t")

    if console_fallback or not token or not phone_number_id:
        sys.stdout.write(f"\n=== [WHATSAPP FALLBACK] ===\nTo: {to_phone}\nBody: {body_text}\n")
        sys.stdout.flush()
        return

    url = f"https://graph.facebook.com/v17.0/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_phone.strip().replace("+", ""),
        "type": "text",
        "text": {"body": body_text},
    }

    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            res = await client.post(url, headers=headers, json=payload)
            if res.status_code in (200, 201, 202):
                logger.info("WhatsApp message sent to %s.", to_phone)
            else:
                logger.error("Meta Graph API rejected WhatsApp message: %d - %s", res.status_code, res.text)
    except Exception as exc:
        logger.error("Failed to connect to Meta Graph API: %s", str(exc))


async def send_whatsapp_interactive_alert(to_phone: str, template_name: str, parameters: list = None):
    """
    Asynchronously transmits a template-based notification alert via Meta's WhatsApp Cloud API.
    Expects recipient phone in international format (e.g., '2348012345678').
    """
    token = os.getenv("WHATSAPP_ACCESS_TOKEN", "").strip()
    phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip()
    console_fallback = os.getenv("WHATSAPP_CONSOLE_FALLBACK", "False").lower() in ("true", "1", "t")

    if console_fallback or not token or not phone_number_id:
        sys.stdout.write(f"\n=== [WHATSAPP FALLBACK] ===\nTo: {to_phone}\nTemplate: {template_name}\nParams: {parameters}\n")
        sys.stdout.flush()
        return

    url = f"https://graph.facebook.com/v17.0/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    components = []
    if parameters:
        components.append({
            "type": "body",
            "parameters": [{"type": "text", "text": str(p)} for p in parameters],
        })

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_phone.strip().replace("+", ""),
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": "en_US"},
        },
    }
    if components:
        payload["template"]["components"] = components

    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            res = await client.post(url, headers=headers, json=payload)
            if res.status_code in (200, 201, 202):
                logger.info("WhatsApp notification pushed to %s via template %s.", to_phone, template_name)
            else:
                logger.error("Meta Graph API rejected WhatsApp payload: %d - %s", res.status_code, res.text)
    except Exception as exc:
        logger.error("Failed to connect to Meta Graph API: %s", str(exc))


# ─── Order Lifecycle WhatsApp Notifications ───────────────────────

def _normalize_phone(phone: str) -> str:
    """Normalize Nigerian phone number to international format without +."""
    if not phone:
        return ""
    phone = phone.strip().replace("+", "").replace(" ", "").replace("-", "")
    # Convert 080... to 23480...
    if phone.startswith("0") and len(phone) >= 11:
        phone = "234" + phone[1:]
    return phone


async def send_order_placed_whatsapp(phone: str, order_number: str, total: float, items_summary: str):
    """Notify customer that their order has been placed."""
    phone = _normalize_phone(phone)
    if not phone:
        return
    body = (
        f"Hi! Your ForgeStore order *{order_number}* has been placed successfully.\n\n"
        f"Items: {items_summary}\n"
        f"Total: *₦{total:,.2f}*\n\n"
        f"We'll notify you once your order is confirmed. Thank you for shopping with us!"
    )
    await send_whatsapp_message(phone, body)


async def send_order_confirmed_whatsapp(phone: str, order_number: str, vendor_name: str = ""):
    """Notify customer that their order has been confirmed."""
    phone = _normalize_phone(phone)
    if not phone:
        return
    vendor_text = f" by {vendor_name}" if vendor_name else ""
    body = (
        f"Great news! Your ForgeStore order *{order_number}* has been confirmed{vendor_text}.\n\n"
        f"Your order is now being prepared for shipment. We'll notify you when it ships."
    )
    await send_whatsapp_message(phone, body)


async def send_order_shipped_whatsapp(phone: str, order_number: str, carrier: str = "", tracking_url: str = ""):
    """Notify customer that their order has been shipped."""
    phone = _normalize_phone(phone)
    if not phone:
        return
    carrier_text = f" via {carrier}" if carrier else ""
    tracking_text = f"\nTrack your order: {tracking_url}" if tracking_url else ""
    body = (
        f"Your ForgeStore order *{order_number}* has been shipped{carrier_text}!\n\n"
        f"You'll receive it soon.{tracking_text}"
    )
    await send_whatsapp_message(phone, body)


async def send_order_delivered_whatsapp(phone: str, order_number: str):
    """Notify customer that their order has been delivered."""
    phone = _normalize_phone(phone)
    if not phone:
        return
    body = (
        f"Your ForgeStore order *{order_number}* has been delivered! 🎉\n\n"
        f"We hope you love your purchase. Rate your experience in the app to help other buyers."
    )
    await send_whatsapp_message(phone, body)


async def send_order_cancelled_whatsapp(phone: str, order_number: str, reason: str = ""):
    """Notify customer that their order has been cancelled."""
    phone = _normalize_phone(phone)
    if not phone:
        return
    reason_text = f"\nReason: {reason}" if reason else ""
    body = (
        f"Your ForgeStore order *{order_number}* has been cancelled.{reason_text}\n\n"
        f"If you have any questions, please contact our support team."
    )
    await send_whatsapp_message(phone, body)


async def send_new_order_vendor_whatsapp(vendor_phone: str, order_number: str, customer_name: str, items_summary: str, total: float):
    """Notify vendor of a new order."""
    vendor_phone = _normalize_phone(vendor_phone)
    if not vendor_phone:
        return
    body = (
        f"New order received! 🛒\n\n"
        f"Order: *{order_number}*\n"
        f"Customer: {customer_name}\n"
        f"Items: {items_summary}\n"
        f"Total: *₦{total:,.2f}*\n\n"
        f"Log in to your vendor dashboard to process this order."
    )
    await send_whatsapp_message(vendor_phone, body)


async def send_order_status_whatsapp(phone: str, order_number: str, status: str, vendor_name: str = ""):
    """Send order status tracking notification via WhatsApp (legacy template-based)."""
    status_map = {
        "PROCESSING": "Processing",
        "SHIPPED": "Shipped",
        "DELIVERED": "Delivered",
        "CANCELLED": "Cancelled",
    }
    template_status = status_map.get(status, status)
    await send_whatsapp_interactive_alert(
        to_phone=phone,
        template_name="order_status_update",
        parameters=[order_number, template_status],
    )


async def send_payout_whatsapp(phone: str, amount: float, status: str):
    """Send payout notification to vendor via WhatsApp template."""
    if status == "SUCCESSFUL":
        msg_status = "Successful"
    elif status == "FAILED":
        msg_status = "Failed"
    else:
        msg_status = "Pending"
    await send_whatsapp_interactive_alert(
        to_phone=phone,
        template_name="payout_notification",
        parameters=[f"₦{amount:,.2f}", msg_status],
    )
