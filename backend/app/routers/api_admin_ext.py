"""Extended Admin API — all 10 systems admin endpoints."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import Optional

from app.database import get_db
from app.auth import require_admin_role
from app.models import AdminUser, AdminRole
from app.services.shipment_service import ShipmentService, DeliveryService
from app.services.notification_service import NotificationService
from app.services.review_service import ReviewService, ReviewModerationService
from app.services.affiliate_service import AffiliateService, CommissionService
from app.services.vendor_analytics_service import (
    VendorAnalyticsService, VendorPayoutService, VendorMetricsService,
)
from app.services.analytics_service import (
    AnalyticsService, ForecastService, FraudDetectionService, InsightGenerationService,
)
from app.services.wallet_service import PaymentService, EscrowService
from app.services.cart_sync_service import CartRecoveryService

router = APIRouter(prefix="/api/admin", tags=["admin-extended"])
admin_dep = Depends(require_admin_role(AdminRole.DIR_ADMIN, AdminRole.MANAGEMENT, AdminRole.TECH_ADMIN))


# ===== System 1: Shipment Management =====

@router.get("/shipments")
def list_shipments(status: Optional[str] = None, db: Session = Depends(get_db), admin: AdminUser = admin_dep):
    """List all shipments, optionally filtered by status."""
    # Simplified: return all shipments
    from app.models import Shipment
    q = db.query(Shipment)
    if status:
        q = q.filter(Shipment.status == status)
    shipments = q.order_by(Shipment.created_at.desc()).limit(100).all()
    return {
        "shipments": [
            {
                "id": s.id,
                "tracking_number": s.tracking_number,
                "order_id": s.order_id,
                "status": s.status,
                "carrier": s.carrier,
                "estimated_delivery": s.estimated_delivery.isoformat() if s.estimated_delivery else None,
                "created_at": s.created_at.isoformat(),
            }
            for s in shipments
        ],
        "count": len(shipments),
    }


@router.post("/shipments")
def create_shipment(
    order_id: str, carrier: Optional[str] = None,
    origin: Optional[str] = None, destination: Optional[str] = None,
    weight_kg: Optional[float] = None, notes: Optional[str] = None,
    estimated_delivery_days: int = 5,
    db: Session = Depends(get_db), admin: AdminUser = admin_dep,
):
    """Create a new shipment for an order."""
    service = ShipmentService(db)
    shipment = service.create_shipment(
        order_id=order_id, carrier=carrier, origin=origin,
        destination=destination, weight_kg=weight_kg, notes=notes,
        estimated_delivery_days=estimated_delivery_days,
    )
    return {
        "id": shipment.id,
        "tracking_number": shipment.tracking_number,
        "status": shipment.status,
        "estimated_delivery": shipment.estimated_delivery.isoformat() if shipment.estimated_delivery else None,
    }


@router.put("/shipments/{shipment_id}/status")
def update_shipment_status(
    shipment_id: str, status: str, description: Optional[str] = None,
    db: Session = Depends(get_db), admin: AdminUser = admin_dep,
):
    """Update shipment status."""
    service = ShipmentService(db)
    try:
        shipment = service.update_status(shipment_id, status, description)
        return {"id": shipment.id, "status": shipment.status}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/shipments/{shipment_id}/assign-agent")
def assign_delivery_agent(
    shipment_id: str, agent_id: str,
    db: Session = Depends(get_db), admin: AdminUser = admin_dep,
):
    """Assign a delivery agent to a shipment."""
    service = ShipmentService(db)
    try:
        shipment = service.assign_delivery_agent(shipment_id, agent_id)
        return {"id": shipment.id, "delivery_agent_id": shipment.delivery_agent_id}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/delivery-agents")
def list_delivery_agents(status: Optional[str] = None, db: Session = Depends(get_db), admin: AdminUser = admin_dep):
    """List delivery agents."""
    service = DeliveryService(db)
    if status:
        agents = [a for a in service.get_available_agents() if a.status == status]
    else:
        from app.models import DeliveryAgent
        agents = db.query(DeliveryAgent).order_by(DeliveryAgent.name).all()
    return {
        "agents": [
            {
                "id": a.id, "name": a.name, "phone": a.phone,
                "vehicle_type": a.vehicle_type, "status": a.status,
                "rating": a.rating, "total_deliveries": a.total_deliveries,
            }
            for a in agents
        ],
    }


# ===== System 2: Vendor Management =====

@router.get("/vendors/analytics/{retailer_id}")
def get_vendor_analytics(retailer_id: str, days: int = 30, db: Session = Depends(get_db), admin: AdminUser = admin_dep):
    """Get vendor analytics data."""
    service = VendorAnalyticsService(db)
    return service.get_dashboard_data(retailer_id, days)


@router.get("/vendors/payouts")
def list_vendor_payouts(status: Optional[str] = None, db: Session = Depends(get_db), admin: AdminUser = admin_dep):
    """List vendor payouts."""
    from app.models import VendorPayout
    q = db.query(VendorPayout)
    if status:
        q = q.filter(VendorPayout.status == status)
    payouts = q.order_by(VendorPayout.created_at.desc()).limit(50).all()
    return {"payouts": [{"id": p.id, "retailer_id": p.retailer_id, "amount": p.amount,
                         "net_amount": p.net_amount, "status": p.status, "created_at": p.created_at.isoformat()} for p in payouts]}


# ===== System 8: Review Moderation =====

@router.get("/reviews/moderation")
def list_moderation_queue(status: str = "PENDING", db: Session = Depends(get_db), admin: AdminUser = admin_dep):
    """List reviews awaiting moderation."""
    from app.models import ReviewModeration
    items = db.query(ReviewModeration).filter(
        ReviewModeration.status == status
    ).order_by(ReviewModeration.created_at.asc()).limit(50).all()
    return {"items": [{"id": m.id, "review_id": m.review_id, "status": m.status,
                       "reason": m.reason, "ai_flags": m.ai_flags,
                       "created_at": m.created_at.isoformat()} for m in items]}


@router.post("/reviews/{review_id}/approve")
def approve_review(review_id: str, notes: Optional[str] = None, db: Session = Depends(get_db), admin: AdminUser = admin_dep):
    """Approve a pending review."""
    service = ReviewModerationService(db)
    service.approve_review(review_id, admin.id, notes)
    return {"status": "approved"}


@router.post("/reviews/{review_id}/reject")
def reject_review(review_id: str, reason: str, notes: Optional[str] = None, db: Session = Depends(get_db), admin: AdminUser = admin_dep):
    """Reject a review."""
    service = ReviewModerationService(db)
    service.reject_review(review_id, admin.id, reason, notes)
    return {"status": "rejected"}


# ===== System 9: Notifications (handled by admin_api.py) =====


# ===== System 10: Enterprise Analytics =====

@router.get("/analytics/predictive")
def get_predictive_analytics(days: int = 30, db: Session = Depends(get_db), admin: AdminUser = admin_dep):
    """Get predictive analytics overview."""
    analytics = AnalyticsService(db)
    revenue = analytics.get_revenue_metrics(days)
    customers = analytics.get_customer_metrics()
    return {"revenue": revenue, "customers": customers}


@router.get("/analytics/cohort")
def get_cohort_analysis(db: Session = Depends(get_db), admin: AdminUser = admin_dep):
    """Get cohort analysis data."""
    analytics = AnalyticsService(db)
    return analytics.get_customer_metrics()


@router.get("/analytics/forecast")
def get_forecast(days_ahead: int = 30, db: Session = Depends(get_db), admin: AdminUser = admin_dep):
    """Get revenue forecast."""
    forecast = ForecastService(db)
    results = forecast.forecast_revenue(days_ahead)
    return {"forecasts": results}


@router.get("/analytics/insights")
def get_insights(db: Session = Depends(get_db), admin: AdminUser = admin_dep):
    """Get AI-generated business insights."""
    insights = InsightGenerationService(db)
    return {"insights": insights.generate_insights()}


@router.get("/analytics/fraud")
def get_fraud_events(status: Optional[str] = None, db: Session = Depends(get_db), admin: AdminUser = admin_dep):
    """Get fraud detection events."""
    from app.models import FraudDetectionEvent
    q = db.query(FraudDetectionEvent)
    if status:
        q = q.filter(FraudDetectionEvent.action_taken == status)
    events = q.order_by(FraudDetectionEvent.created_at.desc()).limit(50).all()
    return {
        "events": [
            {
                "id": e.id, "event_type": e.event_type, "order_id": e.order_id,
                "score": e.score, "indicators": e.indicators,
                "action_taken": e.action_taken, "created_at": e.created_at.isoformat(),
            }
            for e in events
        ],
    }


# ===== System 5: Payments =====

@router.get("/payments")
def list_payments(status: Optional[str] = None, db: Session = Depends(get_db), admin: AdminUser = admin_dep):
    """List payment transactions."""
    from app.models import PaymentLog
    q = db.query(PaymentLog)
    if status:
        q = q.filter(PaymentLog.status == status)
    payments = q.order_by(PaymentLog.created_at.desc()).limit(50).all()
    return {
        "payments": [
            {
                "id": p.id, "reference": p.transaction_reference,
                "provider": p.provider, "amount": p.amount,
                "currency": p.currency, "status": p.status,
                "created_at": p.created_at.isoformat(),
            }
            for p in payments
        ],
    }


@router.get("/affiliates")
def list_affiliates(db: Session = Depends(get_db), admin: AdminUser = admin_dep):
    """List all affiliates."""
    from app.models import Affiliate
    affiliates = db.query(Affiliate).order_by(Affiliate.created_at.desc()).limit(50).all()
    return {
        "affiliates": [
            {
                "id": a.id, "code": a.code, "name": a.name,
                "type": a.type, "status": a.status,
                "total_earned": a.total_earned, "total_conversions": a.total_conversions,
                "wallet_balance": a.wallet_balance,
            }
            for a in affiliates
        ],
    }
