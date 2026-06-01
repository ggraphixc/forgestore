"""
Notification Engine — SMS & Operational Alerts
Sends real-time tracking updates via Termii SMS when fulfillment statuses change.
"""
import os
import httpx
import logging

logger = logging.getLogger("app.notifications")


async def trigger_sms_tracking_alert(recipient_phone: str, message_text: str):
    """Send an operational SMS alert via Termii API.

    Falls back to console logging when TERMII_API_KEY is not configured.
    """
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
