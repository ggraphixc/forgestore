"""Multi-Payment & Wallet System — System 5"""
import logging
import uuid
from datetime import timedelta
from app.utils import utcnow
from typing import Optional
from abc import ABC, abstractmethod
from sqlalchemy.orm import Session

from app.models import Wallet, WalletTransaction, PaymentLog, EscrowTransaction, PaymentSplit, PaymentProvider, Order, Retailer

logger = logging.getLogger("forgestore.wallet")


class PaymentProviderInterface(ABC):
    """Abstract payment gateway interface."""

    @abstractmethod
    def initialize_payment(self, amount: float, currency: str, reference: str, metadata: dict, split_config: Optional[dict] = None) -> dict:
        """Initialize a payment transaction.

        Args:
            split_config: Subaccount split info, e.g.
                Paystack: {"subaccount": "SUB_xxxxx", "transaction_charge": 0}
        """
        pass

    @abstractmethod
    def verify_payment(self, reference: str) -> dict:
        """Verify a payment transaction."""
        pass

    @abstractmethod
    def refund_payment(self, reference: str, amount: Optional[float] = None) -> dict:
        """Process a refund."""
        pass

    @abstractmethod
    def create_subaccount(self, business_name: str, bank_code: str, account_number: str, bank_name: Optional[str] = None) -> str:
        """Create a subaccount for split payments.

        Returns:
            str: The subaccount identifier (Paystack: subaccount_code, Flutterwave: id)
        """
        pass


class PaystackProvider(PaymentProviderInterface):
    """Paystack payment provider implementation."""

    _DEFAULT_API_BASE = "https://api.paystack.co"

    def __init__(self, secret_key: str) -> None:
        self.secret_key = secret_key
        self._api_base = None

    @property
    def _base_url(self) -> str:
        if self._api_base is None:
            try:
                from app.config import get_db_setting
                self._api_base = get_db_setting("paystack_api_base", self._DEFAULT_API_BASE)
            except Exception:
                self._api_base = self._DEFAULT_API_BASE
        return self._api_base

    def initialize_payment(self, amount: float, currency: str, reference: str, metadata: dict, split_config: Optional[dict] = None) -> dict:
        import requests
        payload: dict[str, object] = {
            "amount": int(amount * 100),
            "currency": currency,
            "reference": reference,
            "metadata": metadata,
        }
        if split_config:
            if "subaccount" in split_config:
                payload["subaccount"] = split_config["subaccount"]
            if "transaction_charge" in split_config:
                payload["transaction_charge"] = split_config["transaction_charge"]
            if "bearer" in split_config:
                payload["bearer"] = split_config["bearer"]
        resp = requests.post(
            f"{self._base_url}/transaction/initialize",
            json=payload,
            headers={"Authorization": f"Bearer {self.secret_key}"},
        )
        return resp.json()

    def verify_payment(self, reference: str) -> dict:
        import requests
        resp = requests.get(
            f"{self._base_url}/transaction/verify/{reference}",
            headers={"Authorization": f"Bearer {self.secret_key}"},
        )
        return resp.json()

    def refund_payment(self, reference: str, amount: Optional[float] = None) -> dict:
        import requests
        data: dict[str, object] = {"transaction": reference}
        if amount:
            data["amount"] = int(amount * 100)
        resp = requests.post(
            f"{self._base_url}/refund",
            json=data,
            headers={"Authorization": f"Bearer {self.secret_key}"},
        )
        return resp.json()

    def create_subaccount(self, business_name: str, bank_code: str, account_number: str, bank_name: Optional[str] = None) -> str:
        """Create a Paystack subaccount for split payments."""
        import requests
        resp = requests.post(
            f"{self._base_url}/subaccount",
            json={
                "business_name": business_name,
                "bank_code": bank_code,
                "account_number": account_number,
                "percentage_charge": 0,  # We handle commission via transaction_charge at payment time
            },
            headers={"Authorization": f"Bearer {self.secret_key}"},
        )
        data = resp.json()
        if not data.get("status"):
            raise ValueError(f"Paystack subaccount creation failed: {data.get('message', 'Unknown error')}")
        return data["data"]["subaccount_code"]


class CryptoProvider(PaymentProviderInterface):
    """Crypto payment placeholder for future integration."""

    def __init__(self) -> None:
        pass

    def initialize_payment(self, amount: float, currency: str, reference: str, metadata: dict) -> dict:
        return {"status": True, "message": "Crypto payments coming soon", "data": {"reference": reference}}

    def verify_payment(self, reference: str) -> dict:
        return {"status": True, "message": "Crypto verification placeholder", "data": {"status": "pending"}}

    def refund_payment(self, reference: str, amount: Optional[float] = None) -> dict:
        return {"status": True, "message": "Crypto refund placeholder"}

    def create_subaccount(self, business_name: str, bank_code: str, account_number: str, bank_name: Optional[str] = None) -> str:
        return "crypto_subaccount_placeholder"


