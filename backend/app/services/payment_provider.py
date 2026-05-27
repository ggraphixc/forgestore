"""
Payment Provider Abstraction Layer

Provides a common interface for multiple payment gateways (Paystack, Flutterwave)
with a factory pattern so the rest of the app never depends on a specific provider.
"""
import abc
import json
import logging
from typing import Optional

logger = logging.getLogger("forgestore.payment")


# ── Abstract Base ────────────────────────────────────────────────────

class PaymentProvider(abc.ABC):
    """Every payment gateway must implement these methods."""

    @abc.abstractmethod
    def initialize_payment(
        self,
        email: str,
        amount: float,
        reference: str,
        callback_url: str,
        metadata: Optional[dict] = None,
        currency: str = "NGN",
    ) -> dict:
        """Initialize a payment and return an authorization URL."""

    @abc.abstractmethod
    def verify_payment(self, reference: str) -> dict:
        """Check whether a payment has been completed."""

    @abc.abstractmethod
    def verify_webhook_signature(self, signature: str, body: str) -> bool:
        """Validate an incoming webhook signature."""


# ── Paystack ─────────────────────────────────────────────────────────

class PaystackProvider(PaymentProvider):
    """Paystack payment gateway implementation."""

    API_BASE = "https://api.paystack.co"
    TIMEOUT = 15

    def __init__(self, secret_key: str, public_key: str = ""):
        self.secret_key = secret_key
        self.public_key = public_key

    # ── helpers ──────────────────────────────────────────────────────

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.secret_key}",
            "Content-Type": "application/json",
        }

    # ── interface ────────────────────────────────────────────────────

    def initialize_payment(
        self,
        email: str,
        amount: float,
        reference: str,
        callback_url: str,
        metadata: Optional[dict] = None,
        currency: str = "NGN",
    ) -> dict:
        if not self.secret_key:
            return {"success": False, "message": "Paystack not configured"}

        import requests

        payload = {
            "email": email,
            "amount": int(round(amount * 100)),  # minor units (kobo)
            "currency": currency,
            "reference": reference,
            "callback_url": callback_url,
            "metadata": metadata or {},
        }

        try:
            resp = requests.post(
                f"{self.API_BASE}/transaction/initialize",
                headers=self._headers(),
                json=payload,
                timeout=self.TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("status"):
                logger.info("Paystack init ok — ref: %s", reference)
                return {
                    "success": True,
                    "authorization_url": data["data"]["authorization_url"],
                    "access_code": data["data"].get("access_code", ""),
                    "reference": data["data"]["reference"],
                    "message": "Payment initialized",
                }
            return {"success": False, "message": data.get("message", "Init failed")}
        except Exception as exc:
            logger.error("Paystack init error: %s", exc)
            return {"success": False, "message": f"Payment service error: {exc}"}

    def verify_payment(self, reference: str) -> dict:
        if not self.secret_key:
            return {"success": False, "message": "Paystack not configured"}

        import requests

        try:
            resp = requests.get(
                f"{self.API_BASE}/transaction/verify/{reference}",
                headers=self._headers(),
                timeout=self.TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("status"):
                tx = data["data"]
                paid = tx.get("status") == "success"
                return {
                    "success": True,
                    "paid": paid,
                    "status": tx.get("status", ""),
                    "amount": tx.get("amount", 0) / 100,
                    "currency": tx.get("currency", "NGN"),
                    "transaction_id": tx.get("id"),
                    "customer_email": tx.get("customer", {}).get("email"),
                    "gateway_response": tx.get("gateway_response", ""),
                    "message": "Verified" if paid else "Not completed",
                }
            return {"success": False, "message": data.get("message", "Verify failed")}
        except Exception as exc:
            logger.error("Paystack verify error: %s", exc)
            return {"success": False, "message": f"Verification error: {exc}"}

    def verify_webhook_signature(self, signature: str, body: str) -> bool:
        import hmac, hashlib
        if not self.secret_key or not signature:
            return False
        expected = hmac.new(
            self.secret_key.encode("utf-8"),
            body.encode("utf-8"),
            hashlib.sha512,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)


# ── Flutterwave ──────────────────────────────────────────────────────

class FlutterwaveProvider(PaymentProvider):
    """Flutterwave (Rave) payment gateway implementation."""

    API_BASE = "https://api.flutterwave.com/v3"
    TIMEOUT = 15

    def __init__(self, secret_key: str, public_key: str = ""):
        self.secret_key = secret_key
        self.public_key = public_key

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.secret_key}",
            "Content-Type": "application/json",
        }

    def initialize_payment(
        self,
        email: str,
        amount: float,
        reference: str,
        callback_url: str,
        metadata: Optional[dict] = None,
        currency: str = "NGN",
    ) -> dict:
        if not self.secret_key:
            return {"success": False, "message": "Flutterwave not configured"}

        import requests

        payload = {
            "tx_ref": reference,
            "amount": amount,
            "currency": currency,
            "redirect_url": callback_url,
            "customer": {"email": email},
            "meta": metadata or {},
        }

        try:
            resp = requests.post(
                f"{self.API_BASE}/payments",
                headers=self._headers(),
                json=payload,
                timeout=self.TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") == "success":
                link = data["data"]["link"]
                logger.info("Flutterwave init ok — ref: %s", reference)
                return {
                    "success": True,
                    "authorization_url": link,
                    "access_code": "",
                    "reference": reference,
                    "message": "Payment initialized",
                }
            return {"success": False, "message": data.get("message", "Init failed")}
        except Exception as exc:
            logger.error("Flutterwave init error: %s", exc)
            return {"success": False, "message": f"Payment service error: {exc}"}

    def verify_payment(self, reference: str) -> dict:
        if not self.secret_key:
            return {"success": False, "message": "Flutterwave not configured"}

        import requests

        try:
            resp = requests.get(
                f"{self.API_BASE}/transactions/by_reference/{reference}",
                headers=self._headers(),
                timeout=self.TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") == "success":
                tx = data["data"]
                paid = tx.get("status") == "successful"
                return {
                    "success": True,
                    "paid": paid,
                    "status": tx.get("status", ""),
                    "amount": tx.get("amount", 0),
                    "currency": tx.get("currency", "NGN"),
                    "transaction_id": tx.get("id"),
                    "customer_email": tx.get("customer", {}).get("email"),
                    "gateway_response": tx.get("gateway_response", ""),
                    "message": "Verified" if paid else "Not completed",
                }
            return {"success": False, "message": data.get("message", "Verify failed")}
        except Exception as exc:
            logger.error("Flutterwave verify error: %s", exc)
            return {"success": False, "message": f"Verification error: {exc}"}

    def verify_webhook_signature(self, signature: str, body: str) -> bool:
        import hashlib, hmac
        if not self.secret_key or not signature:
            return False
        expected = hmac.new(
            self.secret_key.encode("utf-8"),
            body.encode("utf-8"),
            hashlib.sha512,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)


# ── Factory ──────────────────────────────────────────────────────────

_registry: dict[str, type[PaymentProvider]] = {
    "paystack": PaystackProvider,
    "flutterwave": FlutterwaveProvider,
}


def register_provider(name: str, cls: type[PaymentProvider]):
    """Register a custom payment provider."""
    _registry[name.lower()] = cls


def get_payment_provider(
    provider: str = "paystack",
    secret_key: Optional[str] = None,
    public_key: Optional[str] = None,
) -> PaymentProvider:
    """Factory: return a configured payment provider instance.

    Keys are read from environment via ``get_settings()`` when not passed explicitly.
    """
    from app.config import get_settings

    settings = get_settings()
    provider = provider.lower()

    cls = _registry.get(provider)
    if not cls:
        raise ValueError(f"Unknown payment provider: {provider!r} (known: {list(_registry)})")

    if provider == "paystack":
        sk = secret_key or settings.paystack_secret_key
        pk = public_key or settings.paystack_public_key
    elif provider == "flutterwave":
        sk = secret_key or settings.flutterwave_secret_key
        pk = public_key or settings.flutterwave_public_key
    else:
        sk = secret_key or ""
        pk = public_key or ""

    return cls(secret_key=sk, public_key=pk)
