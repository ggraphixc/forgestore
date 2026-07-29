"""
Capacitor Mobile App API endpoints.

Provides config, icon, biometric, and offline-sync data for the
native mobile shell (Capacitor bridge).
"""

import logging
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.database import get_db
from app.models import Settings, User, CartItem, WishlistItem, Order, OrderItem, Product
from app.auth import get_current_customer_from_cookie

logger = logging.getLogger("forgestore.app_api")

router = APIRouter(prefix="/api/app", tags=["capacitor-app"])


# ─── 1. App Icon from admin settings logo_url ────────────────────────
@router.get("/icon")
async def get_app_icon(db: Session = Depends(get_db)):
    """Return the logo_url from admin settings for the native app icon."""
    logo = db.query(Settings).filter(Settings.key == "logo_url").first()
    favicon = db.query(Settings).filter(Settings.key == "favicon_url").first()
    return JSONResponse({
        "logo_url": logo.value if logo and logo.value else None,
        "favicon_url": favicon.value if favicon and favicon.value else "/static/img/icon-192.png",
    })


# ─── 2. App Name from admin settings site_name ──────────────────────
@router.get("/config")
async def get_app_config(db: Session = Depends(get_db)):
    """Return site_name and other app config from admin settings."""
    site_name = db.query(Settings).filter(Settings.key == "site_name").first()
    brand_letter = db.query(Settings).filter(Settings.key == "brand_letter_mark").first()
    return JSONResponse({
        "app_name": site_name.value if site_name and site_name.value else "ForgeStore",
        "brand_letter_mark": brand_letter.value if brand_letter and brand_letter.value else "F",
    })


# ─── 4. Biometric Login settings ────────────────────────────────────
@router.get("/biometric")
async def get_biometric_settings(
    request: Request,
    db: Session = Depends(get_db),
):
    """Check if biometric login is available and enabled for the current user."""
    user = get_current_customer_from_cookie(request, db)
    biometric_setting = db.query(Settings).filter(Settings.key == "biometric_login_enabled").first()
    enabled = biometric_setting and biometric_setting.value.lower() == "true"
    return JSONResponse({
        "biometric_enabled": enabled,
        "user_logged_in": user is not None,
        "user_id": user.id if user else None,
    })


# ─── 5. Offline-first Data Sync ─────────────────────────────────────
@router.get("/sync")
async def sync_offline_data(
    request: Request,
    db: Session = Depends(get_db),
):
    """Return cart, wishlist, and recent orders for offline caching."""
    user = get_current_customer_from_cookie(request, db)
    cart_token = request.cookies.get("cart_token", "")

    # Cart items (from cookie token or user)
    cart_items = []
    if cart_token:
        rows = db.query(CartItem, Product).join(
            Product, CartItem.product_id == Product.id
        ).filter(CartItem.cart_token == cart_token).all()
        for ci, prod in rows:
            cart_items.append({
                "id": ci.id,
                "product_id": ci.product_id,
                "quantity": ci.quantity,
                "product": {
                    "id": prod.id,
                    "name": prod.name,
                    "price": prod.price,
                    "discount_price": prod.discount_price,
                    "images": prod.images,
                    "slug": prod.slug,
                },
            })

    # Wishlist items
    wishlist_items = []
    if user:
        wl_rows = db.query(WishlistItem, Product).join(
            Product, WishlistItem.product_id == Product.id
        ).filter(WishlistItem.token == user.id).all()
        for wi, prod in wl_rows:
            wishlist_items.append({
                "id": wi.id,
                "product_id": wi.product_id,
                "product": {
                    "id": prod.id,
                    "name": prod.name,
                    "price": prod.price,
                    "discount_price": prod.discount_price,
                    "images": prod.images,
                    "slug": prod.slug,
                },
            })
    elif cart_token:
        wl_rows = db.query(WishlistItem, Product).join(
            Product, WishlistItem.product_id == Product.id
        ).filter(WishlistItem.token == cart_token).all()
        for wi, prod in wl_rows:
            wishlist_items.append({
                "id": wi.id,
                "product_id": wi.product_id,
                "product": {
                    "id": prod.id,
                    "name": prod.name,
                    "price": prod.price,
                    "discount_price": prod.discount_price,
                    "images": prod.images,
                    "slug": prod.slug,
                },
            })

    # Recent orders (last 10)
    recent_orders = []
    if user:
        orders = db.query(Order).filter(
            Order.customer_id == user.id
        ).order_by(desc(Order.created_at)).limit(10).all()
        for o in orders:
            items = db.query(OrderItem, Product).join(
                Product, OrderItem.product_id == Product.id
            ).filter(OrderItem.order_id == o.id).all()
            recent_orders.append({
                "id": o.id,
                "order_number": o.order_number,
                "status": o.status.value if hasattr(o.status, "value") else o.status,
                "total_amount": o.total_amount,
                "created_at": o.created_at.isoformat() if o.created_at else None,
                "items": [
                    {
                        "product_name": prod.name,
                        "quantity": oi.quantity,
                        "price": oi.price,
                        "images": prod.images,
                    }
                    for oi, prod in items
                ],
            })

    return JSONResponse({
        "cart": cart_items,
        "wishlist": wishlist_items,
        "recent_orders": recent_orders,
        "synced_at": str(__import__("datetime").datetime.utcnow().isoformat()),
    })
