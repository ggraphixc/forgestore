"""
Payment Provider Abstraction Layer

Provides a common interface for multiple payment gateways (Paystack)
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

    _DEFAULT_API_BASE = "https://api.paystack.co"
    TIMEOUT = 15

    def __init__(self, secret_key: str, public_key: str = ""):
        self.secret_key = secret_key
        self.public_key = public_key
        self._api_base = None

    @property
    def API_BASE(self) -> str:
        if self._api_base is None:
            try:
                from app.config import get_db_setting
                self._api_base = get_db_setting("paystack_api_base", self._DEFAULT_API_BASE)
            except Exception:
                self._api_base = self._DEFAULT_API_BASE
        return self._api_base

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


# ── Factory ──────────────────────────────────────────────────────────

_registry: dict[str, type[PaymentProvider]] = {
    "paystack": PaystackProvider,
}


def register_provider(name: str, cls: type[PaymentProvider]):
    """Register a custom payment provider."""
    _registry[name.lower()] = cls


_db_provider_cache: str | None = None
_db_provider_lookup_attempted: bool = False


def _get_db_provider() -> str | None:
    """Read the active payment provider from the DB Settings table.

    Caches the result to avoid a DB query on every request.
    Falls back to ``None`` when the DB is unavailable or no provider is set.
    """
    global _db_provider_cache, _db_provider_lookup_attempted
    if _db_provider_lookup_attempted:
        return _db_provider_cache
    _db_provider_lookup_attempted = True
    try:
        from app.database import SessionLocal
        from app.models import Settings as SettingsModel
        db = SessionLocal()
        try:
            setting = db.query(SettingsModel).filter(
                SettingsModel.key == "default_payment_provider"
            ).first()
            if setting and setting.value:
                _db_provider_cache = setting.value.lower()
                return _db_provider_cache
        finally:
            db.close()
    except Exception:
        logger.warning("Could not read default_payment_provider from DB, falling back to env")
    return None


def invalidate_provider_cache():
    """Clear the cached DB provider value. Call after updating the setting."""
    global _db_provider_cache, _db_provider_lookup_attempted
    _db_provider_cache = None
    _db_provider_lookup_attempted = False
    logger.info("Payment provider cache invalidated")


def get_payment_provider(
    provider: str = "paystack",
    secret_key: Optional[str] = None,
    public_key: Optional[str] = None,
) -> PaymentProvider:
    """Factory: return a configured payment provider instance.

    Resolution order:
        1. Explicit *provider* argument
        2. ``default_payment_provider`` from the DB ``Settings`` table
        3. ``settings.default_payment_provider`` from environment / ``.env``

    Keys are read from environment via ``get_settings()`` when not passed explicitly.
    """
    from app.config import get_settings

    settings = get_settings()

    # Try DB provider first, fall back to env config
    db_provider = _get_db_provider()
    effective_provider = db_provider or settings.default_payment_provider or provider
    effective_provider = effective_provider.lower()

    cls = _registry.get(effective_provider)
    if not cls:
        raise ValueError(f"Unknown payment provider: {effective_provider!r} (known: {list(_registry)})")

    if effective_provider == "paystack":
        sk = secret_key or settings.paystack_secret_key
        pk = public_key or settings.paystack_public_key
    else:
        sk = secret_key or ""
        pk = public_key or ""

    return cls(secret_key=sk, public_key=pk)


# ── Automated Bank Transfer Engine ──────────────────────────────────

class BankTransferEngine:
    """Async Paystack Transfer Engine — creates recipients and initiates transfers."""

    _DEFAULT_API_BASE = "https://api.paystack.co"
    TIMEOUT = 30

    def __init__(self, secret_key: str):
        self.secret_key = secret_key
        self._api_base = None

    @property
    def API_BASE(self) -> str:
        if self._api_base is None:
            try:
                from app.config import get_db_setting
                self._api_base = get_db_setting("paystack_api_base", self._DEFAULT_API_BASE)
            except Exception:
                self._api_base = self._DEFAULT_API_BASE
        return self._api_base

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.secret_key}",
            "Content-Type": "application/json",
        }

    def create_transfer_recipient(
        self,
        name: str,
        bank_code: str,
        account_number: str,
        currency: str = "NGN",
    ) -> dict:
        """Step A: Create a transfer recipient on Paystack."""
        import requests

        payload = {
            "type": "nuban",
            "name": name,
            "account_number": account_number,
            "bank_code": bank_code,
            "currency": currency,
        }
        try:
            resp = requests.post(
                f"{self.API_BASE}/transferrecipient",
                headers=self._headers(),
                json=payload,
                timeout=self.TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("status"):
                recipient_code = data["data"]["recipient_code"]
                logger.info("Transfer recipient created: %s", recipient_code)
                return {"success": True, "recipient_code": recipient_code}
            return {"success": False, "message": data.get("message", "Recipient creation failed")}
        except Exception as exc:
            logger.error("Paystack recipient creation error: %s", exc)
            return {"success": False, "message": str(exc)}

    def initiate_transfer(
        self,
        recipient_code: str,
        amount: float,
        reason: str = "Vendor payout",
        currency: str = "NGN",
    ) -> dict:
        """Step B: Initiate a transfer to a recipient."""
        import requests

        payload = {
            "source": "balance",
            "amount": int(round(amount * 100)),
            "recipient": recipient_code,
            "reason": reason,
            "currency": currency,
        }
        try:
            resp = requests.post(
                f"{self.API_BASE}/transfer",
                headers=self._headers(),
                json=payload,
                timeout=self.TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("status"):
                transfer_code = data["data"].get("transfer_code", "")
                logger.info("Transfer initiated: %s — ₦%.2f", transfer_code, amount)
                return {
                    "success": True,
                    "transfer_code": transfer_code,
                    "status": data["data"].get("status", "pending"),
                    "reference": data["data"].get("reference", ""),
                }
            return {"success": False, "message": data.get("message", "Transfer failed")}
        except Exception as exc:
            logger.error("Paystack transfer error: %s", exc)
            return {"success": False, "message": str(exc)}

    def verify_transfer(self, transfer_code: str) -> dict:
        """Verify transfer status."""
        import requests

        try:
            resp = requests.get(
                f"{self.API_BASE}/transfer/{transfer_code}",
                headers=self._headers(),
                timeout=self.TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("status"):
                return {
                    "success": True,
                    "status": data["data"].get("status", ""),
                    "transfer_code": transfer_code,
                }
            return {"success": False, "message": data.get("message", "Verify failed")}
        except Exception as exc:
            logger.error("Paystack transfer verify error: %s", exc)
            return {"success": False, "message": str(exc)}


def get_bank_transfer_engine() -> Optional[BankTransferEngine]:
    """Factory: return a BankTransferEngine if Paystack is configured."""
    from app.config import get_settings
    cfg = get_settings()
    if cfg.paystack_secret_key:
        return BankTransferEngine(secret_key=cfg.paystack_secret_key)
    return None
