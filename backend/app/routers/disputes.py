"""
Dispute & Escrow Refund Router — customer dispute creation + admin resolution.

Endpoints:
  - POST /api/disputes/create — Customer files dispute
  - POST /api/admin/disputes/{id}/reject — Admin rejects dispute
  - POST /api/admin/disputes/{id}/approve-refund — Admin approves refund
  - GET /api/admin/disputes — List all disputes
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    OrderDispute, Order, VendorFulfillment, VendorWallet, VendorWalletTransaction,
    AdminUser, AdminRole, User, Retailer, Settings,
)
from app.auth import get_current_user_from_cookie, require_admin_role, log_admin_action
from app.core.email import dispatch_email_background
from app.services.email_service import _render_email_template, _base_context
from app.utils import utcnow

logger = logging.getLogger("forgestore.disputes")

router = APIRouter(tags=["disputes"])


def _get_setting_value(db: Session, key: str, default: str = "") -> str:
    s = db.query(Settings).filter(Settings.key == key).first()
    return s.value if s else default


@router.post("/api/disputes/create")
def create_dispute(
    data: dict,
    request: Request,
    db: Session = Depends(get_db),
):
    """Customer files a dispute against an order/fulfillment."""
    from app.core.security import decode_token

    token = request.cookies.get("customer_token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")
    user_id = payload.get("sub", "")

    order_id = data.get("order_id", "")
    vendor_fulfillment_id = data.get("vendor_fulfillment_id")
    reason_category = data.get("reason_category", "OTHER")
    explanation = data.get("explanation_text", "")

    if not order_id:
        raise HTTPException(status_code=400, detail="order_id is required")

    valid_categories = ["DAMAGED_ITEM", "NOT_RECEIVED", "WRONG_ITEM", "QUALITY_ISSUE", "OTHER"]
    if reason_category not in valid_categories:
        raise HTTPException(status_code=400, detail=f"reason_category must be one of {valid_categories}")

    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.customer_id != user_id:
        raise HTTPException(status_code=403, detail="Not your order")

    # Get vendor_fulfillment info for retailer_id
    retailer_id = None
    if vendor_fulfillment_id:
        vf = db.query(VendorFulfillment).filter(VendorFulfillment.id == vendor_fulfillment_id).first()
        if vf:
            retailer_id = vf.retailer_id
            vf.status = "DISPUTED"
    else:
        # Find first fulfillment for this order
        vf = db.query(VendorFulfillment).filter(VendorFulfillment.order_id == order_id).first()
        if vf:
            vendor_fulfillment_id = vf.id
            retailer_id = vf.retailer_id
            vf.status = "DISPUTED"

    dispute = OrderDispute(
        order_id=order_id,
        vendor_fulfillment_id=vendor_fulfillment_id,
        customer_id=user_id,
        retailer_id=retailer_id,
        reason_category=reason_category,
        explanation_text=explanation,
        status="OPEN",
        evidence_attachments_json=data.get("evidence", []),
    )
    db.add(dispute)
    db.commit()
    db.refresh(dispute)

    logger.info("Dispute created: %s for order %s", dispute.id, order_id)
    return {"success": True, "dispute_id": dispute.id, "status": "OPEN"}


@router.get("/api/admin/disputes")
def list_disputes(
    status: str = "",
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_admin_role(AdminRole.DIR_ADMIN, AdminRole.MANAGEMENT)),
):
    """List all disputes with optional status filter."""
    query = db.query(OrderDispute)
    if status:
        query = query.filter(OrderDispute.status == status)
    disputes = query.order_by(OrderDispute.created_at.desc()).limit(100).all()

    return {
        "disputes": [
            {
                "id": d.id,
                "order_id": d.order_id,
                "customer_id": d.customer_id,
                "retailer_id": d.retailer_id,
                "reason_category": d.reason_category,
                "explanation_text": d.explanation_text,
                "status": d.status,
                "refund_amount": d.refund_amount,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in disputes
        ]
    }


@router.post("/api/admin/disputes/{dispute_id}/reject")
def reject_dispute(
    dispute_id: str,
    data: dict,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_admin_role(AdminRole.DIR_ADMIN, AdminRole.MANAGEMENT)),
):
    """Reject a dispute — release escrow hold and credit vendor wallet."""
    dispute = db.query(OrderDispute).filter(OrderDispute.id == dispute_id).first()
    if not dispute:
        raise HTTPException(status_code=404, detail="Dispute not found")
    if dispute.status not in ("OPEN", "UNDER_REVIEW"):
        raise HTTPException(status_code=400, detail=f"Cannot reject dispute in status: {dispute.status}")

    dispute.status = "RESOLVED_REJECTED"
    dispute.resolution_notes = data.get("notes", "Dispute rejected by admin")
    dispute.resolved_by = admin.id
    dispute.resolved_at = utcnow()

    # Release fulfillment hold
    if dispute.vendor_fulfillment_id:
        vf = db.query(VendorFulfillment).filter(VendorFulfillment.id == dispute.vendor_fulfillment_id).first()
        if vf:
            vf.status = "PROCESSING"
            # WhatsApp alert on fulfillment status change
            try:
                from app.core.notifications import send_order_status_whatsapp
                order_obj = db.query(Order).filter(Order.id == dispute.order_id).first()
                if order_obj and order_obj.customer_id:
                    from app.models import User
                    cust = db.query(User).filter(User.id == order_obj.customer_id).first()
                    if cust and cust.phone:
                        import asyncio
                        try:
                            loop = asyncio.get_running_loop()
                            loop.create_task(send_order_status_whatsapp(
                                cust.phone, order_obj.order_number, "PROCESSING"
                            ))
                        except RuntimeError:
                            pass
            except Exception:
                pass

    # Credit vendor wallet (release escrowed funds)
    if dispute.retailer_id:
        wallet = db.query(VendorWallet).filter(VendorWallet.retailer_id == dispute.retailer_id).first()
        if wallet and wallet.locked_escrow_balance > 0:
            release_amount = min(wallet.locked_escrow_balance, dispute.refund_amount or 0)
            if release_amount > 0:
                wallet.locked_escrow_balance -= release_amount
                wallet.balance += release_amount
                tx = VendorWalletTransaction(
                    wallet_id=wallet.id,
                    transaction_type="dispute_release",
                    amount=release_amount,
                    balance_before=wallet.balance - release_amount,
                    balance_after=wallet.balance,
                    order_id=dispute.order_id,
                    reference=f"DISPUTE-REJECT-{dispute.id[:8]}",
                    description=f"Dispute rejected — ₦{release_amount:.2f} released from escrow",
                    status="COMPLETED",
                )
                db.add(tx)

    db.commit()
    log_admin_action(db, admin, "reject_dispute", "dispute", dispute_id,
                     f"Rejected dispute for order {dispute.order_id}")

    # Notify customer
    try:
        order = db.query(Order).filter(Order.id == dispute.order_id).first()
        customer = db.query(User).filter(User.id == dispute.customer_id).first()
        if customer and customer.email:
            html = _render_email_template("order_status.html", _base_context(
                heading="Dispute Update",
                subtitle=f"Order {order.order_number if order else ''}",
                body_html=f"<p>Your dispute has been reviewed and rejected. The vendor has been cleared.</p>",
                customer_name=customer.name or "Customer",
                order_number=order.order_number if order else "",
                status="REVIEWED",
                tracking_number="",
            ))
            dispatch_email_background(customer.email, "Dispute Update — ForgeStore", html)
    except Exception:
        pass

    return {"success": True, "status": "RESOLVED_REJECTED"}


@router.post("/api/admin/disputes/{dispute_id}/approve-refund")
def approve_refund(
    dispute_id: str,
    data: dict,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_admin_role(AdminRole.DIR_ADMIN, AdminRole.MANAGEMENT)),
):
    """Approve a refund — trigger payment gateway reverse transaction."""
    dispute = db.query(OrderDispute).filter(OrderDispute.id == dispute_id).first()
    if not dispute:
        raise HTTPException(status_code=404, detail="Dispute not found")
    if dispute.status not in ("OPEN", "UNDER_REVIEW"):
        raise HTTPException(status_code=400, detail=f"Cannot refund dispute in status: {dispute.status}")

    order = db.query(Order).filter(Order.id == dispute.order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    refund_amount = data.get("refund_amount", order.total_amount)
    dispute.status = "RESOLVED_REFUNDED"
    dispute.refund_amount = refund_amount
    dispute.resolution_notes = data.get("notes", "Refund approved by admin")
    dispute.resolved_by = admin.id
    dispute.resolved_at = utcnow()

    # Release fulfillment
    if dispute.vendor_fulfillment_id:
        vf = db.query(VendorFulfillment).filter(VendorFulfillment.id == dispute.vendor_fulfillment_id).first()
        if vf:
            vf.status = "CANCELLED"
            # WhatsApp alert on fulfillment cancellation
            try:
                from app.core.notifications import send_order_status_whatsapp
                order_obj = db.query(Order).filter(Order.id == dispute.order_id).first()
                if order_obj and order_obj.customer_id:
                    from app.models import User
                    cust = db.query(User).filter(User.id == order_obj.customer_id).first()
                    if cust and cust.phone:
                        import asyncio
                        try:
                            loop = asyncio.get_running_loop()
                            loop.create_task(send_order_status_whatsapp(
                                cust.phone, order_obj.order_number, "CANCELLED"
                            ))
                        except RuntimeError:
                            pass
            except Exception:
                pass

    # Deduct from vendor locked escrow
    if dispute.retailer_id:
        wallet = db.query(VendorWallet).filter(VendorWallet.retailer_id == dispute.retailer_id).first()
        if wallet:
            deduct = min(wallet.locked_escrow_balance, refund_amount)
            wallet.locked_escrow_balance = max(0, wallet.locked_escrow_balance - deduct)
            if deduct > 0:
                tx = VendorWalletTransaction(
                    wallet_id=wallet.id,
                    transaction_type="refund",
                    amount=-deduct,
                    balance_before=wallet.balance,
                    balance_after=wallet.balance,
                    order_id=dispute.order_id,
                    reference=f"DISPUTE-REFUND-{dispute.id[:8]}",
                    description=f"Dispute refund — ₦{deduct:.2f} deducted from escrow",
                    status="COMPLETED",
                )
                db.add(tx)

    # Attempt payment gateway refund
    refund_result = {"status": "manual_review_required"}
    try:
        from app.services.payment_provider import get_payment_provider
        from app.config import get_settings
        cfg = get_settings()
        provider_name = getattr(cfg, "default_payment_provider", "paystack") or "paystack"
        provider = get_payment_provider(provider_name)
        result = provider.refund(order.order_number, refund_amount)
        refund_result = result
        if result.get("success"):
            refund_result["status"] = "gateway_refunded"
    except Exception as exc:
        logger.warning("Gateway refund failed: %s", exc)
        refund_result = {"status": "gateway_error", "error": str(exc)}

    db.commit()
    log_admin_action(db, admin, "approve_refund", "dispute", dispute_id,
                     f"Approved refund ₦{refund_amount:.2f} for order {order.order_number}")

    # Notify customer
    try:
        customer = db.query(User).filter(User.id == dispute.customer_id).first()
        if customer and customer.email:
            html = _render_email_template("order_status.html", _base_context(
                heading="Refund Processed",
                subtitle=f"Order {order.order_number}",
                body_html=f"<p>Your refund of <strong>₦{refund_amount:,.2f}</strong> has been processed. It may take 3-5 business days to reflect.</p>",
                customer_name=customer.name or "Customer",
                order_number=order.order_number,
                status="REFUNDED",
                tracking_number="",
            ))
            dispatch_email_background(customer.email, "Refund Processed — ForgeStore", html)
    except Exception:
        pass

    return {"success": True, "status": "RESOLVED_REFUNDED", "refund_amount": refund_amount, "gateway": refund_result}
