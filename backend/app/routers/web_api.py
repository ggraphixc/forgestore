import logging
import os
import secrets
import hashlib
import hmac
from app.core.image_compressor import compress_image

from fastapi import APIRouter, Depends, HTTPException, Request, Response, UploadFile, File
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import or_, desc
import uuid
import random
import string
from datetime import datetime
from app.utils import utcnow
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
from app.services.payment_provider import get_payment_provider
from slowapi import Limiter
from slowapi.util import get_remote_address
import asyncio

chat_limiter = Limiter(key_func=get_remote_address)

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


@router.get("/orders")
def get_customer_orders(request: Request, db: Session = Depends(get_db)):
    customer = get_current_customer_from_cookie(request, db)
    if not customer:
        return {"orders": []}

    orders = db.query(Order).filter(
        Order.customer_id == customer.id
    ).order_by(desc(Order.created_at)).limit(20).all()

    return {"orders": [
        {
            "id": o.id,
            "order_number": o.order_number,
            "status": o.status.value if o.status else "PENDING",
            "total": o.total_amount,
            "created_at": o.created_at.isoformat() if o.created_at else None,
            "tracking_number": getattr(o, 'tracking_number', None),
        }
        for o in orders
    ]}


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
    date_part = utcnow().strftime("%Y%m%d")
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
        confirm_expires_at=utcnow() + timedelta(hours=48),
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
                timestamp=utcnow(),
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
                timestamp=utcnow(),
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


# --- PRODUCT CHAT ---

