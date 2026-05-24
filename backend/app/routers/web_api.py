import logging
import secrets
import hashlib
import hmac

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import or_
import uuid
import random
import string
from datetime import datetime
from urllib.parse import quote, unquote

logger = logging.getLogger("forgestore.checkout")

from app.database import get_db
from app.models import (
    Product, Category, Retailer, Order, OrderItem, Review,
    User, CartItem, WishlistItem, OrderStatus, Settings, AdminNotification,
    NewsletterSubscriber,
)
from app.schemas import CartAddRequest, CartUpdateRequest, CheckoutRequest, ReviewCreateRequest
from app.auth import get_current_customer_from_cookie
from app.services.ai_service import ai_search_assistant, get_ai_recommendations
from app.services.paystack_service import initialize_payment

router = APIRouter(prefix="/api", tags=["web-api"])


def get_cart_token(request: Request) -> str:
    """Get or create a cart token from cookies."""
    cart_token = request.cookies.get("cart_token")
    if not cart_token:
        cart_token = str(uuid.uuid4())
    return cart_token


def set_cart_token_cookie(response: JSONResponse, token: str):
    """Set cart token cookie."""
    response.set_cookie(
        key="cart_token",
        value=token,
        httponly=True,
        max_age=86400 * 30,  # 30 days
        secure=False,
        samesite="lax",
    )


def get_currency(db: Session) -> str:
    setting = db.query(Settings).filter(Settings.key == "currency").first()
    return setting.value if setting else "NGN"


# --- CART ENDPOINTS ---

@router.get("/cart")
def get_cart(request: Request, db: Session = Depends(get_db)):
    cart_token = get_cart_token(request)
    cart_items = db.query(CartItem).filter(CartItem.cart_token == cart_token).all()

    items = []
    total = 0.0

    for ci in cart_items:
        product = db.query(Product).filter(Product.id == ci.product_id).first()
        if not product:
            continue
        price = product.discount_price if product.discount_price else product.price
        subtotal = price * ci.quantity
        total += subtotal
        items.append({
            "product_id": product.id,
            "name": product.name,
            "price": price,
            "image": product.images[0] if product.images else None,
            "quantity": ci.quantity,
            "subtotal": subtotal,
        })

    return {"items": items, "total": total, "count": len(items)}


