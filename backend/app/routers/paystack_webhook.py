"""
Paystack Webhook & Payment Verification Router

Handles:
- POST /api/paystack/webhook — Receives Paystack charge.success callbacks
- GET  /api/payments/verify/{reference} — Verifies a payment status
"""
import json
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    Order, OrderStatus, OrderItem, Product, AdminNotification, User,
    AdCampaign, OrderEarning, Retailer, WebhookPayloadLog, VendorSettlement,
    VendorWallet, VendorWalletTransaction, VendorNotification, Settings,
)
from app.services.paystack_service import verify_webhook_signature, verify_payment

logger = logging.getLogger("forgestore.paystack_webhook")

router = APIRouter(prefix="/api", tags=["paystack"])


def _get_setting_value(db: Session, key: str, default: str = "") -> str:
    s = db.query(Settings).filter(Settings.key == key).first()
    return s.value if s else default


def _settle_vendor_commission(db: Session, order_id: str, retailer_id: str, item_total: float, reference: str):
    """Compute platform commission, credit vendor wallet, record settlement."""
    from app.utils import utcnow
    commission_pct = float(_get_setting_value(db, "market_commission_percentage", "10.0"))
    commission = round(item_total * commission_pct / 100, 2)
    net = round(item_total - commission, 2)

    # Credit vendor wallet
    wallet = db.query(VendorWallet).filter(VendorWallet.retailer_id == retailer_id).first()
    if wallet:
        bal_before = wallet.balance
        wallet.balance += net
        tx = VendorWalletTransaction(
            wallet_id=wallet.id,
            transaction_type="sale_earning",
            amount=net,
            balance_before=bal_before,
            balance_after=wallet.balance,
            order_id=order_id,
            reference=reference,
            description=f"Earning from order — ₦{net:.2f} (commission: ₦{commission:.2f})",
            status="COMPLETED",
        )
        db.add(tx)

    # Record settlement audit log
    settlement = VendorSettlement(
        order_id=order_id,
        retailer_id=retailer_id,
        gross_amount=item_total,
        platform_commission_fee=commission,
        net_vendor_payout=net,
        commission_percentage=commission_pct,
        is_settled=True,
        settled_at=utcnow(),
        payment_reference=reference,
        provider="paystack",
    )
    db.add(settlement)

    return commission, net


def _create_vendor_low_stock_alert(db: Session, retailer_id: str, product_id: str, product_name: str, current_stock: int):
    """Create a low-stock notification for the vendor."""
    limit = int(float(_get_setting_value(db, "low_stock_limit", "5")))
    if current_stock <= 0:
        severity = "CRITICAL"
        msg = f"'{product_name}' is OUT OF STOCK."
    elif current_stock <= limit:
        severity = "WARNING"
        msg = f"'{product_name}' has only {current_stock} unit(s) remaining."
    else:
        return

    notif = VendorNotification(
        retailer_id=retailer_id,
        message_text=msg,
        severity_level=severity,
        notification_type="low_stock",
        related_product_id=product_id,
    )
    db.add(notif)