@router.get("/products/{product_id}/chat")
def get_product_chat(
    product_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Get chat messages for a product, newest last. Excludes hidden messages."""
    from app.models import ProductChatMessage

    messages = db.query(ProductChatMessage).filter(
        ProductChatMessage.product_id == product_id,
        ProductChatMessage.is_hidden == False,
    ).order_by(ProductChatMessage.created_at.asc()).limit(50).all()

    return {
        "messages": [
            {
                "id": m.id,
                "author_name": m.author_name,
                "content": m.content,
                "image_url": m.image_url,
                "is_admin": m.is_admin,
                "is_flagged": m.is_flagged,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ],
    }


@router.post("/products/{product_id}/chat")
@chat_limiter.limit("20/minute")
async def post_product_chat_message(
    product_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Post a chat message on a product. Rate-limited to 20/min per IP.
    Accepts JSON body or multipart form with optional image upload.
    """
    from app.models import ProductChatMessage

    # Verify product exists
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    content = ""
    author_name = ""
    image_url = None

    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" in content_type:
        form = await request.form()
        content = (form.get("content") or "").strip()
        author_name = (form.get("author_name") or "").strip()
        upload_file = form.get("image")
        if upload_file and hasattr(upload_file, "filename") and upload_file.filename:
            ext = upload_file.filename.rsplit(".", 1)[-1].lower() if "." in upload_file.filename else "jpg"
            if ext not in ("jpg", "jpeg", "png", "gif", "webp"):
                raise HTTPException(status_code=400, detail="Image must be jpg, png, gif, or webp")
            raw = await upload_file.read()
            from app.core.image_compressor import get_max_upload_size_bytes
            max_bytes = get_max_upload_size_bytes(db)
            if len(raw) > max_bytes:
                raise HTTPException(status_code=400, detail=f"File too large. Maximum size is {max_bytes // (1024*1024)}MB.")
            from app.core.cloudinary_upload import is_cloudinary_configured, upload_to_cloudinary
            if is_cloudinary_configured():
                image_url = upload_to_cloudinary(raw, folder="forgestore/chat")
            if not image_url:
                upload_dir = os.path.join("app", "static", "uploads", "chat")
                os.makedirs(upload_dir, exist_ok=True)
                compressed, ext = compress_image(raw)
                unique_name = f"chat-{int(utcnow().timestamp())}-{uuid.uuid4().hex[:8]}.{ext}"
                file_path = os.path.join(upload_dir, unique_name)
                with open(file_path, "wb") as f:
                    f.write(compressed)
                image_url = f"/static/uploads/chat/{unique_name}"
    else:
        data = await request.json()
        content = (data.get("content") or "").strip()
        author_name = (data.get("author_name") or "").strip()

    if not content and not image_url:
        raise HTTPException(status_code=400, detail="Message content or image is required")
    if content and len(content) > 1000:
        raise HTTPException(status_code=400, detail="Message too long (max 1000 chars)")

    customer = get_current_customer_from_cookie(request, db)
    author_name = author_name or (customer.name if customer else "Anonymous")

    msg = ProductChatMessage(
        product_id=product_id,
        user_id=customer.id if customer else None,
        author_name=author_name,
        content=content,
        image_url=image_url,
        is_admin=False,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)

    # Broadcast to WebSocket channel for real-time delivery
    try:
        from app.core.websocket_manager import ws_manager
        loop = asyncio.get_event_loop()
        loop.create_task(ws_manager.broadcast(f"chat:{product_id}", {
            "type": "chat:new_message",
            "message": {
                "id": msg.id,
                "author_name": msg.author_name,
                "content": msg.content,
                "image_url": msg.image_url,
                "is_admin": msg.is_admin,
                "created_at": msg.created_at.isoformat() if msg.created_at else None,
            },
        }))
    except Exception:
        pass  # WebSocket broadcast is best-effort

    return {
        "success": True,
        "message": {
            "id": msg.id,
            "author_name": msg.author_name,
            "content": msg.content,
            "image_url": msg.image_url,
            "is_admin": msg.is_admin,
            "created_at": msg.created_at.isoformat() if msg.created_at else None,
        },
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

    # ── Point Redemption (optional) ──
    points_redeemed = int(request.query_params.get("points", 0)) if hasattr(request.query_params, 'get') else 0
    points_discount = 0.0
    # Check loyalty_points_enabled setting
    from app.models import Settings as SettingsModel
    loyalty_setting = db.query(SettingsModel).filter(SettingsModel.key == "loyalty_points_enabled").first()
    loyalty_enabled = not loyalty_setting or loyalty_setting.value.lower() != "false"
    if loyalty_enabled and points_redeemed > 0 and customer and customer.attribute_points > 0:
        ratio_setting = db.query(SettingsModel).filter(SettingsModel.key == "points_to_currency_ratio").first()
        ratio = float(ratio_setting.value) if ratio_setting else 100.0
        if ratio > 0:
            max_redeemable = customer.attribute_points
            actual_redeemed = min(points_redeemed, max_redeemable)
            points_discount = actual_redeemed / ratio  # e.g. 1000 pts / 100 = 10 currency units
            customer.attribute_points -= actual_redeemed

    # ── Group cart items by retailer_id (vendor) ──
    from collections import defaultdict
    vendor_items: dict[str, list] = defaultdict(list)
    product_map = {}
    for ci in cart_items:
        product = db.query(Product).filter(Product.id == ci.product_id).first()
        if not product:
            continue
        vendor_key = product.retailer_id or "__unassigned__"
        vendor_items[vendor_key].append({
            "product": product,
            "quantity": ci.quantity,
            "price": product.discount_price if product.discount_price else product.price,
        })
        product_map[product.id] = product

    # ── Calculate shipping fees per vendor ──
    from app.models import Settings as SettingsModel
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

    # ── Compute totals ──
    grand_subtotal = 0.0
    total_shipping = 0.0
    total_tax = 0.0
    fulfillments_data = []

    for vendor_id, items in vendor_items.items():
        vendor_subtotal = sum(i["price"] * i["quantity"] for i in items)
        vendor_shipping = fee_per_vendor if fee_per_vendor > 0 else 0.0
        if free_threshold > 0 and vendor_subtotal >= free_threshold:
            vendor_shipping = 0.0
        vendor_tax = round(vendor_subtotal * tax_pct / 100, 2) if tax_pct > 0 else 0.0
        vendor_total = vendor_subtotal + vendor_shipping + vendor_tax

        # Resolve origin address from retailer bio/location
        origin = ""
        if vendor_id != "__unassigned__":
            retailer_obj = db.query(Retailer).filter(Retailer.id == vendor_id).first()
            if retailer_obj:
                origin = retailer_obj.bio or retailer_obj.location or retailer_obj.name

        fulfillments_data.append({
            "retailer_id": vendor_id if vendor_id != "__unassigned__" else None,
            "subtotal": vendor_subtotal,
            "shipping_fee": vendor_shipping,
            "tax_amount": vendor_tax,
            "total_amount": vendor_total,
            "origin_address": origin,
            "items": [
                {
                    "product_id": i["product"].id,
                    "name": i["product"].name,
                    "quantity": i["quantity"],
                    "price": i["price"],
                    "image": i["product"].images[0] if i["product"].images else None,
                }
                for i in items
            ],
        })

        grand_subtotal += vendor_subtotal
        total_shipping += vendor_shipping
        total_tax += vendor_tax

    # Apply points discount (capped at grand_subtotal)
    if points_discount > 0:
        points_discount = min(points_discount, grand_subtotal)

    total = grand_subtotal + total_shipping + total_tax - points_discount

    # ── Validate max order amount ──
    max_order_setting = db.query(SettingsModel).filter(SettingsModel.key == "max_order_amount").first()
    max_order_amount = float(max_order_setting.value) if max_order_setting else 0.0
    if max_order_amount > 0 and total > max_order_amount:
        raise HTTPException(status_code=400, detail=f"Order total ₦{total:,.2f} exceeds maximum allowed ₦{max_order_amount:,.2f}")

    # ── Create parent Order ──
    order = Order(
        order_number=generate_order_number(),
        status=OrderStatus.PENDING,
        total_amount=round(total, 2),
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

    # ── Create VendorFulfillment rows + OrderItems ──
    from app.models import VendorFulfillment
    for fd in fulfillments_data:
        fulfillment = VendorFulfillment(
            order_id=order.id,
            retailer_id=fd["retailer_id"],
            status="PENDING",
            subtotal=fd["subtotal"],
            shipping_fee=fd["shipping_fee"],
            tax_amount=fd["tax_amount"],
            total_amount=fd["total_amount"],
            items_json=fd["items"],
            origin_address=fd["origin_address"],
            destination_address=f"{shipping.address}",
        )
        db.add(fulfillment)

        # Also create legacy OrderItems for backward compat
        for item_data in fd["items"]:
            oi = OrderItem(
                quantity=item_data["quantity"],
                price=item_data["price"],
                product_id=item_data["product_id"],
                order_id=order.id,
            )
            db.add(oi)
            # Decrease inventory
            prod = product_map.get(item_data["product_id"])
            if prod:
                prod.inventory = max(0, prod.inventory - item_data["quantity"])
                prod.sold_count = (prod.sold_count or 0) + item_data["quantity"]

    # ── Record point redemption ──
    if points_discount > 0 and points_redeemed > 0:
        from app.models import PointRedemption
        ratio_setting = db.query(SettingsModel).filter(SettingsModel.key == "points_to_currency_ratio").first()
        ratio = float(ratio_setting.value) if ratio_setting else 100.0
        pr = PointRedemption(
            user_id=customer.id,
            points_redeemed=actual_redeemed,
            currency_value=points_discount,
            exchange_ratio=ratio,
            status="COMPLETED",
        )
        db.add(pr)

    # ── Record vendor-to-vendor affiliate commissions ──
    # (when an invited vendor's products are sold)

    # Clear cart
    for ci in cart_items:
        db.delete(ci)

    db.commit()

    # Create admin notification for the new order
    notif = AdminNotification(
        type="new_order",
        title="New Order Received",
        message=f"Order {order.order_number} from {shipping.name} — ₦{total:,.2f} ({len(fulfillments_data)} vendor fulfillments)",
        link=f"/admin/orders/{order.id}",
    )
    db.add(notif)

    # Check for low inventory on ordered products
    from app.services.notification_bus import push as bus_push
    for fd in fulfillments_data:
        for item_data in fd["items"]:
            p = product_map.get(item_data["product_id"])
            if p and 0 < p.inventory <= 5:
                low_notif = AdminNotification(
                    type="low_stock",
                    title="Low Stock Alert",
                    message=f"'{p.name}' only has {p.inventory} units left in inventory.",
                    link="/admin/catalog",
                )
                db.add(low_notif)
                bus_push("low_stock", low_notif.title, low_notif.message, low_notif.link)

    db.commit()

    # Push new order to real-time bus
    bus_push("new_order", notif.title, notif.message, notif.link)

    # ── Async email dispatch (non-blocking) ──
    from app.services.email_service import (
        send_order_confirmation_email,
        send_vendor_new_order_email,
    )
    from app.core.email import dispatch_email_background

    # ── WhatsApp order notifications (non-blocking) ──
    try:
        from app.core.notifications import (
            send_order_placed_whatsapp,
            send_new_order_vendor_whatsapp,
        )
        import asyncio

        # Get customer phone from shipping address or user profile
        customer_phone = shipping.phone or ""
        if not customer_phone and customer.phone:
            customer_phone = customer.phone

        # Build items summary for WhatsApp
        items_summary = ", ".join([
            f"{i['name']} x{i['quantity']}"
            for fd in fulfillments_data
            for i in fd.get("items", [])[:3]
        ])
        if len(fulfillments_data) > 0:
            total_items = sum(len(fd.get("items", [])) for fd in fulfillments_data)
            if total_items > 3:
                items_summary += f" (+{total_items - 3} more)"

        # Send to customer
        if customer_phone:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(send_order_placed_whatsapp(
                    customer_phone, order.order_number, total, items_summary
                ))
            except RuntimeError:
                pass

        # Send to each vendor
        for fd in fulfillments_data:
            if fd["retailer_id"]:
                retailer_obj = db.query(Retailer).filter(Retailer.id == fd["retailer_id"]).first()
                if retailer_obj and retailer_obj.phone:
                    vendor_items = ", ".join([
                        f"{i['name']} x{i['quantity']}" for i in fd.get("items", [])[:3]
                    ])
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(send_new_order_vendor_whatsapp(
                            retailer_obj.phone, order.order_number,
                            shipping.name, vendor_items, fd["subtotal"]
                        ))
                    except RuntimeError:
                        pass
    except Exception as e:
        logger.warning(f"WhatsApp notification dispatch failed: {e}")

    # Customer confirmation email (async)
    vendor_sections_for_email = []
    for fd in fulfillments_data:
        if fd["retailer_id"]:
            vendor_sections_for_email.append({
                "vendor_name": fd.get("retailer_name", "Vendor"),
                "subtotal": fd["subtotal"],
                "shipping_fee": fd["shipping_fee"],
            })
    items_table_for_email = [
        {"name": i["name"], "quantity": i["quantity"], "price": i["price"]}
        for fd in fulfillments_data
        for i in fd.get("items", [])
    ]
    summary_lines_for_email = [
        {"label": "Subtotal", "value": f"₦{grand_subtotal:,.2f}"},
        {"label": "Shipping", "value": f"₦{total_shipping:,.2f}"},
    ]
    if tax_enabled:
        summary_lines_for_email.append({"label": tax_name, "value": f"₦{total_tax:,.2f}"})
    if points_discount > 0:
        summary_lines_for_email.append({"label": "Points Discount", "value": f"-₦{points_discount:,.2f}"})
    summary_lines_for_email.append({"label": "Total", "value": f"₦{total:,.2f}"})

    # Generate invoice number if auto-invoice enabled
    invoice_number = ""
    auto_invoice_setting = db.query(SettingsModel).filter(SettingsModel.key == "auto_invoice_enabled").first()
    if auto_invoice_setting and auto_invoice_setting.value.lower() != "false":
        prefix_setting = db.query(SettingsModel).filter(SettingsModel.key == "invoice_prefix").first()
        prefix = prefix_setting.value if prefix_setting else "INV"
        invoice_number = f"{prefix}-{order.order_number}"

    send_order_confirmation_email(
        shipping.email, order.order_number, shipping.name,
        vendor_sections=vendor_sections_for_email,
        items_table=items_table_for_email,
        summary_lines=summary_lines_for_email,
        invoice_number=invoice_number,
    )

    # Per-vendor new-order notification emails (async, non-blocking)
    from app.models import AdminUser as AdminUserModel
    for fd in fulfillments_data:
        if fd["retailer_id"]:
            # Find vendor admin email
            vendor_admin = db.query(AdminUserModel).filter(
                AdminUserModel.vendor_id == fd["retailer_id"],
                AdminUserModel.role.value == "RETAILER",
            ).first()
            if vendor_admin and vendor_admin.email:
                send_vendor_new_order_email(
                    to_email=vendor_admin.email,
                    vendor_name=fd.get("retailer_name", "Vendor"),
                    order_number=order.order_number,
                    items=fd.get("items", []),
                    net_payout=fd["subtotal"] * (1 - 0.10),
                    commission=fd["subtotal"] * 0.10,
                    commission_pct=10.0,
                )

    # ── Trigger per-vendor auto-dispatch ──
    for fd in fulfillments_data:
        if fd["retailer_id"]:
            try:
                from app.services.wallet_service import auto_dispatch_shipment
                auto_dispatch_shipment(db, order.id)
            except Exception:
                pass

    # Initialize payment via abstraction layer
    from app.config import get_settings
    _settings = get_settings()
    base_url = _settings.site_base_url.rstrip("/")
    currency = get_currency(db)

    provider_name = getattr(_settings, 'default_payment_provider', 'paystack') or 'paystack'
    provider = get_payment_provider(provider_name)
    payment_result = provider.initialize_payment(
        email=shipping.email,
        amount=total,
        reference=order.order_number,
        callback_url=f"{base_url}/shop/checkout?order_id={order.id}&reference={order.order_number}",
        currency=currency,
        metadata={
            "order_id": order.id,
            "order_number": order.order_number,
            "vendor_count": len(fulfillments_data),
            "points_redeemed": points_redeemed,
            "points_discount": points_discount,
        },
    )

    if payment_result["success"]:
        return {
            "success": True,
            "order_id": order.id,
            "order_number": order.order_number,
            "payment_url": payment_result["authorization_url"],
            "access_code": payment_result.get("access_code", ""),
            "vendor_fulfillments": len(fulfillments_data),
            "points_discount": points_discount,
            "shipping_total": total_shipping,
        }
    else:
        logger.warning(
            "Payment init failed for order %s (provider=%s): %s",
            order.order_number,
            provider_name,
            payment_result.get("message"),
        )
        return {
            "success": True,
            "order_id": order.id,
            "order_number": order.order_number,
            "payment_url": None,
            "paystack_error": payment_result.get("message"),
        }


# --- CART CHECKOUT (create preliminary order from cart) ---

@router.post("/cart/checkout")
def cart_checkout(
    request: Request,
    db: Session = Depends(get_db),
):
    """Create a preliminary order from cart items, return order_id for checkout page."""
    cart_token = get_cart_token(request)
    cart_items = db.query(CartItem).filter(CartItem.cart_token == cart_token).all()

    if not cart_items:
        raise HTTPException(status_code=400, detail="Cart is empty")

    # Get or create customer
    customer = get_current_customer_from_cookie(request, db)
    if not customer:
        # Create guest customer with placeholder info
        guest_email = f"guest_{secrets.token_hex(8)}@forgestore.com"
        customer = User(
            email=guest_email,
            name="Guest",
            phone="",
            role="CUSTOMER",
        )
        db.add(customer)
        db.flush()

    # Calculate total
    subtotal = sum(ci.quantity * (ci.product.discount_price or ci.product.price) for ci in cart_items)

    # Create order with placeholder shipping (user will fill in on checkout page)
    from app.utils import utcnow as _utcnow
    order_number = f"FS-{secrets.token_hex(4).upper()}-{random.randint(1000,9999)}"
    order = Order(
        order_number=order_number,
        total_amount=subtotal,
        shipping_address={"placeholder": True},
        customer_id=customer.id,
        status="PENDING",
    )
    db.add(order)
    db.flush()

    # Create order items
    for ci in cart_items:
        oi = OrderItem(
            quantity=ci.quantity,
            price=ci.product.discount_price or ci.product.price,
            product_id=ci.product_id,
            order_id=order.id,
        )
        db.add(oi)

    # Clear cart
    for ci in cart_items:
        db.delete(ci)

    db.commit()

    return {"order_id": order.id}


# --- PAYMENT INITIALIZATION (for checkout page) ---

@router.post("/payments/initialize")
async def payments_initialize(
    request: Request,
    db: Session = Depends(get_db),
):
    """Initialize payment for an existing order (called by checkout page)."""
    body = await request.json()
    order_id = body.get("order_id")
    provider_name = body.get("provider", "paystack")

    if not order_id:
        raise HTTPException(status_code=400, detail="order_id required")

    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    # Handle Cash on Delivery
    if provider_name == "cod":
        from app.models import Settings as SettingsModel
        cod_setting = db.query(SettingsModel).filter(SettingsModel.key == "cod_enabled").first()
        if cod_setting and cod_setting.value.lower() == "false":
            raise HTTPException(status_code=400, detail="Cash on Delivery is not available")
        # Mark order as PENDING COD — no payment gateway call
        return {"authorization_url": "", "access_code": "", "cod": True, "message": "Order placed. Pay on delivery."}

    from app.config import get_settings
    _settings = get_settings()
    base_url = _settings.site_base_url.rstrip("/")
    currency = get_currency(db)

    provider = get_payment_provider(provider_name)
    payment_result = provider.initialize_payment(
        email=order.customer.email if order.customer else "guest@forgestore.com",
        amount=order.total_amount,
        reference=order.order_number,
        callback_url=f"{base_url}/shop/checkout?order_id={order.id}&reference={order.order_number}",
        currency=currency,
        metadata={
            "order_id": order.id,
            "order_number": order.order_number,
        },
    )

    if payment_result["success"]:
        return {
            "authorization_url": payment_result["authorization_url"],
            "access_code": payment_result.get("access_code", ""),
        }
    else:
        raise HTTPException(status_code=400, detail=payment_result.get("message", "Payment init failed"))


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

    # Enforce review length limits from settings
    from app.services.ai_service import get_setting
    min_len = int(get_setting(db, "reviews_min_length", "10"))
    max_len = int(get_setting(db, "reviews_max_length", "2000"))
    if data.content and len(data.content) < min_len:
        raise HTTPException(status_code=400, detail=f"Review must be at least {min_len} characters")
    if data.content and len(data.content) > max_len:
        raise HTTPException(status_code=400, detail=f"Review must be no more than {max_len} characters")

    # One review per user per product
    if customer:
        existing = db.query(Review).filter(
            Review.product_id == data.product_id,
            Review.user_id == customer.id,
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="You have already reviewed this product")

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

    # Auto-post review as first chat message to link review ↔ chat
    try:
        from app.models import ProductChatMessage
        stars = '⭐' * review.rating
        chat_content = f'[review:{review.rating}]' + (f' {review.content}' if review.content else '')
        chat_msg = ProductChatMessage(
            product_id=review.product_id,
            user_id=review.user_id,
            author_name=review.author,
            content=chat_content,
            is_admin=False,
        )
        db.add(chat_msg)
        db.commit()
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
    customer.updated_at = utcnow()
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
    customer.updated_at = utcnow()
    db.commit()
    return {"success": True}


@router.post("/customer/profile/delete")
def delete_customer_account(request: Request, response: Response, db: Session = Depends(get_db)):
    """Self-service account deletion for authenticated customers."""
    customer = get_current_customer_from_cookie(request, db)
    if not customer:
        raise HTTPException(status_code=401, detail="Not logged in")

    # Delete related records in correct order (items before orders)
    order_ids = [o.id for o in db.query(Order.id).filter(Order.customer_id == customer.id).subquery()]
    db.query(OrderItem).filter(OrderItem.order_id.in_(order_ids)).delete(synchronize_session=False)
    db.query(Order).filter(Order.customer_id == customer.id).delete(synchronize_session=False)
    db.query(Review).filter(Review.user_id == customer.id).delete(synchronize_session=False)

    # Anonymize user record
    customer.email = f"deleted_{customer.id}@example.com"
    customer.name = "Deleted User"
    customer.password = None
    customer.updated_at = utcnow()
    db.commit()

    response.delete_cookie("customer_token")
    return {"success": True, "message": "Account deleted successfully"}


# ─── Customer Return Requests ───────────────────────────────────────────────

@router.post("/returns/request")
def request_return(
    request: Request,
    db: Session = Depends(get_db),
):
    """Customer submits a return request for an order."""
    import asyncio
    import uuid
    from app.models import ReturnRequest, ReturnEvent, Shipment
    from app.services.delivery_pricing import calculate_return_fee

    customer = get_current_customer_from_cookie(request, db)
    if not customer:
        raise HTTPException(status_code=401, detail="Not logged in")

    loop = asyncio.new_event_loop()
    body = loop.run_until_complete(request.json())
    loop.close()

    order_id = body.get("order_id", "")
    reason = body.get("reason", "")
    description = body.get("description", "")

    if not order_id or not reason:
        raise HTTPException(status_code=400, detail="order_id and reason required")

    order = db.query(Order).filter(Order.id == order_id, Order.customer_id == customer.id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    # Check for existing return request
    existing = db.query(ReturnRequest).filter(ReturnRequest.order_id == order_id, ReturnRequest.status.notin_(["REJECTED", "REFUNDED"])).first()
    if existing:
        raise HTTPException(status_code=400, detail="Return already requested for this order")

    # Calculate return fee
    return_fee = calculate_return_fee(original_fee=0, weight_kg=0)

    rr = ReturnRequest(
        return_number=f"RET-{uuid.uuid4().hex[:8].upper()}",
        order_id=order.id,
        customer_id=customer.id,
        reason=reason,
        description=description,
        status="PENDING",
        return_fee=return_fee,
        pickup_address=order.shipping_address.get("address", "") if isinstance(order.shipping_address, dict) else "",
    )
    db.add(rr)
    db.flush()

    event = ReturnEvent(return_id=rr.id, status="PENDING", description=f"Return requested: {reason}", created_by=customer.id)
    db.add(event)
    db.commit()

    return {"ok": True, "return_number": rr.return_number, "return_fee": return_fee}
