"""
Orders Router — multi-vendor mixed cart checkout with automated Paystack split-payments.

Processes mixed carts containing products from multiple vendors, splits the transaction
at the gateway level via Paystack subaccounts, and provisions per-vendor fulfillment rows.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import func
from collections import defaultdict
import uuid
import logging

from app.database import get_db
from app.models import (
    Product, Retailer, Order, OrderItem, OrderStatus,
    User, CartItem, VendorFulfillment, Settings as SettingsModel,
    VendorWallet, VendorWalletTransaction,
)
from app.auth import get_current_customer_from_cookie
from app.utils import utcnow

logger = logging.getLogger("app.orders")

router = APIRouter(prefix="/api/orders", tags=["orders"])


def _generate_order_number() -> str:
    """Generate a unique order number."""
    import random, string
    ts = uuid.uuid4().hex[:8].upper()
    rand = "".join(random.choices(string.digits, k=4))
    return f"FS-{ts}-{rand}"


@router.post("/checkout")
async def checkout_mixed_cart(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Process a mixed multi-vendor cart with automated Paystack split-payments.

    Reads cart items from the request body, groups by vendor, calculates splits,
    creates parent Order + VendorFulfillment rows, and initializes Paystack
    split transaction at the gateway level.

    Request body:
        {
            "items": [{"product_id": "...", "quantity": 1}, ...],
            "email": "customer@example.com",
            "name": "Customer Name",
            "phone": "+234...",
            "address": "Shipping address"
        }
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid request body")

    cart_entries = body.get("items", [])
    email = body.get("email", "")
    name = body.get("name", "")
    phone = body.get("phone", "")
    address = body.get("address", "")

    if not cart_entries:
        raise HTTPException(status_code=400, detail="Cannot initialize checkout on an empty shopping cart")

    if not email:
        raise HTTPException(status_code=400, detail="Customer email is required")

    # 1. Group items by vendor, validate products, compute subtotals
    items_by_vendor: dict[str, int] = defaultdict(int)  # vendor_id -> subtotal_kobo
    processed_items = []
    total_cart_kobo = 0

    for entry in cart_entries:
        product_id = entry.get("product_id", "")
        quantity = int(entry.get("quantity", 1))

        product = db.query(Product).filter(
            Product.id == product_id,
        ).first()
        if not product:
            raise HTTPException(status_code=404, detail=f"Product {product_id} not found")
        # Check inventory if tracking enabled
        from app.models import Settings as SettingsModel
        inv_setting = db.query(SettingsModel).filter(SettingsModel.key == "inventory_tracking_enabled").first()
        inv_enabled = not inv_setting or inv_setting.value.lower() != "false"
        if inv_enabled and product.inventory < quantity:
            raise HTTPException(status_code=400, detail=f"Insufficient stock for '{product.name}'")

        effective_price = product.discount_price if product.discount_price and product.discount_price < product.price else product.price
        item_price_kobo = int(round(effective_price * 100))
        subtotal_kobo = item_price_kobo * quantity

        total_cart_kobo += subtotal_kobo
        vendor_key = product.retailer_id or "__unassigned__"
        items_by_vendor[vendor_key] += subtotal_kobo

        processed_items.append({
            "product": product,
            "quantity": quantity,
            "price": effective_price,
            "subtotal_kobo": subtotal_kobo,
        })

    if total_cart_kobo <= 0:
        raise HTTPException(status_code=400, detail="Cart total is zero")

    # 2. Resolve or create customer
    customer = get_current_customer_from_cookie(request, db)
    if not customer:
        customer = db.query(User).filter(User.email == email).first()
        if not customer:
            customer = User(email=email, name=name, password=None)
            db.add(customer)
            db.flush()

    # 3. Calculate shipping per vendor
    shipping_setting = db.query(SettingsModel).filter(SettingsModel.key == "shipping_fee_per_vendor").first()
    fee_per_vendor = float(shipping_setting.value) if shipping_setting else 0.0
    free_threshold_setting = db.query(SettingsModel).filter(SettingsModel.key == "free_shipping_threshold").first()
    free_threshold = float(free_threshold_setting.value) if free_threshold_setting else 0.0
    tax_setting = db.query(SettingsModel).filter(SettingsModel.key == "tax_percentage").first()
    tax_pct = float(tax_setting.value) if tax_setting else 0.0
    # Respect tax_enabled toggle
    tax_enabled_setting = db.query(SettingsModel).filter(SettingsModel.key == "tax_enabled").first()
    if tax_enabled_setting and tax_enabled_setting.value.lower() == "false":
        tax_pct = 0.0
    tax_name_setting = db.query(SettingsModel).filter(SettingsModel.key == "tax_name").first()
    tax_name = tax_name_setting.value if tax_name_setting else "Tax"

    grand_subtotal = 0.0
    total_shipping = 0.0
    total_tax = 0.0
    fulfillments_data = []

    for vendor_id, vendor_subtotal_kobo in items_by_vendor.items():
        vendor_subtotal_naira = vendor_subtotal_kobo / 100.0
        vendor_shipping = fee_per_vendor if fee_per_vendor > 0 else 0.0
        if free_threshold > 0 and vendor_subtotal_naira >= free_threshold:
            vendor_shipping = 0.0
        vendor_tax = round(vendor_subtotal_naira * tax_pct / 100, 2) if tax_pct > 0 else 0.0
        vendor_total = vendor_subtotal_naira + vendor_shipping + vendor_tax

        # Get vendor items for this fulfillment
        vendor_items_list = [i for i in processed_items if (i["product"].retailer_id or "__unassigned__") == vendor_id]

        fulfillments_data.append({
            "retailer_id": vendor_id if vendor_id != "__unassigned__" else None,
            "subtotal": vendor_subtotal_naira,
            "shipping_fee": vendor_shipping,
            "tax_amount": vendor_tax,
            "total_amount": vendor_total,
            "items": [
                {
                    "product_id": i["product"].id,
                    "name": i["product"].name,
                    "quantity": i["quantity"],
                    "price": i["price"],
                    "image": i["product"].images[0] if i["product"].images else None,
                }
                for i in vendor_items_list
            ],
        })

        grand_subtotal += vendor_subtotal_naira
        total_shipping += vendor_shipping
        total_tax += vendor_tax

    total_naira = grand_subtotal + total_shipping + total_tax
    total_kobo = int(round(total_naira * 100))

    # Validate max order amount
    max_order_setting = db.query(SettingsModel).filter(SettingsModel.key == "max_order_amount").first()
    max_order_amount = float(max_order_setting.value) if max_order_setting else 0.0
    if max_order_amount > 0 and total_naira > max_order_amount:
        raise HTTPException(status_code=400, detail=f"Order total ₦{total_naira:,.2f} exceeds maximum allowed ₦{max_order_amount:,.2f}")

    # 4. Create parent Order
    order_reference = f"FS-ORD-{uuid.uuid4().hex[:8].upper()}"

    order = Order(
        order_number=order_reference,
        status=OrderStatus.PENDING,
        total_amount=round(total_naira, 2),
        shipping_address={
            "name": name,
            "email": email,
            "phone": phone,
            "address": address,
        },
        customer_id=customer.id,
    )
    db.add(order)
    db.flush()

    # 5. Create VendorFulfillment rows + OrderItems + decrease inventory
    for fd in fulfillments_data:
        fulfillment = VendorFulfillment(
            order_id=order.id,
            retailer_id=fd["retailer_id"],
            status="PENDING_PAYMENT",
            subtotal=fd["subtotal"],
            shipping_fee=fd["shipping_fee"],
            tax_amount=fd["tax_amount"],
            total_amount=fd["total_amount"],
            items_json=fd["items"],
            destination_address=address,
        )
        db.add(fulfillment)

        for item_data in fd["items"]:
            oi = OrderItem(
                quantity=item_data["quantity"],
                price=item_data["price"],
                product_id=item_data["product_id"],
                order_id=order.id,
            )
            db.add(oi)

            # Decrease inventory
            prod = db.query(Product).filter(Product.id == item_data["product_id"]).first()
            if prod:
                prod.inventory = max(0, prod.inventory - item_data["quantity"])

    db.commit()

    # 6. Build Paystack split payload and initialize transaction
    from app.services.split_payments import build_paystack_split_payload
    from app.config import get_settings

    settings = get_settings()
    site_base_url = settings.site_base_url.rstrip("/")

    url, headers, payload = await build_paystack_split_payload(
        db=db,
        email=email,
        order_reference=order_reference,
        total_amount_kobo=total_kobo,
        items_by_vendor=dict(items_by_vendor),
    )

    # Add metadata to payload
    payload["metadata"] = {
        "order_id": order.id,
        "order_number": order.order_number,
        "vendor_count": len(fulfillments_data),
    }

    # 7. Execute Paystack transaction initialization
    import httpx

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            response = await client.post(url, headers=headers, json=payload)
            gateway_data = response.json()
        except Exception as exc:
            logger.error("Paystack init failed: %s", exc)
            gateway_data = {"status": False, "message": str(exc)}

    if not gateway_data.get("status"):
        logger.warning("Paystack init rejected: %s", gateway_data.get("message", "Unknown"))
        # Order stays PENDING_PAYMENT — customer can retry or webhook will resolve

    # 8. Send order confirmation email
    try:
        from app.core.email import dispatch_email_background
        from app.services.email_service import send_order_confirmation_email
        summary_lines = [
            {"label": "Subtotal", "value": f"₦{grand_subtotal:,.2f}"},
            {"label": "Shipping", "value": f"₦{total_shipping:,.2f}"},
            {"label": "Tax", "value": f"₦{total_tax:,.2f}"},
            {"label": "Total", "value": f"₦{total_naira:,.2f}"},
        ]
        items_table = [
            {"name": i["name"], "quantity": i["quantity"], "price": i["price"]}
            for fd in fulfillments_data
            for i in fd.get("items", [])
        ]
        background_tasks.add_task(
            send_order_confirmation_email,
            email, order.order_number, name,
            vendor_sections=[],
            items_table=items_table,
            summary_lines=summary_lines,
        )
    except Exception:
        pass

    return {
        "success": gateway_data.get("status", False),
        "order_id": order.id,
        "order_number": order.order_number,
        "checkout_url": gateway_data.get("data", {}).get("authorization_url", ""),
        "total": total_naira,
        "split_executed": "split" in payload,
        "vendor_count": len(fulfillments_data),
    }