@router.post("/paystack/webhook")
async def paystack_webhook(request: Request):
    """
    Receive Paystack webhook events with idempotency guard.
    """
    body = await request.body()
    body_str = body.decode("utf-8")

    signature = request.headers.get("x-paystack-signature", "")
    if not verify_webhook_signature(signature, body_str):
        logger.warning("Invalid Paystack webhook signature")
        return JSONResponse({"status": "invalid signature"}, status_code=401)

    try:
        event = json.loads(body_str)
    except json.JSONDecodeError:
        logger.error("Failed to parse Paystack webhook body")
        return JSONResponse({"status": "invalid JSON"}, status_code=400)

    logger.info("Paystack webhook received: %s", event.get("event"))

    if event.get("event") != "charge.success":
        return JSONResponse({"status": "ignored"})

    data = event.get("data", {})
    tx_status = data.get("status", "")
    if tx_status != "success":
        return JSONResponse({"status": "ignored"})

    reference = data.get("reference", "")
    event_id = data.get("id", "") or f"ps-{reference}"
    metadata = data.get("metadata", {}) or {}
    order_id = metadata.get("order_id", "")

    if not order_id:
        return JSONResponse({"status": "missing order_id"}, status_code=400)

    # --- IDEMPOTENCY GUARD ---
    db: Session = next(get_db())
    try:
        existing = db.query(WebhookPayloadLog).filter(WebhookPayloadLog.event_id == str(event_id)).first()
        if existing and existing.processed_status == "PROCESSED":
            logger.info("Duplicate webhook %s — already processed", event_id)
            db.close()
            return JSONResponse({"status": "already processed"})
        if not existing:
            log_entry = WebhookPayloadLog(
                event_id=str(event_id),
                provider="paystack",
                event_type=event.get("event"),
                payload_json=body_str[:5000],
                order_id=order_id,
                processed_status="PENDING",
            )
            db.add(log_entry)
            db.commit()
    except Exception:
        db.rollback()

    try:
        # --- Ad Campaign payment ---
        campaign = db.query(AdCampaign).filter(AdCampaign.payment_reference == reference).first()
        if campaign:
            if campaign.status in ("PENDING", "PAID"):
                campaign.status = "PAID"
                notif = AdminNotification(
                    type="ad_payment", title="Ad Campaign Payment Received",
                    message=f"Ad campaign '{campaign.id[:8]}' ({campaign.ad_type}) paid via Paystack.",
                    link="/admin/ads",
                )
                db.add(notif)
                # Mark webhook as processed
                wl = db.query(WebhookPayloadLog).filter(WebhookPayloadLog.event_id == str(event_id)).first()
                if wl:
                    wl.processed_status = "PROCESSED"
                    wl.processed_at = utcnow()
                db.commit()
            db.close()
            return JSONResponse({"status": "success"})

        # --- Order payment ---
        order = db.query(Order).filter(Order.id == order_id).first()
        if not order:
            db.close()
            return JSONResponse({"status": "order not found"}, status_code=404)

        if order.status == OrderStatus.PAID:
            db.close()
            return JSONResponse({"status": "already processed"})

        order.status = OrderStatus.PAID
        db.flush()

        # Process items: inventory, earnings, commission settlement, low-stock alerts
        items = db.query(OrderItem).filter(OrderItem.order_id == order_id).all()
        for item in items:
            product = db.query(Product).filter(Product.id == item.product_id).first()
            if product:
                product.inventory = max(0, product.inventory - item.quantity)
                # Low-stock alert
                if product.retailer_id:
                    _create_vendor_low_stock_alert(db, product.retailer_id, product.id, product.name, product.inventory)

            if product and product.retailer_id:
                retailer = db.query(Retailer).filter(Retailer.id == product.retailer_id).first()
                if retailer:
                    item_total = item.price * item.quantity
                    # OrderEarning record
                    commission_rate = retailer.commission_rate or 10.0
                    commission = round(item_total * commission_rate / 100, 2)
                    net_amount = round(item_total - commission, 2)
                    earning = OrderEarning(
                        order_id=order_id, retailer_id=product.retailer_id,
                        product_id=product.id, amount=item_total,
                        commission=commission, net_amount=net_amount, status="SCHEDULED",
                    )
                    db.add(earning)
                    # Commission settlement + wallet credit
                    _settle_vendor_commission(db, order_id, product.retailer_id, item_total, reference)

        # Admin notification
        notif = AdminNotification(
            type="payment_received", title="Payment Received",
            message=f"Order {order.order_number} paid — ₦{order.total_amount:,.2f} via Paystack",
            link=f"/admin/orders/{order.id}",
        )
        db.add(notif)

        # Send payment confirmation email
        from app.services.email_service import send_order_status_email
        customer = db.query(User).filter(User.id == order.customer_id).first()
        if customer and customer.email:
            try:
                send_order_status_email(customer.email, order.order_number, customer.name or "Customer", "PAID")
            except Exception:
                logger.exception("Failed to send payment email")

        # Mark webhook as processed
        wl = db.query(WebhookPayloadLog).filter(WebhookPayloadLog.event_id == str(event_id)).first()
        if wl:
            wl.processed_status = "PROCESSED"
            wl.processed_at = utcnow()

        db.commit()
        logger.info("Order %s marked as PAID. Ref: %s", order.order_number, reference)
    except Exception:
        db.rollback()
        # Mark webhook as FAILED for retry
        try:
            wl = db.query(WebhookPayloadLog).filter(WebhookPayloadLog.event_id == str(event_id)).first()
            if wl:
                wl.processed_status = "FAILED"
                wl.error_message = str(Exception)[:500]
                wl.retry_count += 1
                db.commit()
        except Exception:
            pass
        logger.exception("Failed to process Paystack webhook for order %s", order_id)
        return JSONResponse({"status": "error"}, status_code=500)
    finally:
        db.close()

    return JSONResponse({"status": "success"})


@router.get("/payments/verify/{reference}")
def verify_payment_endpoint(reference: str):
    """
    Verify a Paystack payment by reference (order number).
    """
    result = verify_payment(reference)

    if result["success"] and result.get("paid"):
        db: Session = next(get_db())
        try:
            order = db.query(Order).filter(Order.order_number == reference).first()
            if order and order.status != OrderStatus.PAID:
                order.status = OrderStatus.PAID
                db.commit()
        except Exception:
            logger.exception("Failed to update order status on verification")
        finally:
            db.close()

        return JSONResponse({
            "success": True, "paid": True,
            "status": result["status"], "amount": result["amount"],
            "currency": result["currency"],
            "gateway_response": result.get("gateway_response", ""),
        })

    if result["success"]:
        return JSONResponse({
            "success": True, "paid": False,
            "status": result["status"], "amount": result["amount"],
            "currency": result["currency"],
            "gateway_response": result.get("gateway_response", ""),
        })

    return JSONResponse(
        {"success": False, "message": result.get("message", "Verification failed")},
        status_code=400,
    )
