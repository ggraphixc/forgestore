"""
Unified Notification Engine — Brevo HTTPS Email + Meta WhatsApp Cloud API + Termii SMS

Resolution order for each channel:
  1. Environment variables (BREVO_API_KEY, WHATSAPP_ACCESS_TOKEN, TERMII_API_KEY)
  2. Console stdout dump (dev fallback when no API key or fallback enabled)

All email transmission via HTTPS POST to Brevo v3 endpoint.
All WhatsApp transmission via Meta Graph API v20.0 template messages.
All SMS transmission via Termii API.
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

    url = f"https://graph.facebook.com/v20.0/{phone_number_id}/messages"
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


# ─── Termii SMS ───────────────────────────────────────────────────

async def trigger_sms_tracking_alert(recipient_phone: str, message_text: str):
    """Send an operational SMS alert via Termii API."""
    termii_api_key = os.getenv("TERMII_API_KEY", "").strip()
    termii_sender_id = os.getenv("TERMII_SENDER_ID", "ForgeStore")

    if not termii_api_key:
        logger.info("[SMS CONSOLE FALLBACK] To: %s | Msg: %s", recipient_phone, message_text)
        return

    url = "https://api.ng.termii.com/api/sms/send"
    payload = {
        "to": recipient_phone,
        "from": termii_sender_id,
        "sms": message_text,
        "type": "plain",
        "channel": "generic",
        "api_key": termii_api_key,
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(url, json=payload)
            logger.info("SMS delivery status logged: %s", res.status_code)
    except Exception as e:
        logger.error("Failed to transmit operational SMS update: %s", str(e))


async def send_order_status_sms(phone: str, order_number: str, status: str, vendor_name: str = ""):
    """Send order status tracking SMS to customer."""
    status_messages = {
        "PROCESSING": f"Your order #{order_number} is being prepared by {vendor_name or 'the vendor'}. Track it on ForgeStore.",
        "SHIPPED": f"Great news! Your order #{order_number} has been shipped and is on its way to you.",
        "DELIVERED": f"Your order #{order_number} has been delivered. Thank you for shopping with ForgeStore!",
        "CANCELLED": f"Your order #{order_number} has been cancelled. Contact support if you need help.",
    }
    message = status_messages.get(status, f"Order #{order_number} status update: {status}")
    await trigger_sms_tracking_alert(phone, message)


async def send_payout_sms(phone: str, amount: float, status: str):
    """Send payout notification SMS to vendor."""
    if status == "SUCCESSFUL":
        message = f"Your payout of ₦{amount:,.2f} has been processed and sent to your bank account. — ForgeStore"
    elif status == "FAILED":
        message = f"Your payout of ₦{amount:,.2f} could not be processed. Please check your bank details. — ForgeStore"
    else:
        message = f"Your payout of ₦{amount:,.2f} is being reviewed. — ForgeStore"
    await trigger_sms_tracking_alert(phone, message)
