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
from app.models import Order, OrderStatus, OrderItem, Product, AdminNotification, User, AdCampaign, OrderEarning, Retailer
from app.services.paystack_service import verify_webhook_signature, verify_payment

logger = logging.getLogger("forgestore.paystack_webhook")

router = APIRouter(prefix="/api", tags=["paystack"])


@router.post("/paystack/webhook")
async def paystack_webhook(request: Request):
    """
    Receive Paystack webhook events.

    Expects:
        - x-paystack-signature header for HMAC-SHA512 verification
        - JSON body with event type and data

    Processes:
        - charge.success → marks order as PAID, decrements inventory
    """
    # Read raw body for signature verification
    body = await request.body()
    body_str = body.decode("utf-8")

    # Verify signature
    signature = request.headers.get("x-paystack-signature", "")
    if not verify_webhook_signature(signature, body_str):
        logger.warning("Invalid Paystack webhook signature")
        return JSONResponse({"status": "invalid signature"}, status_code=401)

    # Parse event
    try:
        event = json.loads(body_str)
    except json.JSONDecodeError:
        logger.error("Failed to parse Paystack webhook body")
        return JSONResponse({"status": "invalid JSON"}, status_code=400)

    logger.info("Paystack webhook received: %s", event.get("event"))

    # Only handle charge.success
    if event.get("event") != "charge.success":
        return JSONResponse({"status": "ignored"})

    data = event.get("data", {})
    tx_status = data.get("status", "")
    if tx_status != "success":
        logger.info("Transaction not successful (%s), skipping", tx_status)
        return JSONResponse({"status": "ignored"})

    reference = data.get("reference", "")
    metadata = data.get("metadata", {}) or {}
    order_id = metadata.get("order_id", "")

    if not order_id:
        logger.error("No order_id in Paystack webhook metadata")
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
                    "Ad campaign %s paid via Paystack (ref: %s, type: %s)",
                    campaign.id, reference, campaign.ad_type,
                )
                campaign.status = "PAID"

                notif = AdminNotification(
                    type="ad_payment",
                    title="Ad Campaign Payment Received",
                    message=(
                        f"Ad campaign '{campaign.id[:8]}' ({campaign.ad_type}) paid via Paystack. "
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

        # Decrement inventory and create OrderEarning records
        items = db.query(OrderItem).filter(OrderItem.order_id == order_id).all()
        for item in items:
            product = db.query(Product).filter(Product.id == item.product_id).first()
            if product:
                product.inventory = max(0, product.inventory - item.quantity)

            # Create OrderEarning for the retailer
            if product and product.retailer_id:
                retailer = db.query(Retailer).filter(Retailer.id == product.retailer_id).first()
                if retailer:
                    commission_rate = retailer.commission_rate or 10.0
                    item_total = item.price * item.quantity
                    commission = round(item_total * commission_rate / 100, 2)
                    net_amount = round(item_total - commission, 2)

                    earning = OrderEarning(
                        order_id=order_id,
                        retailer_id=product.retailer_id,
                        product_id=product.id,
                        amount=item_total,
                        commission=commission,
                        net_amount=net_amount,
                        status="SCHEDULED",
                    )
                    db.add(earning)

        # Admin notification
        notif = AdminNotification(
            type="payment_received",
            title="Payment Received",
            message=(
                f"Order {order.order_number} paid — "
                f"₦{order.total_amount:,.2f} via Paystack"
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
            "Order %s marked as PAID. Ref: %s, Tx ID: %s",
            order.order_number,
            reference,
            data.get("id"),
        )
    except Exception:
        db.rollback()
        logger.exception("Failed to process Paystack webhook for order %s", order_id)
        return JSONResponse({"status": "error"}, status_code=500)
    finally:
        db.close()

    return JSONResponse({"status": "success"})


@router.get("/payments/verify/{reference}")
def verify_payment_endpoint(reference: str):
    """
    Verify a Paystack payment by reference (order number).
    Used by the frontend order-success page to confirm payment status.
    """
    result = verify_payment(reference)

    if result["success"] and result.get("paid"):
        # If payment is confirmed, update the order status
        db: Session = next(get_db())
        try:
            order = (
                db.query(Order)
                .filter(Order.order_number == reference)
                .first()
            )
            if order and order.status != OrderStatus.PAID:
                order.status = OrderStatus.PAID
                db.commit()
                logger.info(
                    "Order %s marked as PAID via verification endpoint",
                    reference,
                )
        except Exception:
            logger.exception("Failed to update order status on verification")
        finally:
            db.close()

        return JSONResponse({
            "success": True,
            "paid": True,
            "status": result["status"],
            "amount": result["amount"],
            "currency": result["currency"],
            "gateway_response": result.get("gateway_response", ""),
        })

    # Payment not confirmed
    if result["success"]:
        return JSONResponse({
            "success": True,
            "paid": False,
            "status": result["status"],
            "amount": result["amount"],
            "currency": result["currency"],
            "gateway_response": result.get("gateway_response", ""),
        })

    return JSONResponse(
        {"success": False, "message": result.get("message", "Verification failed")},
        status_code=400,
    )