@router.post("/cart/add")
def add_to_cart(
    request: Request,
    data: CartAddRequest,
    db: Session = Depends(get_db),
):
    cart_token = get_cart_token(request)
    resp = JSONResponse({"success": True})

    # Verify product exists
    product = db.query(Product).filter(Product.id == data.product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # Check if already in cart
    existing = db.query(CartItem).filter(
        CartItem.cart_token == cart_token,
        CartItem.product_id == data.product_id,
    ).first()

    if existing:
        existing.quantity += data.quantity
    else:
        new_item = CartItem(
            cart_token=cart_token,
            product_id=data.product_id,
            quantity=data.quantity,
        )
        db.add(new_item)

    db.commit()
    set_cart_token_cookie(resp, cart_token)
    return resp


@router.put("/cart/update")
def update_cart(
    request: Request,
    data: CartUpdateRequest,
    db: Session = Depends(get_db),
):
    cart_token = get_cart_token(request)
    resp = JSONResponse({"success": True})

    existing = db.query(CartItem).filter(
        CartItem.cart_token == cart_token,
        CartItem.product_id == data.product_id,
    ).first()

    if not existing:
        raise HTTPException(status_code=404, detail="Item not found in cart")

    if data.quantity < 1:
        db.delete(existing)
    else:
        existing.quantity = data.quantity

    db.commit()
    set_cart_token_cookie(resp, cart_token)
    return resp


@router.delete("/cart/remove/{product_id}")
def remove_from_cart(
    request: Request,
    product_id: str,
    db: Session = Depends(get_db),
):
    cart_token = get_cart_token(request)
    resp = JSONResponse({"success": True})

    existing = db.query(CartItem).filter(
        CartItem.cart_token == cart_token,
        CartItem.product_id == product_id,
    ).first()

    if existing:
        db.delete(existing)
        db.commit()

    set_cart_token_cookie(resp, cart_token)
    return resp


# --- WISHLIST ENDPOINTS ---

@router.get("/wishlist")
def get_wishlist(request: Request, db: Session = Depends(get_db)):
    token = get_cart_token(request)
    items = db.query(WishlistItem).filter(WishlistItem.token == token).all()

    products = {}
    for wi in items:
        product = db.query(Product).filter(Product.id == wi.product_id).first()
        if product:
            products[wi.product_id] = {
                "id": product.id,
                "slug": product.slug,
                "name": product.name,
                "price": product.price,
                "discount_price": product.discount_price,
                "image": product.images[0] if product.images else None,
                "rating": product.rating,
                "review_count": product.review_count,
            }

    return {"items": list(products.values()), "count": len(products)}


@router.post("/wishlist/add")
def add_to_wishlist(
    request: Request,
    data: dict,
    db: Session = Depends(get_db),
):
    product_id = data.get("product_id", "")
    if not product_id:
        raise HTTPException(status_code=400, detail="product_id is required")

    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    token = get_cart_token(request)
    resp = JSONResponse({"success": True})

    existing = db.query(WishlistItem).filter(
        WishlistItem.token == token,
        WishlistItem.product_id == product_id,
    ).first()

    if existing:
        db.delete(existing)
        db.commit()
        set_cart_token_cookie(resp, token)
        return resp  # toggled off

    new_item = WishlistItem(token=token, product_id=product_id)
    db.add(new_item)
    db.commit()
    set_cart_token_cookie(resp, token)
    return resp


@router.delete("/wishlist/remove/{product_id}")
def remove_from_wishlist(
    request: Request,
    product_id: str,
    db: Session = Depends(get_db),
):
    token = get_cart_token(request)
    resp = JSONResponse({"success": True})

    existing = db.query(WishlistItem).filter(
        WishlistItem.token == token,
        WishlistItem.product_id == product_id,
    ).first()

    if existing:
        db.delete(existing)
        db.commit()

    set_cart_token_cookie(resp, token)
    return resp


# --- CHECKOUT ENDPOINT ---

def generate_order_number():
    """Generate a unique order number like: FS-20250315-A7K2"""
    date_part = datetime.utcnow().strftime("%Y%m%d")
    random_part = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"FS-{date_part}-{random_part}"


# --- AI PRODUCT RECOMMENDATIONS ---

@router.post("/ai/recommendations")
def ai_recommendations(
    data: dict,
    db: Session = Depends(get_db),
):
    """AI-powered product recommendations based on a product."""
    product_id = data.get("product_id", "")
    if not product_id:
        raise HTTPException(status_code=400, detail="product_id is required")

    current = db.query(Product).filter(Product.id == product_id).first()
    if not current:
        raise HTTPException(status_code=404, detail="Product not found")

    # Get categories and retailers for mapping
    categories = {c.id: c.name for c in db.query(Category).all()}

    # Prepare all products as dicts for AI
    all_products = db.query(Product).all()
    current_dict = {
        "id": current.id,
        "name": current.name,
        "category": categories.get(current.category_id, ""),
        "brand": current.brand or "",
        "price": current.price,
        "description": (current.description or "")[:200],
    }
    products_dict = [
        {
            "id": p.id,
            "name": p.name,
            "category": categories.get(p.category_id, ""),
            "brand": p.brand or "",
            "price": p.price,
            "description": (p.description or "")[:200],
        }
        for p in all_products
    ]

    recommended = get_ai_recommendations(current_dict, products_dict, max_results=4)

    if recommended:
        return {
            "success": True,
            "products": [
                {
                    "id": p.id,
                    "slug": p.slug,
                    "name": p.name,
                    "price": p.price,
                    "discount_price": p.discount_price,
                    "images": p.images,
                    "rating": p.rating,
                }
                for p in recommended
            ],
        }

    # Fallback: same category
    fallback = [
        p for p in all_products
        if p.id != current.id and (
            p.category_id == current.category_id or
            p.retailer_id == current.retailer_id
        )
    ]
    return {
        "success": True,
        "products": [
            {
                "id": p.id,
                "slug": p.slug,
                "name": p.name,
                "price": p.price,
                "discount_price": p.discount_price,
                "images": p.images,
                "rating": p.rating,
            }
            for p in fallback[:4]
        ],
    }


# --- NEWSLETTER SUBSCRIPTION ---

@router.post("/newsletter/subscribe")
def newsletter_subscribe(data: dict, db: Session = Depends(get_db)):
    """
    Subscribe an email to the newsletter.
    Sends a confirmation email (falls back to console if SMTP not configured).
    """
    from app.services.email_service import send_newsletter_confirmation_email
    from app.config import get_settings

    email = (data.get("email") or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="A valid email is required")

    existing = db.query(NewsletterSubscriber).filter(
        NewsletterSubscriber.email == email
    ).first()
    if existing:
        if existing.confirmed:
            return {"success": True, "message": "You're already subscribed!"}
        # Re-send confirmation
        token = existing.confirm_token or secrets.token_urlsafe(24)
        existing.confirm_token = token
        db.commit()
        _settings = get_settings()
        base_url = _settings.site_base_url.rstrip("/")
        confirm_url = f"{base_url}/api/newsletter/confirm?token={token}&email={email}"
        send_newsletter_confirmation_email(email, confirm_url)
        return {"success": True, "message": "Confirmation email re-sent. Please check your inbox."}

    from datetime import timedelta
    token = secrets.token_urlsafe(24)
    subscriber = NewsletterSubscriber(
        email=email,
        confirmed=False,
        confirm_token=token,
        confirm_expires_at=datetime.utcnow() + timedelta(hours=48),
    )
    db.add(subscriber)
    db.commit()

    # Send confirmation email
    _settings = get_settings()
    base_url = _settings.site_base_url.rstrip("/")
    confirm_url = f"{base_url}/api/newsletter/confirm?token={token}&email={email}"
    send_newsletter_confirmation_email(email, confirm_url)

    return {"success": True, "message": "Check your email to confirm your subscription!"}


@router.get("/newsletter/confirm")
def newsletter_confirm(email: str = "", token: str = "", db: Session = Depends(get_db)):
    """Confirm a newsletter subscription via token link."""
    if not email or not token:
        return HTMLResponse("<h2>Invalid confirmation link.</h2>")

    subscriber = db.query(NewsletterSubscriber).filter(
        NewsletterSubscriber.email == email,
        NewsletterSubscriber.confirm_token == token,
    ).first()

    if not subscriber:
        return HTMLResponse("<h2>Invalid or expired confirmation link.</h2>")

    subscriber.confirmed = True
    subscriber.confirm_token = None
    if not subscriber.unsubscribe_token:
        subscriber.unsubscribe_token = secrets.token_urlsafe(24)
    db.commit()

    # Also notify admins
    try:
        from app.services.notification_bus import push as bus_push
        notif = AdminNotification(
            type="newsletter",
            title="New Newsletter Subscriber",
            message=f"{email} confirmed their newsletter subscription.",
            link="/admin/settings",
        )
        db.add(notif)
        db.commit()
        bus_push("newsletter", notif.title, notif.message, notif.link)
    except Exception:
        pass

    return HTMLResponse("""
    <!DOCTYPE html>
    <html><head><meta charset="utf-8"><title>Subscribed!</title>
    <style>
        body { font-family: system-ui, sans-serif; display: flex; align-items: center; justify-content: center; min-height: 80vh; margin: 0; background: #fafaf9; }
        .card { text-align: center; background: white; padding: 48px 32px; border-radius: 16px; box-shadow: 0 4px 24px rgba(0,0,0,0.06); max-width: 400px; }
        h1 { font-size: 24px; color: #1c1917; margin-bottom: 8px; }
        p { color: #57534e; font-size: 14px; line-height: 1.6; }
        .check { font-size: 48px; margin-bottom: 16px; }
    </style>
    </head><body>
    <div class="card">
        <div class="check">&#10003;</div>
        <h1>You're subscribed!</h1>
        <p>Thank you for joining the ForgeStore newsletter. You'll hear from us soon.</p>
    </div>
    </body></html>
    """)


@router.get("/newsletter/open/{campaign_id}/{subscriber_id}")
def newsletter_tracking_open(
    campaign_id: str,
    subscriber_id: str,
    db: Session = Depends(get_db),
):
    """Tracking pixel endpoint — records an open event and returns a 1x1 transparent GIF."""
    from app.models import BroadcastCampaign, BroadcastEvent

    campaign = db.query(BroadcastCampaign).filter(BroadcastCampaign.id == campaign_id).first()
    subscriber = db.query(NewsletterSubscriber).filter(NewsletterSubscriber.id == subscriber_id).first()

    if campaign and subscriber:
        # Check if already opened (deduplicate)
        existing = db.query(BroadcastEvent).filter(
            BroadcastEvent.campaign_id == campaign_id,
            BroadcastEvent.subscriber_id == subscriber_id,
            BroadcastEvent.event_type == "opened",
        ).first()
        if not existing:
            event = BroadcastEvent(
                campaign_id=campaign_id,
                subscriber_id=subscriber_id,
                event_type="opened",
                timestamp=datetime.utcnow(),
            )
            db.add(event)
            # Update campaign count
            campaign.opened_count = db.query(BroadcastEvent).filter(
                BroadcastEvent.campaign_id == campaign_id,
                BroadcastEvent.event_type == "opened",
            ).count()
            db.commit()

    # Return 1x1 transparent GIF
    gif = b"GIF89a\x01\x00\x01\x00\x80\x01\x00\x00\x00\x00\xff\xff\xff\x21\xf9\x04\x01\x00\x00\x00\x00\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00\x3b"
    return Response(content=gif, media_type="image/gif")


@router.get("/newsletter/track/{campaign_id}/{subscriber_id}")
def newsletter_tracking_click(
    campaign_id: str,
    subscriber_id: str,
    url: str = "",
    sig: str = "",
    db: Session = Depends(get_db),
):
    """Click tracking redirect — records a click event and redirects to the target URL."""
    from app.models import BroadcastCampaign, BroadcastEvent
    from app.config import get_settings

    if not url or not sig:
        return HTMLResponse("<h2>Invalid tracking link.</h2>")

    decoded_url = unquote(url)

    # Verify signature
    _settings = get_settings()
    expected_sig = hmac.new(
        _settings.secret_key.encode() if _settings.secret_key else b"forgestore",
        f"{campaign_id}:{subscriber_id}:{decoded_url}".encode(),
        hashlib.sha256
    ).hexdigest()[:16]

    if sig != expected_sig:
        return HTMLResponse("<h2>Invalid or expired tracking link.</h2>")

    campaign = db.query(BroadcastCampaign).filter(BroadcastCampaign.id == campaign_id).first()
    subscriber = db.query(NewsletterSubscriber).filter(NewsletterSubscriber.id == subscriber_id).first()

    if campaign and subscriber:
        # Check if already clicked this URL (deduplicate per url)
        existing = db.query(BroadcastEvent).filter(
            BroadcastEvent.campaign_id == campaign_id,
            BroadcastEvent.subscriber_id == subscriber_id,
            BroadcastEvent.event_type == "clicked",
            BroadcastEvent.extra_data["url"].as_string() == decoded_url,
        ).first()
        if not existing:
            event = BroadcastEvent(
                campaign_id=campaign_id,
                subscriber_id=subscriber_id,
                event_type="clicked",
                extra_data={"url": decoded_url},
                timestamp=datetime.utcnow(),
            )
            db.add(event)
            campaign.clicked_count = db.query(BroadcastEvent).filter(
                BroadcastEvent.campaign_id == campaign_id,
                BroadcastEvent.event_type == "clicked",
            ).count()
            db.commit()

    return RedirectResponse(url=decoded_url, status_code=302)


@router.get("/newsletter/unsubscribe")
def newsletter_unsubscribe(email: str = "", token: str = "", db: Session = Depends(get_db)):
    """
    One-click unsubscribe from the newsletter.
    Requires email + unsubscribe_token for verification.
    """
    if not email or not token:
        return HTMLResponse("""
        <!DOCTYPE html>
        <html><head><meta charset="utf-8"><title>Unsubscribe</title>
        <style>
            body { font-family: system-ui, sans-serif; display: flex; align-items: center; justify-content: center; min-height: 80vh; margin: 0; background: #fafaf9; }
            .card { text-align: center; background: white; padding: 48px 32px; border-radius: 16px; box-shadow: 0 4px 24px rgba(0,0,0,0.06); max-width: 400px; }
            h1 { font-size: 24px; color: #1c1917; margin-bottom: 8px; }
            p { color: #57534e; font-size: 14px; line-height: 1.6; }
        </style>
        </head><body>
        <div class="card">
            <h1>Invalid link</h1>
            <p>This unsubscribe link is missing required information.</p>
        </div>
        </body></html>
        """)

    subscriber = db.query(NewsletterSubscriber).filter(
        NewsletterSubscriber.email == email,
        NewsletterSubscriber.unsubscribe_token == token,
    ).first()

    if not subscriber:
        return HTMLResponse("""
        <!DOCTYPE html>
        <html><head><meta charset="utf-8"><title>Unsubscribe</title>
        <style>
            body { font-family: system-ui, sans-serif; display: flex; align-items: center; justify-content: center; min-height: 80vh; margin: 0; background: #fafaf9; }
            .card { text-align: center; background: white; padding: 48px 32px; border-radius: 16px; box-shadow: 0 4px 24px rgba(0,0,0,0.06); max-width: 400px; }
            h1 { font-size: 24px; color: #1c1917; margin-bottom: 8px; }
            p { color: #57534e; font-size: 14px; line-height: 1.6; }
        </style>
        </head><body>
        <div class="card">
            <h1>Already unsubscribed</h1>
            <p>This email is not in our subscriber list or has already been removed.</p>
        </div>
        </body></html>
        """)

    db.delete(subscriber)
    db.commit()

    return HTMLResponse("""
    <!DOCTYPE html>
    <html><head><meta charset="utf-8"><title>Unsubscribed</title>
    <style>
        body { font-family: system-ui, sans-serif; display: flex; align-items: center; justify-content: center; min-height: 80vh; margin: 0; background: #fafaf9; }
        .card { text-align: center; background: white; padding: 48px 32px; border-radius: 16px; box-shadow: 0 4px 24px rgba(0,0,0,0.06); max-width: 400px; }
        h1 { font-size: 24px; color: #1c1917; margin-bottom: 8px; }
        p { color: #57534e; font-size: 14px; line-height: 1.6; }
        .check { font-size: 48px; margin-bottom: 16px; }
    </style>
    </head><body>
    <div class="card">
        <div class="check">&#10003;</div>
        <h1>You've been unsubscribed</h1>
        <p>You will no longer receive marketing emails from ForgeStore.</p>
    </div>
    </body></html>
    """)


# --- AI SEARCH ASSISTANT ---

@router.post("/ai/search")
def ai_search(
    data: dict,
    db: Session = Depends(get_db),
):
    """AI-powered natural language product search."""
    query = data.get("query", "")
    if not query:
        raise HTTPException(status_code=400, detail="Query is required")

    # Get all products
    products = db.query(Product).order_by(Product.rating.desc()).all()
    retailers = {r.id: r.name for r in db.query(Retailer).all()}
    categories = {c.id: c.name for c in db.query(Category).all()}

    # Try AI-powered search
    products_dict = [
        {
            "id": p.id,
            "name": p.name,
            "category": categories.get(p.category_id, ""),
            "brand": p.brand or "",
            "price": p.price,
            "description": p.description or "",
        }
        for p in products
    ]

    ai_result = ai_search_assistant(query, products_dict)

    if ai_result and "product_ids" in ai_result and ai_result["product_ids"]:
        id_set = set(ai_result["product_ids"])
        matched = [p for p in products if p.id in id_set]
        # Preserve AI's ordering
        id_order = {pid: idx for idx, pid in enumerate(ai_result["product_ids"])}
        matched.sort(key=lambda p: id_order.get(p.id, 999))

        return {
            "success": True,
            "message": ai_result.get("message", "Here are the best matches:"),
            "refined_query": ai_result.get("refined_query", query),
            "products": [
                {
                    "id": p.id,
                    "slug": p.slug,
                    "name": p.name,
                    "price": p.price,
                    "discount_price": p.discount_price,
                    "images": p.images,
                    "rating": p.rating,
                    "retailer_name": retailers.get(p.retailer_id, ""),
                    "inventory": p.inventory,
                }
                for p in matched[:6]
            ],
        }

    # Fallback: basic search
    search_term = f"%{query}%"
    fallback = db.query(Product).filter(
        Product.name.ilike(search_term) |
        Product.description.ilike(search_term)
    ).limit(6).all()

    return {
        "success": True,
        "message": "Found some matches via basic search:",
        "refined_query": query,
        "ai_fallback": True,
        "products": [
            {
                "id": p.id,
                "slug": p.slug,
                "name": p.name,
                "price": p.price,
                "discount_price": p.discount_price,
                "images": p.images,
                "rating": p.rating,
                "retailer_name": retailers.get(p.retailer_id, ""),
                "inventory": p.inventory,
            }
            for p in fallback
        ],
    }


@router.post("/checkout")
def checkout(
    request: Request,
    shipping: CheckoutRequest,
    db: Session = Depends(get_db),
):
    cart_token = get_cart_token(request)
    cart_items = db.query(CartItem).filter(CartItem.cart_token == cart_token).all()

    if not cart_items:
        raise HTTPException(status_code=400, detail="Cart is empty")

    # Resolve authenticated customer first, otherwise find by shipping email or create guest customer
    customer = get_current_customer_from_cookie(request, db)
    if not customer:
        customer = db.query(User).filter(User.email == shipping.email).first()
        if not customer:
            customer = User(
                email=shipping.email,
                name=shipping.name,
                password=None,  # Guest checkout — no password set
            )
            db.add(customer)
            db.flush()

    # Calculate total
    total = 0.0
    order_items_data = []
    for ci in cart_items:
        product = db.query(Product).filter(Product.id == ci.product_id).first()
        if not product:
            continue
        price = product.discount_price if product.discount_price else product.price
        subtotal = price * ci.quantity
        total += subtotal
        order_items_data.append({
            "product": product,
            "quantity": ci.quantity,
            "price": price,
        })

    # Create order
    order = Order(
        order_number=generate_order_number(),
        status=OrderStatus.PENDING,
        total_amount=total,
        shipping_address={
            "name": shipping.name,
            "email": shipping.email,
            "phone": shipping.phone,
            "address": shipping.address,
        },
        customer_id=customer.id,
    )
    db.add(order)
    db.flush()

    # Create order items
    for oi in order_items_data:
        item = OrderItem(
            quantity=oi["quantity"],
            price=oi["price"],
            product_id=oi["product"].id,
            order_id=order.id,
        )
        db.add(item)

        # Decrease inventory
        oi["product"].inventory = max(0, oi["product"].inventory - oi["quantity"])

    # Clear cart
    for ci in cart_items:
        db.delete(ci)

    db.commit()

    # Create admin notification for the new order
    notif = AdminNotification(
        type="new_order",
        title="New Order Received",
        message=f"Order {order.order_number} from {shipping.name} — ₦{total:,.2f}",
        link=f"/admin/orders/{order.id}",
    )
    db.add(notif)

    # Check for low inventory on ordered products
    from app.services.notification_bus import push as bus_push
    for oi_data in order_items_data:
        p = oi_data["product"]
        if 0 < p.inventory <= 5:
            low_notif = AdminNotification(
                type="low_stock",
                title="Low Stock Alert",
                message=f"'{p.name}' only has {p.inventory} units left in inventory.",
                link=f"/admin/catalog",
            )
            db.add(low_notif)
            bus_push("low_stock", low_notif.title, low_notif.message, low_notif.link)

    db.commit()

    # Push new order to real-time bus
    bus_push("new_order", notif.title, notif.message, notif.link)

    # Send order confirmation email
    from app.services.email_service import send_order_confirmation_email
    send_order_confirmation_email(shipping.email, order.order_number, shipping.name)

    # Initialize Paystack payment
    from app.config import get_settings
    _settings = get_settings()
    base_url = _settings.site_base_url.rstrip("/")
    currency = get_currency(db)
    paystack_result = initialize_payment(
        email=shipping.email,
        amount=total,
        order_id=order.id,
        order_number=order.order_number,
        callback_url=f"{base_url}/shop/checkout?order_id={order.id}&reference={order.order_number}",
        currency=currency,
    )

    if paystack_result["success"]:
        return {
            "success": True,
            "order_id": order.id,
            "order_number": order.order_number,
            "payment_url": paystack_result["authorization_url"],
            "access_code": paystack_result.get("access_code", ""),
        }
    else:
        logger.warning(
            "Paystack init failed for order %s: %s",
            order.order_number,
            paystack_result.get("message"),
        )
        # Return order created but payment not started
        return {
            "success": True,
            "order_id": order.id,
            "order_number": order.order_number,
            "payment_url": None,
            "paystack_error": paystack_result.get("message"),
        }


# --- SEARCH ---

@router.get("/search/suggestions")
def search_suggestions(
    q: str = "",
    db: Session = Depends(get_db),
):
    """Quick search suggestions for the live search dropdown (max 5 results)."""
    if not q or len(q.strip()) < 2:
        return {"suggestions": []}

    search_term = f"%{q}%"
    products = db.query(Product).filter(
        or_(
            Product.name.ilike(search_term),
            Product.brand.ilike(search_term),
        )
    ).order_by(Product.rating.desc()).limit(5).all()

    retailers = {r.id: r.name for r in db.query(Retailer).all()}

    return {
        "suggestions": [
            {
                "id": p.id,
                "slug": p.slug,
                "name": p.name,
                "price": p.price,
                "discount_price": p.discount_price,
                "image": p.images[0] if p.images else None,
                "retailer_name": retailers.get(p.retailer_id, ""),
            }
            for p in products
        ],
        "total": len(products),
    }


@router.get("/search")
def search_products(
    q: str = "",
    category: str = "",
    db: Session = Depends(get_db),
):
    query = db.query(Product)

    if q:
        search_term = f"%{q}%"
        query = query.filter(
            or_(
                Product.name.ilike(search_term),
                Product.description.ilike(search_term),
                Product.brand.ilike(search_term),
            )
        )

    if category:
        cat = db.query(Category).filter(Category.slug == category).first()
        if cat:
            query = query.filter(Product.category_id == cat.id)

    products = query.order_by(Product.created_at.desc()).limit(50).all()
    retailers = {r.id: r.name for r in db.query(Retailer).all()}

    return {
        "products": [
            {
                "id": p.id,
                "slug": p.slug,
                "name": p.name,
                "price": p.price,
                "discount_price": p.discount_price,
                "image": p.images[0] if p.images else None,
                "rating": p.rating,
                "review_count": p.review_count,
                "retailer_name": retailers.get(p.retailer_id),
                "inventory": p.inventory,
            }
            for p in products
        ],
        "total": len(products),
    }


# --- REVIEWS ---

@router.post("/reviews")
def submit_review(
    data: ReviewCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    # Get user from cookie if logged in, otherwise use anonymous
    customer = get_current_customer_from_cookie(request, db)

    # Validate product exists
    product = db.query(Product).filter(Product.id == data.product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # Validate rating
    if data.rating < 1 or data.rating > 5:
        raise HTTPException(status_code=400, detail="Rating must be between 1 and 5")

    review = Review(
        product_id=data.product_id,
        user_id=customer.id if customer else None,
        author=data.author or (customer.name if customer else "Anonymous"),
        rating=data.rating,
        title=data.title,
        content=data.content,
        helpful=0,
    )
    db.add(review)

    # Update product rating
    all_reviews = db.query(Review).filter(Review.product_id == data.product_id).all()
    product.rating = sum(r.rating for r in all_reviews) / len(all_reviews) if all_reviews else 0
    product.review_count = len(all_reviews)

    db.commit()

    # Notify admins of new review
    try:
        notif = AdminNotification(
            type="new_review",
            title="New Review Submitted",
            message=f"{review.author} reviewed '{product.name}' — {review.rating}/5 stars",
            link=f"/admin/catalog",
        )
        db.add(notif)
        db.commit()
        from app.services.notification_bus import push as bus_push
        bus_push("new_review", notif.title, notif.message, notif.link)
    except Exception:
        pass

    return {"success": True, "review_id": review.id}


# --- GET USER ORDERS (for web account) ---

@router.get("/orders")
def get_user_orders(request: Request, db: Session = Depends(get_db)):
    customer = get_current_customer_from_cookie(request, db)
    if not customer:
        raise HTTPException(status_code=401, detail="Not logged in")

    orders = db.query(Order).filter(
        Order.customer_id == customer.id
    ).order_by(Order.created_at.desc()).all()

    return {
        "orders": [
            {
                "id": o.id,
                "order_number": o.order_number,
                "status": o.status.value if hasattr(o.status, 'value') else o.status,
                "total_amount": o.total_amount,
                "created_at": o.created_at.isoformat() if o.created_at else None,
            }
            for o in orders
        ],
    }


@router.get("/orders/{order_id}")
def get_order_detail(
    order_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    customer = get_current_customer_from_cookie(request, db)
    if not customer:
        raise HTTPException(status_code=401, detail="Not logged in")

    order = db.query(Order).filter(
        Order.id == order_id,
        Order.customer_id == customer.id,
    ).first()

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    items = db.query(OrderItem).filter(OrderItem.order_id == order.id).all()
    product_ids = [i.product_id for i in items]
    products = {p.id: p for p in db.query(Product).filter(Product.id.in_(product_ids)).all()}

    return {
        "id": order.id,
        "order_number": order.order_number,
        "status": order.status.value if hasattr(order.status, 'value') else order.status,
        "total_amount": order.total_amount,
        "shipping_address": order.shipping_address,
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "items": [
            {
                "product_id": i.product_id,
                "product_name": products[i.product_id].name if i.product_id in products else "Unknown",
                "product_image": products[i.product_id].images[0] if i.product_id in products and products[i.product_id].images else None,
                "quantity": i.quantity,
                "price": i.price,
            }
            for i in items
        ],
    }


# --- Account Profile & Settings API ---

@router.get("/account/profile")
def get_profile(request: Request, db: Session = Depends(get_db)):
    """Get the current customer's profile."""
    customer = get_current_customer_from_cookie(request, db)
    if not customer:
        raise HTTPException(status_code=401, detail="Not logged in")
    return {
        "id": customer.id,
        "email": customer.email,
        "name": customer.name,
        "created_at": customer.created_at.isoformat() if customer.created_at else None,
    }


@router.put("/account/profile")
def update_profile(request: Request, data: dict, db: Session = Depends(get_db)):
    """Update the current customer's profile."""
    customer = get_current_customer_from_cookie(request, db)
    if not customer:
        raise HTTPException(status_code=401, detail="Not logged in")

    if "name" in data:
        customer.name = data["name"]
    customer.updated_at = datetime.utcnow()
    db.commit()
    return {"success": True}


@router.get("/account/reviews")
def get_user_reviews(request: Request, db: Session = Depends(get_db)):
    """Get the current customer's reviews."""
    customer = get_current_customer_from_cookie(request, db)
    if not customer:
        raise HTTPException(status_code=401, detail="Not logged in")

    reviews = db.query(Review).filter(
        Review.user_id == customer.id
    ).order_by(Review.created_at.desc()).all()

    product_ids = [r.product_id for r in reviews]
    products = {p.id: p for p in db.query(Product).filter(Product.id.in_(product_ids)).all()}

    return {
        "reviews": [
            {
                "id": r.id,
                "product_id": r.product_id,
                "product_name": products[r.product_id].name if r.product_id in products else "Unknown",
                "product_image": products[r.product_id].images[0] if r.product_id in products and products[r.product_id].images else None,
                "rating": r.rating,
                "title": r.title,
                "content": r.content,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in reviews
        ]
    }


@router.put("/account/password")
def change_password(request: Request, data: dict, db: Session = Depends(get_db)):
    """Change the current customer's password."""
    from app.auth import verify_password, hash_password

    customer = get_current_customer_from_cookie(request, db)
    if not customer:
        raise HTTPException(status_code=401, detail="Not logged in")

    current = data.get("current_password", "")
    new_pass = data.get("new_password", "")

    if not customer.password:
        raise HTTPException(status_code=400, detail="This account does not have a password set")

    if not verify_password(current, customer.password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    if len(new_pass) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters")

    customer.password = hash_password(new_pass)
    customer.updated_at = datetime.utcnow()
    db.commit()
    return {"success": True}
