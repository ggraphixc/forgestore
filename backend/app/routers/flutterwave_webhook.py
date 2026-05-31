"""
Flutterwave Webhook & Payment Verification Router

Handles:
- POST /api/flutterwave/webhook — Receives Flutterwave charge.completed callbacks
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
from app.config import get_settings
from app.utils import utcnow

logger = logging.getLogger("forgestore.flutterwave_webhook")

router = APIRouter(prefix="/api", tags=["flutterwave"])


def _get_setting_value(db: Session, key: str, default: str = "") -> str:
    s = db.query(Settings).filter(Settings.key == key).first()
    return s.value if s else default


def _settle_vendor_commission(db: Session, order_id: str, retailer_id: str, item_total: float, reference: str):
    """Compute platform commission, credit vendor wallet, record settlement."""
    commission_pct = float(_get_setting_value(db, "market_commission_percentage", "10.0"))
    commission = round(item_total * commission_pct / 100, 2)
    net = round(item_total - commission, 2)

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

    settlement = VendorSettlement(
        order_id=order_id, retailer_id=retailer_id,
        gross_amount=item_total, platform_commission_fee=commission,
        net_vendor_payout=net, commission_percentage=commission_pct,
        is_settled=True, settled_at=utcnow(),
        payment_reference=reference, provider="flutterwave",
    )
    db.add(settlement)
    return commission, net


def _create_vendor_low_stock_alert(db: Session, retailer_id: str, product_id: str, product_name: str, current_stock: int):
    limit = int(float(_get_setting_value(db, "low_stock_limit", "5")))
    if current_stock <= 0:
        severity, msg = "CRITICAL", f"'{product_name}' is OUT OF STOCK."
    elif current_stock <= limit:
        severity, msg = "WARNING", f"'{product_name}' has only {current_stock} unit(s) remaining."
    else:
        return
    notif = VendorNotification(
        retailer_id=retailer_id, message_text=msg,
        severity_level=severity, notification_type="low_stock",
        related_product_id=product_id,
    )
    db.add(notif)


@router.post("/flutterwave/webhook")
async def flutterwave_webhook(request: Request):
    """
    Receive Flutterwave webhook events with idempotency guard.
    """
    body = await request.body()
    body_str = body.decode("utf-8")

    settings = get_settings()
    expected_hash = settings.flutterwave_encryption_key
    received_hash = request.headers.get("verif-hash", "")

    if not expected_hash or received_hash != expected_hash:
        logger.warning("Invalid Flutterwave webhook verif-hash")
        return JSONResponse({"status": "invalid signature"}, status_code=401)

    try:
        event = json.loads(body_str)
    except json.JSONDecodeError:
        return JSONResponse({"status": "invalid JSON"}, status_code=400)

    logger.info("Flutterwave webhook received: %s", event.get("event"))

    event_type = event.get("event", "")
    if event_type not in ("charge.completed", "transfer.completed"):
        return JSONResponse({"status": "ignored"})

    data = event.get("data", {})
    tx_status = data.get("status", "")
    if tx_status != "successful":
        return JSONResponse({"status": "ignored"})

    reference = data.get("tx_ref", "") or data.get("flw_ref", "")
    event_id = data.get("id", "") or f"fw-{reference}"
    meta = data.get("meta", {}) or {}
    order_id = meta.get("order_id", "")

    if not order_id:
        db_check: Session = next(get_db())
        try:
            order = db_check.query(Order).filter(Order.order_number == reference).first()
            if order:
                order_id = order.id
        except Exception:
            pass
        finally:
            db_check.close()

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
                event_id=str(event_id), provider="flutterwave",
                event_type=event_type, payload_json=body_str[:5000],
                order_id=order_id, processed_status="PENDING",
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
                    message=f"Ad campaign '{campaign.id[:8]}' ({campaign.ad_type}) paid via Flutterwave.",
                    link="/admin/ads",
                )
                db.add(notif)
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

        items = db.query(OrderItem).filter(OrderItem.order_id == order_id).all()
        for item in items:
            product = db.query(Product).filter(Product.id == item.product_id).first()
            if product:
                product.inventory = max(0, product.inventory - item.quantity)
                if product.retailer_id:
                    _create_vendor_low_stock_alert(db, product.retailer_id, product.id, product.name, product.inventory)

            if product and product.retailer_id:
                retailer = db.query(Retailer).filter(Retailer.id == product.retailer_id).first()
                if retailer:
                    item_total = item.price * item.quantity
                    commission_rate = retailer.commission_rate or 10.0
                    commission = round(item_total * commission_rate / 100, 2)
                    net_amount = round(item_total - commission, 2)
                    earning = OrderEarning(
                        order_id=order_id, retailer_id=product.retailer_id,
                        product_id=product.id, amount=item_total,
                        commission=commission, net_amount=net_amount, status="SCHEDULED",
                    )
                    db.add(earning)
                    _settle_vendor_commission(db, order_id, product.retailer_id, item_total, reference)

        notif = AdminNotification(
            type="payment_received", title="Payment Received",
            message=f"Order {order.order_number} paid — ₦{order.total_amount:,.2f} via Flutterwave",
            link=f"/admin/orders/{order.id}",
        )
        db.add(notif)

        from app.services.email_service import send_order_status_email
        customer = db.query(User).filter(User.id == order.customer_id).first()
        if customer and customer.email:
            try:
                send_order_status_email(customer.email, order.order_number, customer.name or "Customer", "PAID")
            except Exception:
                logger.exception("Failed to send payment email")

        wl = db.query(WebhookPayloadLog).filter(WebhookPayloadLog.event_id == str(event_id)).first()
        if wl:
            wl.processed_status = "PROCESSED"
            wl.processed_at = utcnow()

        db.commit()
        logger.info("Order %s marked as PAID via Flutterwave. Ref: %s", order.order_number, reference)
    except Exception:
        db.rollback()
        try:
            wl = db.query(WebhookPayloadLog).filter(WebhookPayloadLog.event_id == str(event_id)).first()
            if wl:
                wl.processed_status = "FAILED"
                wl.error_message = str(Exception)[:500]
                wl.retry_count += 1
                db.commit()
        except Exception:
            pass
        logger.exception("Failed to process Flutterwave webhook for order %s", order_id)
        return JSONResponse({"status": "error"}, status_code=500)
    finally:
        db.close()

    return JSONResponse({"status": "success"})
