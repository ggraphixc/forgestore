"""Affiliate & Referral System — System 4"""
import logging
import uuid
from datetime import datetime
from datetime import timedelta
from app.utils import utcnow
from app.utils import utcnow
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models import (
    Affiliate, AffiliateCommission, ReferralEvent, AffiliatePayout,
    Order, OrderItem, Product, User,
)
from app.services.wallet_service import WalletService

logger = logging.getLogger("forgestore.affiliate")


class AffiliateService:
    """Manages affiliate accounts, links, and tracking."""

    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def _generate_code() -> str:
        """Generate a unique referral code."""
        import uuid
        return uuid.uuid4().hex[:8].upper()

    def create_affiliate(self, user_id: Optional[str] = None, name: Optional[str] = None,
                         email: Optional[str] = None, commission_rate: float = 5.0,
                         affiliate_type: str = "referral") -> Affiliate:
        """Create a new affiliate."""
        code = self._generate_code()
        while self.db.query(Affiliate).filter(Affiliate.code == code).first():
            code = self._generate_code()

        affiliate = Affiliate(
            user_id=user_id,
            code=code,
            name=name,
            email=email,
            type=affiliate_type,
            commission_rate=commission_rate,
        )
        self.db.add(affiliate)
        self.db.commit()
        self.db.refresh(affiliate)
        return affiliate

    def get_affiliate_by_code(self, code: str) -> Optional[Affiliate]:
        """Get affiliate by referral code."""
        return self.db.query(Affiliate).filter(Affiliate.code == code).first()

    def get_affiliate_by_user_id(self, user_id: str) -> Optional[Affiliate]:
        """Get affiliate by user ID."""
        return self.db.query(Affiliate).filter(Affiliate.user_id == user_id).first()

    def track_click(self, affiliate_code: str, ip_address: Optional[str] = None,
                    user_agent: Optional[str] = None) -> Optional[ReferralEvent]:
        """Track a referral link click."""
        affiliate = self.get_affiliate_by_code(affiliate_code)
        if not affiliate:
            return None

        affiliate.total_clicks += 1
        event = ReferralEvent(
            affiliate_id=affiliate.id,
            event_type="click",
            referrer_code=affiliate_code,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        self.db.add(event)
        self.db.commit()
        self.db.refresh(event)
        return event

    def track_conversion(self, affiliate_code: str, order_id: str,
                         referred_email: Optional[str] = None) -> Optional[AffiliateCommission]:
        """Track a conversion from a referral link."""
        affiliate = self.get_affiliate_by_code(affiliate_code)
        if not affiliate:
            return None

        order = self.db.query(Order).filter(Order.id == order_id).first()
        if not order:
            return None

        affiliate.total_conversions += 1
        commission_amount = round(order.total_amount * (affiliate.commission_rate / 100), 2)
        affiliate.total_earned += commission_amount
        affiliate.wallet_balance += commission_amount

        commission = AffiliateCommission(
            affiliate_id=affiliate.id,
            order_id=order_id,
            order_amount=order.total_amount,
            commission_rate=affiliate.commission_rate,
            commission_amount=commission_amount,
            status="APPROVED",
            referred_email=referred_email,
        )
        self.db.add(commission)

        event =ReferralEvent(
                affiliate_id=affiliate.id,
                event_type="conversion",
                referrer_code=affiliate_code,
                extra_data={"order_id": order_id, "commission_amount": commission_amount},
            )
        self.db.add(event)
        self.db.commit()
        self.db.refresh(commission)
        return commission

    def get_affiliate_stats(self, affiliate_id: str) -> dict:
        """Get comprehensive stats for an affiliate."""
        affiliate = self.db.query(Affiliate).filter(Affiliate.id == affiliate_id).first()
        if not affiliate:
            return {}

        # Get recent commissions
        recent_commissions = self.db.query(AffiliateCommission).filter(
            AffiliateCommission.affiliate_id == affiliate_id
        ).order_by(AffiliateCommission.created_at.desc()).limit(20).all()

        # Get clicks over time (last 30 days)
        month_ago = utcnow() - timedelta(days=30)
        clicks = self.db.query(ReferralEvent).filter(
            ReferralEvent.affiliate_id == affiliate_id,
            ReferralEvent.event_type == "click",
            ReferralEvent.created_at >= month_ago,
        ).count()

        conversions = self.db.query(ReferralEvent).filter(
            ReferralEvent.affiliate_id == affiliate_id,
            ReferralEvent.event_type == "conversion",
            ReferralEvent.created_at >= month_ago,
        ).count()

        conversion_rate = round((conversions / max(clicks, 1)) * 100, 2) if clicks else 0

        return {
            "code": affiliate.code,
            "type": affiliate.type,
            "status": affiliate.status,
            "total_earned": affiliate.total_earned,
            "total_paid": affiliate.total_paid,
            "wallet_balance": affiliate.wallet_balance,
            "total_clicks": affiliate.total_clicks,
            "total_conversions": affiliate.total_conversions,
            "commission_rate": affiliate.commission_rate,
            "recent_clicks_30d": clicks,
            "recent_conversions_30d": conversions,
            "conversion_rate_30d": conversion_rate,
            "recent_commissions": [
                {
                    "id": c.id,
                    "order_amount": c.order_amount,
                    "commission_amount": c.commission_amount,
                    "status": c.status,
                    "created_at": c.created_at.isoformat(),
                }
                for c in recent_commissions
            ],
        }


class CommissionService:
    """Manages commission calculation and processing."""

    def __init__(self, db: Session):
        self.db = db

    def process_order_commissions(self, order_id: str) -> list[AffiliateCommission]:
        """Process commissions for all affiliate-referred items in an order."""
        order = self.db.query(Order).filter(Order.id == order_id).first()
        if not order:
            return []

        commissions = []
        items = self.db.query(OrderItem).filter(OrderItem.order_id == order_id).all()

        for item in items:
            # Check if product has an associated affiliate
            product = self.db.query(Product).filter(Product.id == item.product_id).first()
            if not product:
                continue

            # Check for affiliate codes in order metadata or relevant promotions
            # For now, this is handled by the referral_service
            pass

        return commissions

    def approve_commission(self, commission_id: str) -> bool:
        """Approve a pending commission."""
        commission = self.db.query(AffiliateCommission).filter(
            AffiliateCommission.id == commission_id
        ).first()
        if not commission:
            return False

        commission.status = "APPROVED"
        self.db.commit()
        return True

    def cancel_commission(self, commission_id: str) -> bool:
        """Cancel a commission (e.g., order refunded)."""
        commission = self.db.query(AffiliateCommission).filter(
            AffiliateCommission.id == commission_id
        ).first()
        if not commission:
            return False

        commission.status = "CANCELLED"
        if commission.affiliate_id:
            affiliate = self.db.query(Affiliate).filter(
                Affiliate.id == commission.affiliate_id
            ).first()
            if affiliate:
                affiliate.total_earned = max(0, affiliate.total_earned - commission.commission_amount)
                affiliate.wallet_balance = max(0, affiliate.wallet_balance - commission.commission_amount)

        self.db.commit()
        return True


class ReferralService:
    """Manages referral tracking and wallet integration."""

    def __init__(self, db: Session):
        self.db = db

    def process_referral(self, referral_code: str, referrer_id: str, referred_email: str) -> Optional[Affiliate]:
        """Process a referral when someone signs up with a referral code."""
        affiliate = self.db.query(Affiliate).filter(
            Affiliate.code == referral_code
        ).first()
        if not affiliate:
            return None

        event =ReferralEvent(
                affiliate_id=affiliate.id,
                event_type="signup",
                referrer_code=referral_code,
                extra_data={"referred_email": referred_email, "referrer_id": referrer_id},
            )
        self.db.add(event)
        self.db.commit()
        return affiliate

    def withdraw_earnings(self, affiliate_id: str, amount: float,
                          payment_method: str, payout_details: Optional[dict] = None) -> Optional[AffiliatePayout]:
        """Withdraw earnings from affiliate wallet."""
        affiliate = self.db.query(Affiliate).filter(Affiliate.id == affiliate_id).first()
        if not affiliate:
            return None

        if affiliate.wallet_balance < amount:
            raise ValueError("Insufficient wallet balance")

        fee = round(amount * 0.02, 2)  # 2% withdrawal fee
        net_amount = round(amount - fee, 2)

        payout = AffiliatePayout(
            affiliate_id=affiliate_id,
            amount=amount,
            fee=fee,
            net_amount=net_amount,
            status="PENDING",
            payment_method=payment_method,
        )
        self.db.add(payout)

        affiliate.wallet_balance = round(affiliate.wallet_balance - amount, 2)
        affiliate.total_paid += net_amount
        self.db.commit()
        self.db.refresh(payout)
        return payout

    def process_payout(self, payout_id: str, payment_reference: str) -> bool:
        """Process an affiliate payout."""
        payout = self.db.query(AffiliatePayout).filter(AffiliatePayout.id == payout_id).first()
        if not payout:
            return False

        payout.status = "COMPLETED"
        payout.payment_reference = payment_reference
        payout.processed_at = utcnow()
        self.db.commit()
        return True

    def get_referral_history(self, affiliate_id: str) -> list[ReferralEvent]:
        """Get all referral events for an affiliate."""
        return self.db.query(ReferralEvent).filter(
            ReferralEvent.affiliate_id == affiliate_id
        ).order_by(ReferralEvent.created_at.desc()).limit(50).all()

    def get_earnings_history(self, affiliate_id: str) -> list[AffiliatePayout]:
        """Get all payouts for an affiliate."""
        return self.db.query(AffiliatePayout).filter(
            AffiliatePayout.affiliate_id == affiliate_id
        ).order_by(AffiliatePayout.created_at.desc()).limit(50).all()