class PaymentGatewayFactory:
    """Factory for creating payment providers."""

    @staticmethod
    def get_provider(provider_name: str, config: Optional[dict] = None) -> PaymentProviderInterface:
        providers = {
            "paystack": lambda c: PaystackProvider(c.get("secret_key", "") if c else ""),
            "crypto": lambda c: CryptoProvider(),
        }
        factory_fn = providers.get(provider_name.lower())
        if not factory_fn:
            raise ValueError(f"Unsupported payment provider: {provider_name}")
        return factory_fn(config or {})


class WalletService:
    """Manages user wallets and transactions."""

    def __init__(self, db: Session):
        self.db = db

    def get_or_create_wallet(self, user_id: str, currency: str = "NGN") -> Wallet:
        """Get or create a wallet for a user."""
        wallet = self.db.query(Wallet).filter(
            Wallet.user_id == user_id,
            Wallet.currency == currency,
        ).first()
        if not wallet:
            wallet = Wallet(user_id=user_id, currency=currency)
            self.db.add(wallet)
            self.db.commit()
            self.db.refresh(wallet)
        return wallet

    def get_balance(self, user_id: str, currency: str = "NGN") -> float:
        """Get wallet balance."""
        wallet = self.get_or_create_wallet(user_id, currency)
        return wallet.balance  # type: ignore[return-value]

    def credit_wallet(self, user_id: str, amount: float, reference: str, description: str = "", currency: str = "NGN", metadata: Optional[dict] = None) -> WalletTransaction:
        """Credit a user's wallet."""
        wallet = self.get_or_create_wallet(user_id, currency)
        balance_before = wallet.balance
        wallet.balance += amount  # type: ignore[assignment]

        transaction = WalletTransaction(
            wallet_id=wallet.id,
            transaction_type="deposit",
            amount=amount,
            balance_before=balance_before,
            balance_after=wallet.balance,
            currency=currency,
            reference=reference,
            description=description,
            status="COMPLETED",
            extra_data=metadata or {},
        )
        self.db.add(transaction)
        self.db.commit()
        self.db.refresh(transaction)
        return transaction

    def debit_wallet(self, user_id: str, amount: float, reference: str, description: str = "", currency: str = "NGN", metadata: Optional[dict] = None) -> WalletTransaction:
        """Debit a user's wallet."""
        wallet = self.get_or_create_wallet(user_id, currency)
        if wallet.balance < amount:
            raise ValueError("Insufficient balance")

        balance_before = wallet.balance
        wallet.balance -= amount  # type: ignore[assignment]

        transaction = WalletTransaction(
            wallet_id=wallet.id,
            transaction_type="withdrawal",
            amount=amount,
            balance_before=balance_before,
            balance_after=wallet.balance,
            currency=currency,
            reference=reference,
            description=description,
            status="COMPLETED",
            extra_data=metadata or {},
        )
        self.db.add(transaction)
        self.db.commit()
        self.db.refresh(transaction)
        return transaction

    def get_transactions(self, user_id: str, limit: int = 50) -> list[WalletTransaction]:
        """Get wallet transaction history."""
        wallet = self.get_or_create_wallet(user_id)
        return self.db.query(WalletTransaction).filter(
            WalletTransaction.wallet_id == wallet.id
        ).order_by(WalletTransaction.created_at.desc()).limit(limit).all()


