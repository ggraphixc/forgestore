"""
Paystack Payment Service

Handles Paystack transaction initialization, verification, and webhook signature validation.
"""
import json
import logging
import os
import hmac
import hashlib
from typing import Optional
import requests

logger = logging.getLogger("forgestore.paystack")

PAYSTACK_API = "https://api.paystack.co"
TIMEOUT_SECONDS = 15


def _get_secret_key() -> str:
    """Get the Paystack secret key from settings."""
    from app.config import get_settings
    key = get_settings().paystack_secret_key
    if not key:
        logger.error("PAYSTACK_SECRET_KEY is not set (check .env)")
    return key


def initialize_payment(
    email: str,
    amount: float,
    order_id: str,
    order_number: str,
    callback_url: str,
    currency: str = "NGN",
) -> dict:
    """
    Initialize a Paystack transaction.

    Args:
        email: Customer email address.
        amount: Amount in the selected currency (e.g. NGN).
        order_id: Internal order ID to attach as metadata.
        order_number: Human-readable order number (used as reference).
        callback_url: URL to redirect the user to after payment.
        currency: Currency code (NGN, USD, etc.).

    Returns:
        dict with keys: success, authorization_url, access_code, reference, message
    """
    secret_key = _get_secret_key()
    if not secret_key:
        return {"success": False, "message": "Paystack not configured"}

    headers = {
        "Authorization": f"Bearer {secret_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "email": email,
        "amount": int(round(amount * 100)),  # Paystack uses minor units (kobo for NGN)
        "currency": currency,
        "reference": order_number,
        "callback_url": callback_url,
        "metadata": {
            "order_id": order_id,
            "order_number": order_number,
        },
    }

    try:
        resp = requests.post(
            f"{PAYSTACK_API}/transaction/initialize",
            headers=headers,
            json=payload,
            timeout=TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("status"):
            logger.info(
                "Payment initialized for order %s — ref: %s",
                order_number,
                data["data"]["reference"],
            )
            return {
                "success": True,
                "authorization_url": data["data"]["authorization_url"],
                "access_code": data["data"]["access_code"],
                "reference": data["data"]["reference"],
                "message": "Payment initialized successfully",
            }
        else:
            logger.error("Paystack init failed: %s", data.get("message", "Unknown"))
            return {"success": False, "message": data.get("message", "Paystack initialization failed")}

    except requests.RequestException as e:
        logger.error("Paystack HTTP error: %s", e)
        return {"success": False, "message": f"Payment service error: {str(e)}"}


def verify_payment(reference: str) -> dict:
    """
    Verify a Paystack transaction.

    Args:
        reference: The transaction reference (order number).

    Returns:
        dict with keys: success, paid, amount, currency, transaction_id, customer_email, message
    """
    secret_key = _get_secret_key()
    if not secret_key:
        return {"success": False, "message": "Paystack not configured"}

    headers = {
        "Authorization": f"Bearer {secret_key}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.get(
            f"{PAYSTACK_API}/transaction/verify/{reference}",
            headers=headers,
            timeout=TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("status"):
            tx_data = data["data"]
            status = tx_data.get("status", "")
            is_paid = status == "success"

            logger.info(
                "Payment verification for %s — status: %s, amount: %s %s",
                reference,
                status,
                tx_data.get("amount", 0) / 100,
                tx_data.get("currency", "NGN"),
            )

            return {
                "success": True,
                "paid": is_paid,
                "status": status,
                "amount": tx_data.get("amount", 0) / 100,
                "currency": tx_data.get("currency", "NGN"),
                "transaction_id": tx_data.get("id"),
                "customer_email": tx_data.get("customer", {}).get("email"),
                "gateway_response": tx_data.get("gateway_response", ""),
                "message": "Payment verified successfully" if is_paid else "Payment not completed",
            }
        else:
            logger.error("Paystack verify failed: %s", data.get("message", "Unknown"))
            return {"success": False, "message": data.get("message", "Verification failed")}

    except requests.RequestException as e:
        logger.error("Paystack verify HTTP error: %s", e)
        return {"success": False, "message": f"Verification error: {str(e)}"}


def verify_webhook_signature(signature: str, body: str) -> bool:
    """
    Verify the Paystack webhook HMAC-SHA512 signature.

    Args:
        signature: The x-paystack-signature header value.
        body: Raw request body as string.

    Returns:
        True if signature is valid, False otherwise.
    """
    secret_key = _get_secret_key()
    if not secret_key or not signature:
        return False

    expected = hmac.new(
        secret_key.encode("utf-8"),
        body.encode("utf-8"),
        hashlib.sha512,
    ).hexdigest()

    return hmac.compare_digest(expected, signature)
