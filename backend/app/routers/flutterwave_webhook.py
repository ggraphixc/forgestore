"""
Flutterwave Webhook & Payment Verification Router

Handles:
- POST /api/flutterwave/webhook — Receives Flutterwave charge.completed callbacks

Flutterwave webhook signature verification:
Flutterwave sends a `verif-hash` header that matches the webhook hash you configure
in your Flutterwave dashboard. It's a static token comparison — NOT an HMAC of the body
(which is different from Paystack's HMAC-SHA512 approach).
"""
import json
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Order, OrderStatus, OrderItem, Product, AdminNotification, User, AdCampaign
from app.config import get_settings

logger = logging.getLogger("forgestore.flutterwave_webhook")

router = APIRouter(prefix="/api", tags=["flutterwave"])


@router.post("/flutterwave/webhook")
async def flutterwave_webhook(request: Request):
    """
    Receive Flutterwave webhook events.

    Flutterwave sends a POST with:
        - `verif-hash` header — static token you set in Flutterwave dashboard
        - JSON body with event type and data

    The verif-hash is compared against `flutterwave_encryption_key` (serves as the
    shared secret that matches what you configure in the Flutterwave webhook settings).

    Processes:
        - charge.completed / transfer.completed → marks order as PAID, decrements inventory
    """
    # Read raw body
    body = await request.body()
    body_str = body.decode("utf-8")

    # Flutterwave verif-hash is a static token comparison — NOT HMAC.
    # Compare against the encryption key (which serves as our shared secret).
    settings = get_settings()
    expected_hash = settings.flutterwave_encryption_key
    received_hash = request.headers.get("verif-hash", "")

    if not expected_hash or received_hash != expected_hash:
        logger.warning(
            "Invalid Flutterwave webhook verif-hash (received: %s, expected match)",
            received_hash[:8] + "..." if received_hash else "none",
        )
        return JSONResponse({"status": "invalid signature"}, status_code=401)

    # Parse event
    try:
        event = json.loads(body_str)
    except json.JSONDecodeError:
        logger.error("Failed to parse Flutterwave webhook body")
        return JSONResponse({"status": "invalid JSON"}, status_code=400)

    logger.info("Flutterwave webhook received: %s", event.get("event"))

    # Only handle charge.completed / transfer.completed
    event_type = event.get("event", "")
    if event_type not in ("charge.completed", "transfer.completed"):
        return JSONResponse({"status": "ignored"})

    data = event.get("data", {})
    tx_status = data.get("status", "")
    if tx_status != "successful":
        logger.info("Transaction not successful (%s), skipping", tx_status)
        return JSONResponse({"status": "ignored"})

    reference = data.get("tx_ref", "") or data.get("flw_ref", "")
    meta = data.get("meta", {}) or {}
    order_id = meta.get("order_id", "")

    if not order_id:
        # Fallback: look up order by transaction reference (order_number)
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
        logger.error("No order_id found for Flutterwave webhook (tx_ref: %s)", reference)
        return JSONResponse({"status": "missing order_id"}, status_code=400)

    # Process order payment and ad campaign in a new DB session
    db: Session = next(get_db())
    try:
        # --- Check for Ad Campaign payment first ---
        campaign = db.query(AdCampaign).filter(
            AdCampaign.payment_reference == reference
        ).first()
        if campaign:
            if campaign.status in ("PENDING", "PAID"):
                logger.info(
                    "Ad campaign %s paid via Flutterwave (ref: %s, type: %s)",
                    campaign.id, reference, campaign.ad_type,
                )
                campaign.status = "PAID"

                notif = AdminNotification(
                    type="ad_payment",
                    title="Ad Campaign Payment Received",
                    message=(
                        f"Ad campaign '{campaign.id[:8]}' ({campaign.ad_type}) paid via Flutterwave. "
                        f"Go to Ads section to activate it."
                    ),
                    link="/admin/ads",
                )
                db.add(notif)
                db.commit()
                logger.info("Ad campaign %s marked as PAID", campaign.id)
            db.close()
            return JSONResponse({"status": "success"})

        # --- Process order payment ---
        order = db.query(Order).filter(Order.id == order_id).first()
        if not order:
            logger.error("Order not found: %s", order_id)
            db.close()
            return JSONResponse({"status": "order not found"}, status_code=404)

        if order.status == OrderStatus.PAID:
            logger.info("Order %s already PAID, skipping", order.order_number)
            db.close()
            return JSONResponse({"status": "already processed"})

        # Mark order as PAID
        order.status = OrderStatus.PAID
        db.flush()

        # Decrement inventory
        items = db.query(OrderItem).filter(OrderItem.order_id == order_id).all()
        for item in items:
            product = db.query(Product).filter(Product.id == item.product_id).first()
            if product:
                product.inventory = max(0, product.inventory - item.quantity)

        # Admin notification
        notif = AdminNotification(
            type="payment_received",
            title="Payment Received",
            message=(
                f"Order {order.order_number} paid — "
                f"₦{order.total_amount:,.2f} via Flutterwave"
            ),
            link=f"/admin/orders/{order.id}",
        )
        db.add(notif)

        # Send payment confirmation email
        from app.services.email_service import send_order_status_email
        customer = db.query(User).filter(User.id == order.customer_id).first()
        if customer and customer.email:
            try:
                send_order_status_email(
                    customer.email,
                    order.order_number,
                    customer.name or "Customer",
                    "PAID"
                )
            except Exception:
                logger.exception("Failed to send payment email")

        db.commit()

        logger.info(
            "Order %s marked as PAID via Flutterwave. Tx Ref: %s",
            order.order_number,
            reference,
        )
    except Exception:
        db.rollback()
        logger.exception("Failed to process Flutterwave webhook for order %s", order_id)
        return JSONResponse({"status": "error"}, status_code=500)
    finally:
        db.close()

    return JSONResponse({"status": "success"})