class VendorWalletService:
    """Isolated vendor wallet operations — ensures one vendor cannot access another's funds."""

    def __init__(self, db: Session):
        self.db = db

    def get_or_create_wallet(self, retailer_id: str, currency: str = "NGN"):
        from app.models import VendorWallet
        wallet = self.db.query(VendorWallet).filter(
            VendorWallet.retailer_id == retailer_id,
            VendorWallet.currency == currency,
        ).first()
        if not wallet:
            wallet = VendorWallet(retailer_id=retailer_id, currency=currency)
            self.db.add(wallet)
            self.db.commit()
            self.db.refresh(wallet)
        return wallet

    def credit_vendor(self, retailer_id: str, amount: float, reference: str, description: str = "", order_id: Optional[str] = None):
        """Credit a specific vendor's wallet. Isolated per retailer_id."""
        from app.models import VendorWallet, VendorWalletTransaction
        wallet = self.get_or_create_wallet(retailer_id)
        balance_before = wallet.balance
        wallet.balance += amount

        tx = VendorWalletTransaction(
            wallet_id=wallet.id,
            transaction_type="sale_earning",
            amount=amount,
            balance_before=balance_before,
            balance_after=wallet.balance,
            order_id=order_id,
            reference=reference,
            description=description,
            status="COMPLETED",
        )
        self.db.add(tx)
        self.db.commit()
        self.db.refresh(tx)
        return tx

    def credit_affiliate_commission(self, retailer_id: str, amount: float, reference: str, description: str = ""):
        """Credit affiliate commission to a vendor's wallet."""
        from app.models import VendorWallet, VendorWalletTransaction
        wallet = self.get_or_create_wallet(retailer_id)
        balance_before = wallet.balance
        wallet.balance += amount

        tx = VendorWalletTransaction(
            wallet_id=wallet.id,
            transaction_type="affiliate_commission",
            amount=amount,
            balance_before=balance_before,
            balance_after=wallet.balance,
            reference=reference,
            description=description,
            status="COMPLETED",
        )
        self.db.add(tx)
        self.db.commit()
        self.db.refresh(tx)
        return tx

    def get_balance(self, retailer_id: str) -> float:
        wallet = self.get_or_create_wallet(retailer_id)
        return wallet.balance

    def get_transactions(self, retailer_id: str, limit: int = 50):
        from app.models import VendorWallet, VendorWalletTransaction
        wallet = self.get_or_create_wallet(retailer_id)
        return self.db.query(VendorWalletTransaction).filter(
            VendorWalletTransaction.wallet_id == wallet.id
        ).order_by(VendorWalletTransaction.created_at.desc()).limit(limit).all()


def auto_dispatch_shipment(db: Session, order_id: str):
    """Automatically dispatch a shipment when order enters PROCESSING.

    Finds the first available logistics agent or delivery agent,
    creates a shipment entry, and assigns it.
    """
    from app.models import AdminUser, DeliveryAgent, Shipment, AdminRole, Retailer, OrderItem, Product

    # Check if auto-dispatch is enabled
    from app.models import Settings as SettingsModel
    setting = db.query(SettingsModel).filter(SettingsModel.key == "logistics_auto_dispatch_enabled").first()
    if setting and setting.value.lower() == "false":
        return

    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        return

    # Find first available delivery agent
    agent = db.query(DeliveryAgent).filter(DeliveryAgent.status == "AVAILABLE").order_by(DeliveryAgent.rating.desc()).first()
    if not agent:
        # Fallback: find a LOGISTICS admin user
        logistics_admin = db.query(AdminUser).filter(AdminUser.role == AdminRole.LOGISTICS).first()
        if not logistics_admin:
            return

    # Extract origin from retailer (vendor) address/bio
    origin = ""
    destination = ""
    if order.shipping_address:
        if isinstance(order.shipping_address, dict):
            dest_parts = [order.shipping_address.get("address", ""), order.shipping_address.get("city", "")]
            destination = ", ".join(p for p in dest_parts if p)

    # Get retailer info for origin
    order_items = db.query(OrderItem).filter(OrderItem.order_id == order_id).all()
    if order_items:
        first_product = db.query(Product).filter(Product.id == order_items[0].product_id).first()
        if first_product and first_product.retailer_id:
            retailer = db.query(Retailer).filter(Retailer.id == first_product.retailer_id).first()
            if retailer:
                origin = retailer.bio or retailer.location or retailer.name

    from app.services.shipment_service import ShipmentService
    svc = ShipmentService(db)
    shipment = svc.create_shipment(
        order_id=order_id,
        origin=origin,
        destination=destination,
        delivery_agent_id=agent.id if agent else None,
    )
    return shipment


class EscrowService:
    """Manages escrow transactions for secure payments."""

    def __init__(self, db: Session):
        self.db = db

    def create_escrow(self, order_id: str, amount: float, payer_id: str, payee_id: str, release_condition: str = "delivery_confirmed", auto_release_days: int = 14) -> EscrowTransaction:
        """Create an escrow transaction for an order."""
        import uuid
        escrow = EscrowTransaction(
            order_id=order_id,
            amount=amount,
            payer_id=payer_id,
            payee_id=payee_id,
            status="HELD",
            release_condition=release_condition,
            auto_release_at=utcnow() + timedelta(days=auto_release_days) if release_condition == "auto_release_date" else None,
        )
        self.db.add(escrow)
        self.db.commit()
        self.db.refresh(escrow)
        return escrow

    def release_escrow(self, escrow_id: str) -> bool:
        """Release funds from escrow to the payee."""
        escrow = self.db.query(EscrowTransaction).filter(EscrowTransaction.id == escrow_id).first()
        if not escrow or escrow.status != "HELD":
            return False

        escrow.status = "RELEASED"
        escrow.released_at = utcnow()
        self.db.commit()

        # Credit the payee's wallet
        wallet_service = WalletService(self.db)
        wallet_service.credit_wallet(
            escrow.payee_id,
            escrow.amount,
            f"escrow_release_{escrow.id}",
            f"Escrow release for order {escrow.order_id}",
        )
        return True

    def refund_escrow(self, escrow_id: str) -> bool:
        """Refund escrow funds to the payer."""
        escrow = self.db.query(EscrowTransaction).filter(EscrowTransaction.id == escrow_id).first()
        if not escrow or escrow.status not in ("HELD", "DISPUTED"):
            return False

        escrow.status = "REFUNDED"
        self.db.commit()

        wallet_service = WalletService(self.db)
        wallet_service.credit_wallet(
            escrow.payer_id,
            escrow.amount,
            f"escrow_refund_{escrow.id}",
            f"Escrow refund for order {escrow.order_id}",
        )
        return True


class PaymentService:
    """Unified payment processing with multi-provider support."""

    def __init__(self, db: Session):
        self.db = db

    def get_default_provider(self) -> Optional[PaymentProvider]:
        """Get the default active payment provider."""
        return self.db.query(PaymentProvider).filter(
            PaymentProvider.is_active == True,
            PaymentProvider.is_default == True,
        ).first()

    def initialize_payment(self, order_id: str, amount: float, currency: str = "NGN", provider_name: Optional[str] = None, metadata: Optional[dict] = None, split_config: Optional[dict] = None) -> dict:
        """Initialize a payment through the specified or default provider."""
        if provider_name:
            provider_config = self.db.query(PaymentProvider).filter(PaymentProvider.name == provider_name).first()
        else:
            provider_config = self.get_default_provider()

        if not provider_config:
            raise ValueError("No active payment provider configured")

        import uuid
        reference = f"FS-{uuid.uuid4().hex[:12].upper()}"

        provider = PaymentGatewayFactory.get_provider(provider_config.name, provider_config.config)
        result = provider.initialize_payment(amount, currency, reference, metadata or {}, split_config=split_config)

        # Log the payment attempt
        log = PaymentLog(
            order_id=order_id,
            provider=provider_config.name,
            transaction_reference=reference,
            transaction_type="payment",
            amount=amount,
            currency=currency,
            status="initiated",
            request_data={"provider": provider_config.name, "amount": amount, "currency": currency},
            response_data=result,
        )
        self.db.add(log)
        self.db.commit()

        return {
            "reference": reference,
            "provider": provider_config.name,
            "authorization_url": result.get("data", {}).get("authorization_url", ""),
            "status": result.get("status", False),
        }

    def verify_payment(self, reference: str, provider_name: Optional[str] = None) -> dict:
        """Verify a payment transaction."""
        log = self.db.query(PaymentLog).filter(
            PaymentLog.transaction_reference == reference
        ).first()
        if not log:
            return {"status": False, "message": "Transaction not found"}

        provider_config = self.db.query(PaymentProvider).filter(
            PaymentProvider.name == (provider_name or log.provider)
        ).first()
        if not provider_config:
            return {"status": False, "message": "Provider not found"}

        provider = PaymentGatewayFactory.get_provider(provider_config.name, provider_config.config)
        result = provider.verify_payment(reference)

        if result.get("status") and result.get("data", {}).get("status") == "success":
            log.status = "successful"
            log.response_data = result
            self.db.commit()
        else:
            log.status = "failed"
            log.error_message = result.get("message", "Verification failed")
            self.db.commit()

        return result

    def process_refund(self, reference: str, amount: Optional[float] = None) -> dict:
        """Process a refund for a payment."""
        log = self.db.query(PaymentLog).filter(
            PaymentLog.transaction_reference == reference
        ).first()
        if not log:
            return {"status": False, "message": "Transaction not found"}

        provider_config = self.db.query(PaymentProvider).filter(
            PaymentProvider.name == log.provider
        ).first()
        if not provider_config:
            return {"status": False, "message": "Provider not found"}

        provider = PaymentGatewayFactory.get_provider(provider_config.name, provider_config.config)
        result = provider.refund_payment(reference, amount)

        if result.get("status"):
            log.status = "refunded"
            log.response_data = result
            self.db.commit()

        return result

    def create_payment_split(self, order_id: str, splits: list[dict]) -> list[PaymentSplit]:
        """Create payment splits for multi-vendor orders."""
        order = self.db.query(Order).filter(Order.id == order_id).first()
        if not order:
            raise ValueError("Order not found")

        created = []
        for split in splits:
            payment_split = PaymentSplit(
                order_id=order_id,
                recipient_id=split["retailer_id"],
                amount=split["amount"],
                percentage=split.get("percentage", 0),
            )
            self.db.add(payment_split)
            created.append(payment_split)

        self.db.commit()
        return created
