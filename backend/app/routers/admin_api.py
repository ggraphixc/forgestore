from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form, Response, BackgroundTasks
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List
from app.core.image_compressor import compress_image
import os
import uuid
import json
import asyncio
from datetime import datetime
from app.utils import utcnow

from app.database import get_db
from app.models import Product, Category, Retailer, Order, OrderItem, OrderStatus, User, WishlistItem, Review
from app.schemas import (
    ProductCreate, ProductUpdate, ProductResponse,
    CategoryCreate, CategoryUpdate, CategoryResponse,
    RetailerCreate, RetailerUpdate, RetailerResponse,
    AdCampaignCreate, AdCampaignUpdate, AdCampaignResponse,
)
from app.auth import get_current_admin, require_role, hash_password, has_permission, AdminRole, log_admin_action, require_admin_role, create_access_token, set_auth_cookie
from app.config import get_settings
from app.models import AdminUser, NewsletterSubscriber, BroadcastCampaign, BroadcastEvent, BroadcastTemplate, AdCampaign, PromoAd, OrderEarning
from app.services.email_service import send_newsletter_broadcast
from app.config import get_settings
import csv
import io
import secrets
from concurrent.futures import ThreadPoolExecutor
import threading

BROADCAST_EXECUTOR = ThreadPoolExecutor(max_workers=4)

router = APIRouter(prefix="/api/admin", tags=["admin-api"])
settings = get_settings()

# --- Background scheduler for scheduled broadcasts ---
_scheduler_lock = threading.Lock()
_scheduler_started = False


def _start_broadcast_scheduler():
    """Start a background thread that checks for scheduled broadcasts every 30 seconds."""
    global _scheduler_started
    with _scheduler_lock:
        if _scheduler_started:
            return
        _scheduler_started = True

    def _check_loop():
        import time
        while True:
            try:
                from app.database import SessionLocal
                from app.models import NewsletterSubscriber as NS
                db = SessionLocal()
                try:
                    now = utcnow()
                    pending = db.query(BroadcastCampaign).filter(
                        BroadcastCampaign.status == "scheduled",
                        BroadcastCampaign.scheduled_at != None,
                        BroadcastCampaign.scheduled_at <= now,
                    ).all()

                    for campaign in pending:
                        campaign.status = "sending"
                        db.commit()

                        # Get subscribers
                        query = db.query(NS).filter(NS.confirmed == True)
                        if campaign.tag_filter:
                            subscribers = query.all()
                            subscribers = [s for s in subscribers if s.tags and campaign.tag_filter in s.tags]
                        else:
                            subscribers = query.all()

                        campaign.total_recipients = len(subscribers)
                        db.commit()

                        # Generate unsubscribe tokens
                        for sub in subscribers:
                            if not sub.unsubscribe_token:
                                sub.unsubscribe_token = secrets.token_urlsafe(24)
                        db.commit()

                        # Send in background
                        def _send_campaign(camp_id, subs):
                            from app.database import SessionLocal as BGDb
                            bg_db = BGDb()
                            try:
                                bg_campaign = bg_db.query(BroadcastCampaign).filter(BroadcastCampaign.id == camp_id).first()
                                if not bg_campaign:
                                    return
                                base_url = settings.site_base_url.rstrip("/")
                                sent = 0
                                for s in subs:
                                    unsub_url = f"{base_url}/api/newsletter/unsubscribe?email={s.email}&token={s.unsubscribe_token}"
                                    send_newsletter_broadcast(
                                        to_email=s.email,
                                        subject=bg_campaign.subject,
                                        html_body=bg_campaign.content,
                                        unsubscribe_url=unsub_url,
                                        campaign_id=camp_id,
                                        subscriber_id=s.id,
                                    )
                                    # Record sent event
                                    ev = BroadcastEvent(
                                        campaign_id=camp_id,
                                        subscriber_id=s.id,
                                        event_type="sent",
                                        timestamp=utcnow(),
                                    )
                                    bg_db.add(ev)
                                    sent += 1
                                bg_campaign.sent_count = sent
                                bg_campaign.sent_at = utcnow()
                                bg_campaign.status = "sent"
                                bg_db.commit()
                            except Exception:
                                try:
                                    bg_campaign.status = "failed"
                                    bg_db.commit()
                                except Exception:
                                    pass
                            finally:
                                bg_db.close()

                        BROADCAST_EXECUTOR.submit(_send_campaign, campaign.id, subscribers)
                except Exception:
                    pass
                finally:
                    db.close()
            except Exception:
                pass
            time.sleep(30)

    thread = threading.Thread(target=_check_loop, daemon=True)
    thread.start()


# Start the scheduler on import
_start_broadcast_scheduler()
settings = get_settings()


# --- Admin Users Management API ---
@router.get("/admin-users")
def list_admin_users(
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_role("admin_users")),
):
    admin_users = db.query(AdminUser).order_by(AdminUser.created_at).all()
    return {
        "admin_users": [
            {
                "id": u.id,
                "email": u.email,
                "name": u.name,
                "role": u.role.value if hasattr(u.role, 'value') else u.role,
                "vendor_id": u.vendor_id,
                "created_at": u.created_at.isoformat() if u.created_at else None,
            }
            for u in admin_users
        ]
    }


@router.post("/admin-users")
def create_admin_user(
    data: dict,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_role("admin_users")),
):
    existing = db.query(AdminUser).filter(AdminUser.email == data.get("email")).first()
    if existing:
        raise HTTPException(status_code=400, detail="Admin with this email already exists")

    new_admin = AdminUser(
        email=data.get("email"),
        password=hash_password(data.get("password", "changeme123")),
        name=data.get("name"),
        role=data.get("role", "LOGISTICS"),
        vendor_id=data.get("vendor_id"),
    )
    db.add(new_admin)
    db.commit()
    db.refresh(new_admin)
    log_admin_action(db, admin, "create", "admin_user", new_admin.id, f"Created admin user {data.get('email')}")
    return {"success": True, "id": new_admin.id}


@router.put("/admin-users/{admin_id}")
def update_admin_user(
    admin_id: str,
    data: dict,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_role("admin_users")),
):
    target = db.query(AdminUser).filter(AdminUser.id == admin_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Admin user not found")

    if "name" in data:
        target.name = data["name"]
    if "role" in data:
        target.role = data["role"]
    if "vendor_id" in data:
        target.vendor_id = data["vendor_id"]
    if "password" in data and data["password"]:
        target.password = hash_password(data["password"])

    db.commit()
    log_admin_action(db, admin, "update", "admin_user", admin_id, f"Updated admin user {target.email}")
    return {"success": True}


@router.delete("/admin-users/{admin_id}")
def delete_admin_user(
    admin_id: str,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_role("admin_users")),
):
    if admin.id == admin_id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    target = db.query(AdminUser).filter(AdminUser.id == admin_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Admin user not found")
    db.delete(target)
    db.commit()
    log_admin_action(db, admin, "delete", "admin_user", admin_id, f"Deleted admin user {target.email}")
    return {"success": True}


# --- Product CRUD API ---
@router.post("/products")
def create_product(
    data: ProductCreate,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_role("catalog")),
):
    product = Product(**data.model_dump())
    db.add(product)
    db.commit()
    db.refresh(product)
    log_admin_action(db, admin, "create", "product", product.id, f"Created product '{data.name}'")
    return {"success": True, "id": product.id}


@router.put("/products/{product_id}")
def update_product(
    product_id: str,
    data: ProductUpdate,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_role("catalog")),
):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # RETAILER can only update their own products
    if admin.role == AdminRole.RETAILER and admin.vendor_id:
        if product.retailer_id != admin.vendor_id:
            raise HTTPException(status_code=403, detail="You can only edit your own products")

    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(product, key, value)
    product.updated_at = utcnow()

    db.commit()
    log_admin_action(db, admin, "update", "product", product_id, f"Updated product '{product.name}'")
    return {"success": True}


@router.delete("/products/{product_id}")
def delete_product(
    product_id: str,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_role("catalog")),
):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    # RETAILER can only delete their own products
    if admin.role == AdminRole.RETAILER and admin.vendor_id:
        if product.retailer_id != admin.vendor_id:
            raise HTTPException(status_code=403, detail="You can only delete your own products")
    
    db.delete(product)
    db.commit()
    log_admin_action(db, admin, "delete", "product", product_id, f"Deleted product '{product.name}'")
    return {"success": True}


# --- Category CRUD API ---
@router.post("/categories")
def create_category(
    data: CategoryCreate,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_role("categories")),
):
    category = Category(**data.model_dump())
    db.add(category)
    db.commit()
    db.refresh(category)
    log_admin_action(db, admin, "create", "category", category.id, f"Created category '{data.name}'")
    return {"success": True, "id": category.id}


@router.put("/categories/{category_id}")
def update_category(
    category_id: str,
    data: CategoryUpdate,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_role("categories")),
):
    category = db.query(Category).filter(Category.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(category, key, value)
    category.updated_at = utcnow()
    db.commit()
    log_admin_action(db, admin, "update", "category", category_id, f"Updated category '{category.name}'")
    return {"success": True}


@router.delete("/categories/{category_id}")
def delete_category(
    category_id: str,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_role("categories")),
):
    category = db.query(Category).filter(Category.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    # Unlink products
    db.query(Product).filter(Product.category_id == category_id).update({"category_id": None})
    db.delete(category)
    db.commit()
    log_admin_action(db, admin, "delete", "category", category_id, f"Deleted category '{category.name}'")
    return {"success": True}


# --- Retailer CRUD API ---
@router.post("/retailers")
def create_retailer(
    data: RetailerCreate,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_role("retailers")),
):
    retailer = Retailer(**data.model_dump())
    db.add(retailer)
    db.commit()
    db.refresh(retailer)
    log_admin_action(db, admin, "create", "retailer", retailer.id, f"Created retailer '{data.name}'")
    return {"success": True, "id": retailer.id}


@router.put("/retailers/{retailer_id}")
def update_retailer(
    retailer_id: str,
    data: RetailerUpdate,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_role("retailers")),
):
    retailer = db.query(Retailer).filter(Retailer.id == retailer_id).first()
    if not retailer:
        raise HTTPException(status_code=404, detail="Retailer not found")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(retailer, key, value)
    retailer.updated_at = utcnow()
    db.commit()
    log_admin_action(db, admin, "update", "retailer", retailer_id, f"Updated retailer '{retailer.name}'")
    return {"success": True}


@router.delete("/retailers/{retailer_id}")
def delete_retailer(
    retailer_id: str,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_role("retailers")),
):
    retailer = db.query(Retailer).filter(Retailer.id == retailer_id).first()
    if not retailer:
        raise HTTPException(status_code=404, detail="Retailer not found")
    # Unlink products
    db.query(Product).filter(Product.retailer_id == retailer_id).update({"retailer_id": None})
    db.delete(retailer)
    db.commit()
    log_admin_action(db, admin, "delete", "retailer", retailer_id, f"Deleted retailer '{retailer.name}'")
    return {"success": True}


# --- Order Management ---
@router.get("/orders")
def list_orders(
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_role("orders")),
):
    orders = db.query(Order).order_by(Order.created_at.desc()).all()
    result = []
    for o in orders:
        customer = db.query(User).filter(User.id == o.customer_id).first()
        result.append({
            "id": o.id,
            "order_number": o.order_number,
            "status": o.status.value if hasattr(o.status, 'value') else o.status,
            "total_amount": o.total_amount,
            "customer_name": customer.name if customer else "Unknown",
            "created_at": o.created_at.isoformat() if o.created_at else None,
        })
    return {"orders": result}


@router.put("/orders/{order_id}/status")
def update_order_status(
    order_id: str,
    data: dict,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_role("orders")),
):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    status = data.get("status", "")
    if not status:
        raise HTTPException(status_code=400, detail="status is required")
    
    try:
        order.status = OrderStatus(status)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid status: {status}")
    
    order.updated_at = utcnow()
    db.commit()

    # Auto-dispatch shipment when order transitions to PROCESSING
    if status == "PROCESSING":
        try:
            from app.services.wallet_service import auto_dispatch_shipment
            auto_dispatch_shipment(db, order_id)
        except Exception:
            pass  # Dispatch failure should not block order update

    # Send email on status change (non-blocking via dispatch_email_background)
    from app.core.email import dispatch_email_background
    from app.services.email_service import _render_email_template, _base_context
    customer = db.query(User).filter(User.id == order.customer_id).first()
    if customer and customer.email:
        status_emoji = {"PAID": "✅", "PROCESSING": "🔧", "SHIPPED": "📦", "DELIVERED": "🎉", "CANCELLED": "❌"}
        emoji = status_emoji.get(status, "📋")
        html = _render_email_template("order_status.html", _base_context(
            heading=f"{emoji} Order {status.title()}!",
            subtitle=f"Order {order.order_number}",
            body_html=f"""<p style="font-size:14px;color:#57534e;text-align:center;margin:0 0 20px;">Hi <strong>{customer.name or 'Customer'}</strong>,</p>
            <p style="font-size:14px;color:#57534e;line-height:1.6;text-align:center;margin:0 0 20px;">
              Your order <strong>{order.order_number}</strong> has been updated to <strong>{status}</strong>.
            </p>""",
            cta_url=f"{settings.site_base_url.rstrip('/')}/shop/account/orders",
            cta_label="View My Orders",
            customer_name=customer.name or "Customer",
            order_number=order.order_number,
            status=status,
            tracking_number="",
        ))
        dispatch_email_background(customer.email, f"Order {status.title()} — {order.order_number}", html)

    log_admin_action(db, admin, "update", "order", order_id, f"Updated order {order.order_number} to {status}")
    return {"success": True}


@router.delete("/orders/{order_id}")
def delete_order(
    order_id: str,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_role("orders")),
):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    # Delete order items first
    db.query(OrderItem).filter(OrderItem.order_id == order_id).delete()
    
    order_number = order.order_number
    db.delete(order)
    db.commit()
    
    log_admin_action(db, admin, "delete", "order", order_id, f"Deleted order {order_number}")
    return {"success": True}


# --- Settings API ---

SETTINGS_CATEGORY_PERMISSIONS = {
    "global": "settings",
    "design": "settings",
    "technical": "settings",
    "optional": "settings",
    "developer": "settings",
    "logistics": "settings",
    "other": "settings",
}


def _get_setting_def(key: str):
    from app.services.ai_service import SETTINGS_DEFINITIONS
    for sd in SETTINGS_DEFINITIONS:
        if sd["key"] == key:
            return sd
    return None


@router.get("/settings")
def get_settings(
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_role("settings")),
):
    """Get all settings, categorized for the admin UI."""
    from app.config import get_categorized_settings
    categorized = get_categorized_settings(db)
    return {"categories": categorized}


@router.put("/settings/{key}")
def update_setting(
    key: str,
    value: str,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_role("settings")),
):
    from app.models import Settings as SettingsModel
    from app.services.ai_service import SETTINGS_DEFINITIONS

    # Find the setting definition
    sd = _get_setting_def(key)
    if not sd:
        raise HTTPException(status_code=400, detail=f"Unknown setting key: {key}")

    # Check category permission
    cat_perm = SETTINGS_CATEGORY_PERMISSIONS.get(sd["category"], "settings")
    if not has_permission(admin, cat_perm):
        raise HTTPException(status_code=403, detail=f"You don't have permission to modify {sd['category']} settings")

    setting = db.query(SettingsModel).filter(SettingsModel.key == key).first()
    if setting:
        setting.value = value
    else:
        setting = SettingsModel(
            key=key, value=value,
            category=sd["category"],
            setting_type=sd["type"],
            label=sd["label"],
            description=sd.get("description", ""),
        )
        db.add(setting)
    db.commit()

    log_admin_action(db, admin, "update", "setting", key, f"Updated setting '{key}'")
    from app.config import invalidate_settings_cache
    invalidate_settings_cache()
    return {"success": True}


@router.post("/settings/bulk")
def bulk_update_settings(
    data: dict,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_role("settings")),
):
    """Bulk update multiple settings at once. Keys are the setting keys."""
    from app.models import Settings as SettingsModel
    from app.services.ai_service import SETTINGS_DEFINITIONS

    updated = 0
    for key, value in data.items():
        # Validate setting exists
        sd = _get_setting_def(key)
        if not sd:
            continue
        cat_perm = SETTINGS_CATEGORY_PERMISSIONS.get(sd["category"], "settings")
        if not has_permission(admin, cat_perm):
            continue

        setting = db.query(SettingsModel).filter(SettingsModel.key == key).first()
        if setting:
            setting.value = str(value)
        else:
            setting = SettingsModel(
                key=key, value=str(value),
                category=sd["category"],
                setting_type=sd["type"],
                label=sd["label"],
                description=sd.get("description", ""),
            )
            db.add(setting)
        updated += 1
    db.commit()

    log_admin_action(db, admin, "update", "settings_bulk", "", f"Bulk updated {updated} settings")
    from app.config import invalidate_settings_cache
    invalidate_settings_cache()
    return {"success": True, "updated": updated}


# --- AI Integration API ---

@router.post("/ai/generate-description")
def ai_generate_description(
    data: dict,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_role("catalog")),
):
    """Generate a product description using AI."""
    from app.services.ai_service import generate_product_description

    description = generate_product_description(
        product_name=data.get("name", ""),
        category=data.get("category", ""),
        brand=data.get("brand", ""),
        keywords=data.get("keywords", ""),
        tone=data.get("tone", "professional"),
    )

    if description:
        log_admin_action(db, admin, "ai_generate", "description", "", f"Generated description for '{data.get('name')}'")
        return {"success": True, "description": description}
    else:
        return {"success": False, "description": None, "message": "AI is not configured. Set your API key in Developer Settings."}


@router.post("/ai/generate-tags")
def ai_generate_tags(
    data: dict,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_role("catalog")),
):
    """Generate SEO tags for a product using AI."""
    from app.services.ai_service import generate_product_tags

    tags = generate_product_tags(
        product_name=data.get("name", ""),
        description=data.get("description", ""),
    )

    if tags:
        log_admin_action(db, admin, "ai_generate", "tags", "", f"Generated tags for '{data.get('name')}'")
        return {"success": True, "tags": tags}
    else:
        return {"success": False, "tags": None, "message": "AI is not configured. Set your API key in Developer Settings."}


# --- Notifications API ---

@router.get("/notifications")
def get_notifications(
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    """Get recent notifications with pagination."""
    from app.models import AdminNotification
    total = db.query(func.count(AdminNotification.id)).scalar() or 0
    notifications = db.query(AdminNotification).order_by(
        AdminNotification.created_at.desc()
    ).offset(offset).limit(limit).all()
    return {
        "notifications": [
            {
                "id": n.id,
                "type": n.type,
                "title": n.title,
                "message": n.message,
                "link": n.link,
                "read": n.read,
                "created_at": n.created_at.isoformat() if n.created_at else None,
            }
            for n in notifications
        ],
        "total": total,
        "has_more": (offset + limit) < total,
    }


@router.put("/notifications/{notif_id}/read")
def mark_notification_read(
    notif_id: str,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    """Mark a single notification as read."""
    from app.models import AdminNotification
    notif = db.query(AdminNotification).filter(AdminNotification.id == notif_id).first()
    if notif:
        notif.read = True
        db.commit()
    return {"success": True}


@router.get("/notifications/unread-count")
def get_unread_notification_count(
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    """Get the count of unread notifications."""
    from app.models import AdminNotification
    count = db.query(func.count(AdminNotification.id)).filter(
        AdminNotification.read == False
    ).scalar() or 0
    return {"count": count}


@router.put("/notifications/read-all")
def mark_all_notifications_read(
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    """Mark ALL notifications as read in bulk."""
    from app.models import AdminNotification
    updated = db.query(AdminNotification).filter(
        AdminNotification.read == False
    ).update({"read": True})
    db.commit()
    return {"success": True, "marked": updated}


@router.get("/notifications/stream")
async def stream_notifications(
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
):
    """Server-Sent Events endpoint for real-time notifications.
    
    The client connects and receives new notifications as they happen,
    plus a keepalive ping every 30s to prevent connection drops.
    """
    from app.services.notification_bus import poll

    last_id = 0

    async def event_generator():
        nonlocal last_id

        # Send initial connection confirmation
        yield f"event: connected\ndata: {{\"status\":\"ok\"}}\n\n"

        while True:
            if await request.is_disconnected():
                break

            try:
                events = poll(since_id=last_id)
                for ev in events:
                    yield f"data: {json.dumps(ev)}\n\n"
                    last_id = int(ev["id"])

                # If no events, send keepalive every 30s
                if not events:
                    yield ": keepalive\n\n"

                await asyncio.sleep(3)
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# --- Audit Log API ---

@router.get("/audit-logs")
def get_audit_logs(
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_role("admin_users")),
):
    """Get recent audit log entries with pagination."""
    from app.models import AdminAuditLog
    total = db.query(func.count(AdminAuditLog.id)).scalar() or 0
    logs = db.query(AdminAuditLog).order_by(
        AdminAuditLog.created_at.desc()
    ).offset(offset).limit(limit).all()
    return {
        "logs": [
            {
                "id": log.id,
                "admin_email": log.admin_email,
                "action": log.action,
                "resource_type": log.resource_type,
                "resource_id": log.resource_id,
                "details": log.details,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            for log in logs
        ],
        "total": total,
        "has_more": (offset + limit) < total,
    }


# --- Newsletter Subscribers ---
@router.get("/newsletter-subscribers")
def list_newsletter_subscribers(
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_role("settings")),
):
    subscribers = db.query(NewsletterSubscriber).order_by(
        NewsletterSubscriber.created_at.desc()
    ).all()
    return {
        "subscribers": [
            {
                "id": s.id,
                "email": s.email,
                "confirmed": s.confirmed,
                "tags": s.tags or [],
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in subscribers
        ]
    }


@router.delete("/newsletter-subscribers/{subscriber_id}")
def delete_newsletter_subscriber(
    subscriber_id: str,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_role("settings")),
):
    subscriber = db.query(NewsletterSubscriber).filter(
        NewsletterSubscriber.id == subscriber_id
    ).first()
    if not subscriber:
        raise HTTPException(status_code=404, detail="Subscriber not found")
    email = subscriber.email
    db.delete(subscriber)
    db.commit()
    log_admin_action(db, admin, "delete", "newsletter_subscriber", subscriber_id, f"Unsubscribed {email}")
    return {"success": True}


@router.put("/newsletter-subscribers/{subscriber_id}/tags")
def update_subscriber_tags(
    subscriber_id: str,
    data: dict,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_role("settings")),
):
    """Update the tags for a newsletter subscriber."""
    subscriber = db.query(NewsletterSubscriber).filter(
        NewsletterSubscriber.id == subscriber_id
    ).first()
    if not subscriber:
        raise HTTPException(status_code=404, detail="Subscriber not found")
    subscriber.tags = data.get("tags", [])
    db.commit()
    return {"success": True, "tags": subscriber.tags}


@router.post("/newsletter-subscribers/broadcast")
def broadcast_newsletter(
    data: dict,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_role("settings")),
):
    """
    Send a broadcast email to all confirmed subscribers (immediately or scheduled).
    Creates a BroadcastCampaign record for analytics tracking.
    Runs the actual sends in a background thread pool.
    """
    subject = (data.get("subject") or "").strip()
    content = (data.get("content") or "").strip()
    tag_filter = data.get("tag_filter", None)
    scheduled_at_str = data.get("scheduled_at", None)  # ISO format string or null for immediate
    template_id = data.get("template_id", None)

    if not subject or not content:
        raise HTTPException(status_code=400, detail="Subject and content are required")

    query = db.query(NewsletterSubscriber).filter(
        NewsletterSubscriber.confirmed == True
    )
    subscribers = query.all()
    if tag_filter:
        subscribers = [s for s in subscribers if s.tags and tag_filter in s.tags]
    if not subscribers:
        raise HTTPException(status_code=400, detail="No confirmed subscribers to send to")

    # Parse scheduled_at if provided
    scheduled_at = None
    if scheduled_at_str:
        try:
            scheduled_at = datetime.fromisoformat(scheduled_at_str)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Invalid scheduled_at format. Use ISO format (e.g. 2025-06-01T14:00:00)")

    is_scheduled = scheduled_at is not None and scheduled_at > utcnow()

    # Generate unsubscribe tokens for any subscriber that doesn't have one
    for sub in subscribers:
        if not sub.unsubscribe_token:
            sub.unsubscribe_token = secrets.token_urlsafe(24)
    db.commit()

    # Create campaign record
    campaign = BroadcastCampaign(
        subject=subject,
        content=content,
        tag_filter=tag_filter or None,
        status="scheduled" if is_scheduled else "sending",
        scheduled_at=scheduled_at,
        total_recipients=len(subscribers),
        template_id=template_id or None,
        created_by=admin.id,
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)

    if not is_scheduled:
        # Send immediately
        campaign.status = "sending"
        db.commit()

        def _send_all(camp_id, subs):
            from app.database import SessionLocal as BGDb
            bg_db = BGDb()
            try:
                bg_campaign = bg_db.query(BroadcastCampaign).filter(BroadcastCampaign.id == camp_id).first()
                if not bg_campaign:
                    return
                base_url = settings.site_base_url.rstrip("/")
                sent = 0
                for s in subs:
                    unsub_url = f"{base_url}/api/newsletter/unsubscribe?email={s.email}&token={s.unsubscribe_token}"
                    send_newsletter_broadcast(
                        to_email=s.email,
                        subject=subject,
                        html_body=content,
                        unsubscribe_url=unsub_url,
                        campaign_id=camp_id,
                        subscriber_id=s.id,
                    )
                    ev = BroadcastEvent(
                        campaign_id=camp_id,
                        subscriber_id=s.id,
                        event_type="sent",
                        timestamp=utcnow(),
                    )
                    bg_db.add(ev)
                    sent += 1
                bg_campaign.sent_count = sent
                bg_campaign.sent_at = utcnow()
                bg_campaign.status = "sent"
                bg_db.commit()
            except Exception:
                try:
                    bg_campaign.status = "failed"
                    bg_db.commit()
                except Exception:
                    pass
            finally:
                bg_db.close()

        BROADCAST_EXECUTOR.submit(_send_all, campaign.id, subscribers)

        log_admin_action(
            db, admin, "broadcast", "newsletter", campaign.id,
            f"Broadcast '{subject}' to {len(subscribers)} subscribers"
        )

        return {
            "success": True,
            "campaign_id": campaign.id,
            "sent_to": len(subscribers),
            "message": f"Broadcast queued to {len(subscribers)} subscriber(s)"
        }
    else:
        log_admin_action(
            db, admin, "schedule", "newsletter", campaign.id,
            f"Scheduled broadcast '{subject}' for {scheduled_at_str}"
        )
        return {
            "success": True,
            "campaign_id": campaign.id,
            "scheduled_at": scheduled_at_str,
            "message": f"Broadcast scheduled for {scheduled_at_str}"
        }


@router.post("/newsletter-subscribers/import")
async def import_newsletter_subscribers(
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_role("settings")),
):
    """
    Import subscribers from a CSV file.
    Expected CSV columns: Email (required), Tags (optional), Confirmed (optional).
    Detects duplicates by email and returns a detailed summary.
    """
    import re

    form = await request.form()
    file = form.get("file")
    if not file or not hasattr(file, "filename") or not file.filename:
        raise HTTPException(status_code=400, detail="CSV file is required")

    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only .csv files are accepted")

    content = await file.read()
    try:
        decoded = content.decode("utf-8-sig")  # Handle BOM
    except UnicodeDecodeError:
        try:
            decoded = content.decode("latin-1")
        except UnicodeDecodeError:
            raise HTTPException(status_code=400, detail="Could not decode CSV file. Use UTF-8 or Latin-1 encoding.")

    reader = csv.DictReader(io.StringIO(decoded))
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV file is empty or has no headers")

    # Normalize column names (case-insensitive)
    normalized_fields = {f.strip().lower(): f.strip() for f in reader.fieldnames}

    # Find the email column (accept "email", "e-mail", "mail")
    email_key = None
    for candidate in ["email", "e-mail", "mail", "correo", "email_address"]:
        if candidate in normalized_fields:
            email_key = normalized_fields[candidate]
            break
    if not email_key:
        raise HTTPException(
            status_code=400,
            detail=f"Could not find an 'Email' column in CSV. Found columns: {', '.join(reader.fieldnames)}"
        )

    # Find tags and confirmed columns
    tags_key = normalized_fields.get("tags")
    confirmed_key = normalized_fields.get("confirmed")

    email_regex = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

    # Fetch all existing emails in one query for fast duplicate detection
    existing_emails = set(
        row[0].lower()
        for row in db.query(NewsletterSubscriber.email).all()
    )

    results = {
        "total": 0,
        "imported": 0,
        "duplicates": 0,
        "errors": 0,
        "error_details": [],
        "duplicate_emails": [],
        "imported_emails": [],
    }

    subscribers_to_add = []

    # Store all row results for error CSV generation
    rows_with_status = []  # Each entry: { "email": str, "tags": str, "confirmed": str, "status": str, "error": str or None }

    for row_idx, row in enumerate(reader, start=2):  # start=2 because row 1 is header
        results["total"] += 1

        raw_email = (row.get(email_key) or "").strip()
        email = raw_email.lower()

        raw_tags = ""
        if tags_key and (row.get(tags_key) or "").strip():
            raw_tags = row[tags_key].strip()

        raw_confirmed = ""
        if confirmed_key and (row.get(confirmed_key) or "").strip():
            raw_confirmed = row[confirmed_key].strip()

        if not email:
            results["errors"] += 1
            results["error_details"].append(f"Row {row_idx}: Missing email")
            rows_with_status.append({"email": raw_email, "tags": raw_tags, "confirmed": raw_confirmed, "status": "error", "error": "Missing email"})
            continue

        if not email_regex.match(email):
            results["errors"] += 1
            results["error_details"].append(f"Row {row_idx}: Invalid email '{email}'")
            rows_with_status.append({"email": raw_email, "tags": raw_tags, "confirmed": raw_confirmed, "status": "error", "error": "Invalid email format"})
            continue

        if email in existing_emails:
            results["duplicates"] += 1
            results["duplicate_emails"].append(email)
            rows_with_status.append({"email": raw_email, "tags": raw_tags, "confirmed": raw_confirmed, "status": "duplicate", "error": "Already exists in database"})
            continue

        # Parse tags
        tags = []
        if raw_tags:
            tags = [t.strip() for t in re.split(r"[;|,]", raw_tags) if t.strip()]

        # Parse confirmed status
        confirmed = False
        if raw_confirmed.lower() in ("yes", "true", "1", "y", "confirmed"):
            confirmed = True

        subscriber = NewsletterSubscriber(
            email=email,
            confirmed=confirmed,
            tags=tags or None,
        )
        if confirmed:
            subscriber.confirm_token = secrets.token_urlsafe(24)
            subscriber.unsubscribe_token = secrets.token_urlsafe(24)

        subscribers_to_add.append(subscriber)
        existing_emails.add(email)  # Prevent duplicate in same import
        results["imported"] += 1
        results["imported_emails"].append(email)
        rows_with_status.append({"email": raw_email, "tags": raw_tags, "confirmed": raw_confirmed, "status": "imported", "error": None})

    if results["total"] == 0:
        raise HTTPException(status_code=400, detail="CSV file has no data rows")

    if subscribers_to_add:
        for sub in subscribers_to_add:
            db.add(sub)
        db.commit()

    # Build downloadable error CSV
    error_rows = [r for r in rows_with_status if r["status"] in ("error", "duplicate")]
    if error_rows:
        error_output = io.StringIO()
        error_writer = csv.writer(error_output)
        # Write header
        header = ["Email", "Tags", "Confirmed", "Status", "Error"]
        error_writer.writerow(header)
        for r in error_rows:
            error_writer.writerow([r["email"], r["tags"], r["confirmed"], r["status"], r["error"] or ""])
        results["downloadable_error_csv"] = error_output.getvalue()
        error_output.close()
    else:
        results["downloadable_error_csv"] = None

    log_admin_action(
        db, admin, "import", "newsletter_subscriber", "",
        f"Imported {results['imported']} subscribers from CSV ({results['duplicates']} duplicates, {results['errors']} errors)"
    )

    return results


@router.get("/newsletter-subscribers/import/sample-csv")
def download_sample_csv(
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_role("settings")),
):
    """Download a sample CSV template for newsletter subscriber import."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Email", "Name", "Tags", "Confirmed"])
    writer.writerow(["jane@example.com", "Jane Doe", "vip, new", "Yes"])
    writer.writerow(["john@example.com", "John Smith", "wholesale", "No"])
    writer.writerow(["alice@example.com", "Alice Johnson", "partner", "Yes"])
    writer.writerow(["bob@example.com", "Bob Brown", "", "No"])
    writer.writerow(["carol@example.com", "Carol White", "vip, repeat", "Yes"])

    csv_content = output.getvalue()
    output.close()

    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": "attachment; filename=newsletter-import-sample.csv",
        },
    )


@router.get("/newsletter-subscribers/import/error-csv/{import_id}")
def download_import_error_csv(
    import_id: str,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_role("settings")),
):
    """Download a CSV with error details from a previous import (stored in admin audit log metadata)."""
    from app.models import AdminAuditLog

    log_entry = db.query(AdminAuditLog).filter(
        AdminAuditLog.id == import_id,
        AdminAuditLog.action == "import",
    ).first()
    if not log_entry or not log_entry.details:
        raise HTTPException(status_code=404, detail="Import log not found or has no error details")

    # The error CSV was embedded in the response and can be regenerated from the details
    # For now, return the details as a CSV-friendly format
    details = log_entry.details

    output = io.StringIO()
    output.write("Error Details\n")
    output.write(f"\"{details}\"\n")
    csv_content = output.getvalue()
    output.close()

    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename=import-errors-{import_id[:8]}.csv",
        },
    )


@router.get("/newsletter-subscribers/export")
def export_newsletter_subscribers(
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_role("settings")),
):
    subscribers = db.query(NewsletterSubscriber).order_by(
        NewsletterSubscriber.created_at.desc()
    ).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Email", "Confirmed", "Tags", "Subscribed Date"])
    for s in subscribers:
        writer.writerow([
            s.email,
            "Yes" if s.confirmed else "No",
            ", ".join(s.tags) if s.tags else "",
            s.created_at.strftime("%Y-%m-%d %H:%M:%S") if s.created_at else "",
        ])

    csv_content = output.getvalue()
    output.close()

    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=newsletter-subscribers-{utcnow().strftime('%Y-%m-%d')}.csv",
        },
    )


# --- Broadcast Campaign Analytics ---
@router.get("/newsletter-campaigns")
def list_broadcast_campaigns(
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_role("settings")),
):
    """List all broadcast campaigns with analytics."""
    campaigns = db.query(BroadcastCampaign).order_by(
        BroadcastCampaign.created_at.desc()
    ).all()
    return {
        "campaigns": [
            {
                "id": c.id,
                "subject": c.subject,
                "tag_filter": c.tag_filter,
                "status": c.status,
                "scheduled_at": c.scheduled_at.isoformat() if c.scheduled_at else None,
                "sent_at": c.sent_at.isoformat() if c.sent_at else None,
                "total_recipients": c.total_recipients,
                "sent_count": c.sent_count,
                "opened_count": c.opened_count,
                "clicked_count": c.clicked_count,
                "unsubscribed_count": c.unsubscribed_count,
                "template_id": c.template_id,
                "created_at": c.created_at.isoformat() if c.created_at else None,
                # Derived metrics
                "open_rate": round(c.opened_count / c.sent_count * 100, 1) if c.sent_count > 0 else 0,
                "click_rate": round(c.clicked_count / c.sent_count * 100, 1) if c.sent_count > 0 else 0,
            }
            for c in campaigns
        ]
    }


@router.get("/newsletter-campaigns/{campaign_id}")
def get_broadcast_campaign_detail(
    campaign_id: str,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_role("settings")),
):
    """Get detailed analytics for a specific campaign."""
    campaign = db.query(BroadcastCampaign).filter(BroadcastCampaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    # Get recent events with subscriber info
    events = db.query(BroadcastEvent).filter(
        BroadcastEvent.campaign_id == campaign_id
    ).order_by(BroadcastEvent.timestamp.desc()).limit(100).all()

    subscriber_ids = list(set(e.subscriber_id for e in events))
    subscribers = {
        s.id: s.email
        for s in db.query(NewsletterSubscriber).filter(NewsletterSubscriber.id.in_(subscriber_ids)).all()
    } if subscriber_ids else {}

    # Aggregate events
    event_counts = {}
    for e in events:
        event_counts[e.event_type] = event_counts.get(e.event_type, 0) + 1

    return {
        "campaign": {
            "id": campaign.id,
            "subject": campaign.subject,
            "tag_filter": campaign.tag_filter,
            "status": campaign.status,
            "scheduled_at": campaign.scheduled_at.isoformat() if campaign.scheduled_at else None,
            "sent_at": campaign.sent_at.isoformat() if campaign.sent_at else None,
            "total_recipients": campaign.total_recipients,
            "sent_count": campaign.sent_count,
            "opened_count": campaign.opened_count,
            "clicked_count": campaign.clicked_count,
            "unsubscribed_count": campaign.unsubscribed_count,
            "open_rate": round(campaign.opened_count / campaign.sent_count * 100, 1) if campaign.sent_count > 0 else 0,
            "click_rate": round(campaign.clicked_count / campaign.sent_count * 100, 1) if campaign.sent_count > 0 else 0,
            "created_at": campaign.created_at.isoformat() if campaign.created_at else None,
        },
        "event_counts": event_counts,
        "recent_events": [
            {
                "id": e.id,
                "event_type": e.event_type,
                "email": subscribers.get(e.subscriber_id, "Unknown"),
                "metadata": e.extra_data,
                "timestamp": e.timestamp.isoformat() if e.timestamp else None,
            }
            for e in events[:50]
        ],
    }


@router.delete("/newsletter-campaigns/{campaign_id}")
def cancel_scheduled_broadcast(
    campaign_id: str,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_role("settings")),
):
    """Cancel a scheduled broadcast."""
    campaign = db.query(BroadcastCampaign).filter(BroadcastCampaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if campaign.status != "scheduled":
        raise HTTPException(status_code=400, detail="Only scheduled campaigns can be cancelled")

    campaign.status = "failed"
    db.commit()
    log_admin_action(db, admin, "cancel", "broadcast", campaign_id, f"Cancelled scheduled broadcast '{campaign.subject}'")
    return {"success": True}


# --- Broadcast Templates ---
@router.get("/newsletter-templates")
def list_broadcast_templates(
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_role("settings")),
):
    """List all broadcast email templates."""
    templates = db.query(BroadcastTemplate).order_by(BroadcastTemplate.updated_at.desc()).all()
    return {
        "templates": [
            {
                "id": t.id,
                "name": t.name,
                "subject": t.subject,
                "content": t.content,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "updated_at": t.updated_at.isoformat() if t.updated_at else None,
                "campaign_count": db.query(func.count(BroadcastCampaign.id)).filter(
                    BroadcastCampaign.template_id == t.id
                ).scalar() or 0,
            }
            for t in templates
        ]
    }


@router.post("/newsletter-templates")
def create_broadcast_template(
    data: dict,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_role("settings")),
):
    """Create a new broadcast template."""
    name = (data.get("name") or "").strip()
    subject = (data.get("subject") or "").strip()
    content = (data.get("content") or "").strip()

    if not name or not subject or not content:
        raise HTTPException(status_code=400, detail="Name, subject, and content are required")

    template = BroadcastTemplate(
        name=name,
        subject=subject,
        content=content,
        created_by=admin.id,
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    log_admin_action(db, admin, "create", "broadcast_template", template.id, f"Created template '{name}'")
    return {"success": True, "id": template.id}


@router.put("/newsletter-templates/{template_id}")
def update_broadcast_template(
    template_id: str,
    data: dict,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_role("settings")),
):
    """Update a broadcast template."""
    template = db.query(BroadcastTemplate).filter(BroadcastTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    if "name" in data:
        template.name = data["name"]
    if "subject" in data:
        template.subject = data["subject"]
    if "content" in data:
        template.content = data["content"]
    template.updated_at = utcnow()
    db.commit()
    log_admin_action(db, admin, "update", "broadcast_template", template_id, f"Updated template '{template.name}'")
    return {"success": True}


@router.delete("/newsletter-templates/{template_id}")
def delete_broadcast_template(
    template_id: str,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_role("settings")),
):
    """Delete a broadcast template."""
    template = db.query(BroadcastTemplate).filter(BroadcastTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    db.delete(template)
    db.commit()
    log_admin_action(db, admin, "delete", "broadcast_template", template_id, f"Deleted template '{template.name}'")
    return {"success": True}


# --- Double Opt-in Management ---
@router.get("/newsletter/pending-confirmations")
def list_pending_confirmations(
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_role("settings")),
):
    """List subscribers awaiting confirmation (double opt-in)."""
    pending = db.query(NewsletterSubscriber).filter(
        NewsletterSubscriber.confirmed == False
    ).order_by(NewsletterSubscriber.created_at.desc()).all()

    now = utcnow()
    return {
        "pending": [
            {
                "id": s.id,
                "email": s.email,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "expired": s.confirm_expires_at is not None and s.confirm_expires_at < now,
                "expires_at": s.confirm_expires_at.isoformat() if s.confirm_expires_at else None,
            }
            for s in pending
        ]
    }


@router.post("/newsletter/resend-confirmation")
def resend_confirmation_email(
    data: dict,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_role("settings")),
):
    """Re-send the confirmation email for a pending subscriber."""
    subscriber_id = data.get("subscriber_id", "")
    if not subscriber_id:
        raise HTTPException(status_code=400, detail="subscriber_id is required")

    subscriber = db.query(NewsletterSubscriber).filter(
        NewsletterSubscriber.id == subscriber_id,
        NewsletterSubscriber.confirmed == False,
    ).first()
    if not subscriber:
        raise HTTPException(status_code=404, detail="Pending subscriber not found")

    from app.services.email_service import send_newsletter_confirmation_email

    # Generate fresh token and expiry
    token = subscriber.confirm_token or secrets.token_urlsafe(24)
    subscriber.confirm_token = token
    subscriber.confirm_expires_at = utcnow()  # will be patched below
    db.commit()

    _settings = get_settings()
    base_url = _settings.site_base_url.rstrip("/")
    confirm_url = f"{base_url}/api/newsletter/confirm?token={token}&email={subscriber.email}"
    send_newsletter_confirmation_email(subscriber.email, confirm_url)

    log_admin_action(
        db, admin, "resend_confirmation", "newsletter_subscriber", subscriber_id,
        f"Re-sent confirmation email to {subscriber.email}"
    )
    return {"success": True, "message": f"Confirmation email re-sent to {subscriber.email}"}


@router.delete("/newsletter/cleanup-expired")
def cleanup_expired_confirmations(
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_role("settings")),
):
    """Delete expired unconfirmed subscribers."""
    now = utcnow()
    expired = db.query(NewsletterSubscriber).filter(
        NewsletterSubscriber.confirmed == False,
        NewsletterSubscriber.confirm_expires_at != None,
        NewsletterSubscriber.confirm_expires_at < now,
    ).all()

    count = len(expired)
    emails = [s.email for s in expired]
    for s in expired:
        db.delete(s)
    db.commit()

    if count > 0:
        log_admin_action(
            db, admin, "cleanup", "newsletter_subscriber", "",
            f"Cleaned up {count} expired unconfirmed subscribers: {', '.join(emails[:5])}{'...' if count > 5 else ''}"
        )

    return {"success": True, "cleaned": count, "emails": emails}


# ==============================================================================
# RETAILER BANKING & SUBACCOUNT SETUP
# ==============================================================================


def _resolve_bank_account_name(bank_code: str, account_number: str) -> str:
    """Resolve a bank account name using the active payment provider.

    Uses Paystack's resolve account endpoint by default.
    Returns the account name or raises ValueError.
    """
    from app.config import get_settings
    cfg = get_settings()

    if not cfg.paystack_secret_key:
        raise ValueError("Paystack is not configured. Set PAYSTACK_SECRET_KEY in .env")

    import requests
    resp = requests.get(
        f"https://api.paystack.co/bank/resolve?account_number={account_number}&bank_code={bank_code}",
        headers={"Authorization": f"Bearer {cfg.paystack_secret_key}"},
        timeout=15,
    )
    data = resp.json()
    if not data.get("status"):
        raise ValueError(f"Could not resolve account: {data.get('message', 'Unknown error')}")
    return data["data"]["account_name"]


@router.post("/retailer/bank-setup")
def retailer_bank_setup(
    data: dict,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_role("catalog")),
):
    """
    Set up banking details for a retailer.

    Accepts account_number and bank_code, resolves the account name via
    the payment gateway, creates a subaccount for split payments, and
    saves all details to the retailer record.

    Requirements:
        - Admin user must have RETAILER role with vendor_id set to the retailer ID
        - PAYSTACK_SECRET_KEY must be configured in .env
    """
    account_number = (data.get("account_number") or "").strip()
    bank_code = (data.get("bank_code") or "").strip()
    bank_name = (data.get("bank_name") or "").strip()

    if not account_number or not bank_code:
        raise HTTPException(status_code=400, detail="account_number and bank_code are required")

    # Determine the retailer — from vendor_id for RETAILER role, or explicit retailer_id for admins
    retailer_id = data.get("retailer_id") or admin.vendor_id
    if not retailer_id:
        raise HTTPException(status_code=400, detail="Could not determine retailer. Set retailer_id or ensure admin has vendor_id.")

    retailer = db.query(Retailer).filter(Retailer.id == retailer_id).first()
    if not retailer:
        raise HTTPException(status_code=404, detail="Retailer not found")

    # Resolve account name via Paystack
    try:
        account_name = _resolve_bank_account_name(bank_code, account_number)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Determine which payment provider is active
    from app.config import get_settings
    cfg = get_settings()
    provider_name = cfg.default_payment_provider or "paystack"

    if provider_name == "paystack":
        if not cfg.paystack_secret_key:
            raise HTTPException(status_code=400, detail="Paystack secret key is not configured")
        from app.services.wallet_service import PaystackProvider
        provider = PaystackProvider(cfg.paystack_secret_key)
        try:
            subaccount_id = provider.create_subaccount(
                business_name=retailer.name or account_name,
                bank_code=bank_code,
                account_number=account_number,
            )
            retailer.paystack_subaccount_code = subaccount_id
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Subaccount creation failed: {str(e)}")
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported payment provider: {provider_name}")

    # Save bank details
    retailer.bank_name = bank_name or None
    retailer.account_number = account_number
    retailer.bank_code = bank_code
    retailer.account_name = account_name

    db.commit()
    db.refresh(retailer)

    log_admin_action(db, admin, "update", "retailer_banking", retailer.id,
                     f"Set up banking for retailer '{retailer.name}' — {account_name} ({bank_code}/{account_number[-4:]})")

    return {
        "success": True,
        "account_name": account_name,
        "bank_name": bank_name or None,
        "subaccount_id": subaccount_id,
    }


@router.get("/retailer/banking-status")
def retailer_banking_status(
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_role("catalog")),
):
    """Get the banking and subaccount status for the current retailer."""
    retailer_id = admin.vendor_id
    if not retailer_id:
        raise HTTPException(status_code=400, detail="Admin user has no vendor_id")

    retailer = db.query(Retailer).filter(Retailer.id == retailer_id).first()
    if not retailer:
        raise HTTPException(status_code=404, detail="Retailer not found")

    return {
        "bank_name": retailer.bank_name,
        "account_number": retailer.account_number[-4:] if retailer.account_number else None,
        "account_name": retailer.account_name,
        "bank_code": retailer.bank_code,
        "paystack_subaccount_code": retailer.paystack_subaccount_code,
        "commission_rate": retailer.commission_rate,
        "has_banking": bool(retailer.account_number and retailer.bank_code),
        "has_subaccount": bool(retailer.paystack_subaccount_code),
    }


# ==============================================================================
# ADVERTISING CAMPAIGNS
# ==============================================================================


# Ad pricing configuration
AD_PRICING = {
    "SHOP": {"price_per_month": 10000, "label": "Shop Banner Ad"},
    "PRODUCT": {"price_per_month": 5000, "label": "Product Promotion Ad"},
    "SYSTEM_PROMO": {"price_per_month": 0, "label": "System Promo Flyer"},
}

PROMO_PRICING = {
    "PROMO": {"price_per_day": 500, "label": "General Promo"},
    "FLASH_SALE": {"price_per_day": 800, "label": "Flash Sale"},
    "SUPER_SALE": {"price_per_day": 1000, "label": "Super Sale"},
    "HOT_WEEK": {"price_per_day": 1500, "label": "Hot Week"},
    "FESTIVAL": {"price_per_day": 1200, "label": "Festival Sale"},
    "SEASONAL_SALE": {"price_per_day": 700, "label": "Seasonal Sale"},
}

AD_PROVIDERS = {
    "internal": {"label": "Internal (Built-in)", "description": "Use ForgeStore's built-in ad system"},
    "google_ads": {"label": "Google Ads", "description": "Google Ads integration for external ad serving"},
    "meta_ads": {"label": "Meta Ads (Facebook/Instagram)", "description": "Facebook & Instagram ad integration"},
}


@router.post("/ads/initialize")
def initialize_ad_payment(
    data: dict,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_role("ads")),
):
    """
    Initialize an ad campaign payment.

    Creates a PENDING AdCampaign record and returns a payment link to complete
    the subscription fee payment.

    Request body:
        - ad_type: "SHOP", "PRODUCT", or "SYSTEM_PROMO"
        - product_id: (optional) Product ID for PRODUCT ads
        - retailer_id: (optional) Retailer ID for SHOP ads
        - banner_url: Banner image URL for SYSTEM_PROMO
        - target_url: (optional) Target URL for SYSTEM_PROMO
        - duration_months: Number of months (default: 1)

    Returns:
        - authorization_url: Payment link to redirect the retailer
        - reference: Payment reference
        - campaign_id: ID of the created campaign
        - amount: Amount to pay
    """
    from app.config import get_settings
    from app.services.wallet_service import PaymentService
    import uuid

    ad_type = data.get("ad_type", "SHOP").upper()
    product_id = data.get("product_id") or None
    banner_url = data.get("banner_url") or None
    target_url = data.get("target_url") or None
    duration_months = int(data.get("duration_months", 1))

    if ad_type not in AD_PRICING:
        raise HTTPException(status_code=400, detail=f"Invalid ad_type '{ad_type}'. Must be SHOP, PRODUCT, or SYSTEM_PROMO.")

    if ad_type == "PRODUCT" and not product_id:
        raise HTTPException(status_code=400, detail="product_id is required for PRODUCT ads")

    if ad_type == "SYSTEM_PROMO" and not banner_url:
        raise HTTPException(status_code=400, detail="banner_url is required for SYSTEM_PROMO ads")

    # Determine retailer — RETAILERs use their vendor_id, DIR_ADMIN/MANAGEMENT can pass explicit retailer_id
    retailer_id = data.get("retailer_id") or admin.vendor_id
    if ad_type == "SHOP" and not retailer_id:
        raise HTTPException(status_code=400, detail="retailer_id is required for SHOP ads. DIR_ADMIN must pass retailer_id in request.")

    retailer = None
    if retailer_id:
        retailer = db.query(Retailer).filter(Retailer.id == retailer_id).first()
        if not retailer:
            raise HTTPException(status_code=404, detail="Retailer not found")

    # Calculate price
    pricing = AD_PRICING[ad_type]
    amount = pricing["price_per_month"] * duration_months

    # SYSTEM_PROMO ads are free and auto-activate for DIR_ADMIN
    if ad_type == "SYSTEM_PROMO" and admin.role == AdminRole.DIR_ADMIN:
        campaign = AdCampaign(
            retailer_id=None,
            product_id=None,
            ad_type=ad_type,
            status="ACTIVE",
            banner_url=banner_url,
            target_url=target_url,
            start_date=utcnow(),
        )
        from datetime import timedelta
        campaign.end_date = utcnow() + timedelta(days=30)
        db.add(campaign)
        db.commit()
        db.refresh(campaign)

        log_admin_action(db, admin, "create", "ad_campaign", campaign.id,
                         f"Created SYSTEM_PROMO campaign")
        return {
            "success": True,
            "authorization_url": None,
            "reference": None,
            "campaign_id": campaign.id,
            "amount": 0,
            "message": "SYSTEM_PROMO campaign created and activated",
        }

    cfg = get_settings()

    # Create a unique payment reference
    payment_reference = f"AD-{uuid.uuid4().hex[:12].upper()}"

    # Create PENDING AdCampaign
    campaign = AdCampaign(
        retailer_id=retailer_id,
        product_id=product_id,
        ad_type=ad_type,
        status="PENDING",
        payment_reference=payment_reference,
        banner_url=banner_url,
        target_url=target_url,
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)

    # Initialize payment via PaymentService
    payment_service = PaymentService(db)
    callback_url = f"{cfg.site_base_url.rstrip('/')}/admin/ads/callback?campaign_id={campaign.id}"

    metadata = {
        "campaign_id": campaign.id,
        "ad_type": ad_type,
        "retailer_id": retailer_id,
        "duration_months": duration_months,
    }

    try:
        result = payment_service.initialize_payment(
            order_id="",  # No order for ad campaigns
            amount=float(amount),
            currency="NGN",
            metadata=metadata,
        )
        # Patch the reference on the campaign
        campaign.payment_reference = result["reference"]
        db.commit()

        return {
            "success": True,
            "authorization_url": result.get("authorization_url", ""),
            "reference": result["reference"],
            "campaign_id": campaign.id,
            "amount": amount,
            "duration_months": duration_months,
        }
    except ValueError as e:
        # Clean up the campaign on failure
        db.delete(campaign)
        db.commit()
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/ads/campaigns")
def list_ad_campaigns(
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_role("ads")),
):
    """List ad campaigns. RETAILER sees only their own; admins see all."""
    from app.models import AdCampaign

    if admin.role == AdminRole.RETAILER and admin.vendor_id:
        query = db.query(AdCampaign).filter(AdCampaign.retailer_id == admin.vendor_id)
    else:
        query = db.query(AdCampaign)

    campaigns = query.order_by(AdCampaign.created_at.desc()).all()
    return {
        "campaigns": [
            {
                "id": c.id,
                "ad_type": c.ad_type,
                "status": c.status,
                "banner_url": c.banner_url,
                "target_url": c.target_url,
                "retailer_id": c.retailer_id,
                "product_id": c.product_id,
                "start_date": c.start_date.isoformat() if c.start_date else None,
                "end_date": c.end_date.isoformat() if c.end_date else None,
                "payment_reference": c.payment_reference,
                "clicks": c.clicks,
                "impressions": c.impressions,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in campaigns
        ]
    }


@router.put("/ads/{campaign_id}/activate")
def activate_ad_campaign(
    campaign_id: str,
    data: dict,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_admin_role(AdminRole.DIR_ADMIN, AdminRole.MANAGEMENT)),
):
    """Activate a PAID ad campaign (admin-only: DIR_ADMIN or MANAGEMENT).

    Sets status to ACTIVE, assigns start_date/end_date and optional banner_url.
    """
    from app.models import AdCampaign

    campaign = db.query(AdCampaign).filter(AdCampaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    if campaign.status not in ("PAID", "PENDING"):
        raise HTTPException(status_code=400, detail=f"Campaign cannot be activated (status: {campaign.status})")

    campaign.status = "ACTIVE"
    campaign.start_date = utcnow()
    campaign.end_date = utcnow()  # Will be set properly below with timedelta
    # Set end_date based on duration (default 30 days)
    from datetime import timedelta
    campaign.end_date = utcnow() + timedelta(days=30)

    if "banner_url" in data:
        campaign.banner_url = data["banner_url"]

    db.commit()
    log_admin_action(db, admin, "activate", "ad_campaign", campaign_id, f"Activated ad campaign {campaign.id}")

    return {"success": True}


@router.post("/ads/{campaign_id}/expire")
def expire_ad_campaign(
    campaign_id: str,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_admin_role(AdminRole.DIR_ADMIN, AdminRole.MANAGEMENT)),
):
    """Manually expire an ACTIVE ad campaign."""
    from app.models import AdCampaign

    campaign = db.query(AdCampaign).filter(AdCampaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    if campaign.status != "ACTIVE":
        raise HTTPException(status_code=400, detail=f"Campaign is not ACTIVE (status: {campaign.status})")

    campaign.status = "EXPIRED"
    campaign.end_date = utcnow()
    db.commit()

    log_admin_action(db, admin, "expire", "ad_campaign", campaign_id, f"Expired ad campaign {campaign.id}")
    return {"success": True}


# ==============================================================================
# ADMIN IMPERSONATION
# ==============================================================================


@router.post("/impersonate/customer/{customer_id}")
def impersonate_customer(
    customer_id: str,
    response: Response,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_admin_role(AdminRole.DIR_ADMIN, AdminRole.MANAGEMENT)),
):
    """
    Impersonate a customer by generating and setting their session cookie.
    Restricted to DIR_ADMIN and MANAGEMENT roles only.
    """
    customer = db.query(User).filter(User.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    from datetime import timedelta
    token = create_access_token(
        {
            "sub": customer.id,
            "email": customer.email,
            "name": customer.name,
            "type": "customer",
            "impersonated_by": admin.id,
        },
        expires_delta=timedelta(hours=1),
    )

    set_auth_cookie(response, token, "customer_token", max_age_days=1)

    log_admin_action(
        db, admin, "impersonate", "customer", customer_id,
        f"Impersonated customer {customer.email} ({customer.name})",
    )

    return {
        "success": True,
        "redirect_url": "/shop",
    }


# ==============================================================================
# PAYMENT PROVIDER TOGGLE
# ==============================================================================


@router.get("/settings/payment-provider")
def get_payment_provider_setting(
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_role("settings")),
):
    """Get the currently active payment provider."""
    from app.models import Settings as SettingsModel
    from app.config import get_settings as get_env_settings

    env = get_env_settings()

    setting = db.query(SettingsModel).filter(
        SettingsModel.key == "default_payment_provider"
    ).first()
    db_provider = setting.value if setting else None
    active_provider = db_provider or env.default_payment_provider or "paystack"

    return {
        "active_provider": active_provider,
        "source": "database" if db_provider else "environment",
        "available_providers": ["paystack"],
    }


@router.post("/settings/payment-provider")
def set_payment_provider(
    data: dict,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_admin_role(AdminRole.DIR_ADMIN)),
):
    """
    Toggle the active payment provider.

    Request body:
        - provider: "paystack"

    This updates the ``default_payment_provider`` key in the Settings table.
    The change takes effect immediately for all subsequent payment operations.
    """
    from app.models import Settings as SettingsModel
    from app.services.payment_provider import invalidate_provider_cache

    provider = (data.get("provider") or "").strip().lower()

    if provider not in ("paystack",):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid provider '{provider}'. Must be 'paystack'."
        )

    setting = db.query(SettingsModel).filter(
        SettingsModel.key == "default_payment_provider"
    ).first()

    if setting:
        setting.value = provider
    else:
        setting = SettingsModel(
            key="default_payment_provider",
            value=provider,
            category="developer",
            setting_type="select",
            label="Default Payment Provider",
        )
        db.add(setting)

    db.commit()

    # Invalidate both caches so the change is picked up immediately
    invalidate_provider_cache()
    from app.config import invalidate_settings_cache
    invalidate_settings_cache()

    log_admin_action(db, admin, "update", "payment_provider", "",
                     f"Switched default payment provider to {provider}")

    return {"success": True, "active_provider": provider}


@router.get("/ads/pricing")
def get_ad_pricing():
    """Get ad pricing configuration."""
    return {"pricing": AD_PRICING, "promo_pricing": PROMO_PRICING}


@router.get("/ads/settings")
def get_ads_settings(
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_admin_role(AdminRole.DIR_ADMIN)),
):
    """Get all ads-related settings."""
    settings_keys = [
        "ads_default_provider", "ads_auto_approve", "ads_max_duration_days",
        "ads_min_budget", "promo_ads_enabled", "promo_flash_sale_enabled",
        "promo_hot_week_enabled", "promo_festival_enabled",
    ]
    settings = {}
    for key in settings_keys:
        s = db.query(Settings).filter(Settings.key == key).first()
        settings[key] = s.value if s else ""
    return {"settings": settings, "pricing": AD_PRICING, "promo_pricing": PROMO_PRICING}


@router.post("/ads/settings")
def update_ads_settings(
    data: dict,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_admin_role(AdminRole.DIR_ADMIN)),
):
    """Update ads-related settings (pricing, provider, toggles)."""
    settings_map = {
        "ads_default_provider": data.get("ads_default_provider", "internal"),
        "ads_auto_approve": str(data.get("ads_auto_approve", "false")).lower(),
        "ads_max_duration_days": str(data.get("ads_max_duration_days", "90")),
        "ads_min_budget": str(data.get("ads_min_budget", "1000")),
        "promo_ads_enabled": str(data.get("promo_ads_enabled", "true")).lower(),
        "promo_flash_sale_enabled": str(data.get("promo_flash_sale_enabled", "true")).lower(),
        "promo_hot_week_enabled": str(data.get("promo_hot_week_enabled", "true")).lower(),
        "promo_festival_enabled": str(data.get("promo_festival_enabled", "true")).lower(),
    }

    # Update pricing if provided
    if "promo_pricing" in data:
        for subtype, price_data in data["promo_pricing"].items():
            if subtype in PROMO_PRICING and "price_per_day" in price_data:
                PROMO_PRICING[subtype]["price_per_day"] = int(price_data["price_per_day"])

    for key, value in settings_map.items():
        existing = db.query(Settings).filter(Settings.key == key).first()
        if existing:
            existing.value = value
        else:
            setting = Settings(
                key=key,
                value=value,
                category="optional",
                setting_type="text",
                label=key.replace("_", " ").title(),
            )
            db.add(setting)

    db.commit()

    from app.config import invalidate_settings_cache
    invalidate_settings_cache()

    log_admin_action(db, admin, "update", "ads_settings", "",
                     f"Updated ads settings: {list(settings_map.keys())}")

    return {"success": True}


@router.get("/ads/analytics")
def get_ad_analytics(
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_admin_role(AdminRole.DIR_ADMIN, AdminRole.MANAGEMENT)),
):
    """Get aggregated ad campaign analytics for the admin dashboard."""
    from app.models import AdCampaign, Retailer
    from datetime import timedelta

    # Overall stats
    total_campaigns = db.query(func.count(AdCampaign.id)).scalar() or 0
    active_campaigns = db.query(func.count(AdCampaign.id)).filter(AdCampaign.status == "ACTIVE").scalar() or 0
    total_clicks = db.query(func.coalesce(func.sum(AdCampaign.clicks), 0)).scalar() or 0
    total_impressions = db.query(func.coalesce(func.sum(AdCampaign.impressions), 0)).scalar() or 0
    total_spent = total_campaigns * sum(p["price_per_month"] for p in AD_PRICING.values()) // len(AD_PRICING)

    # CTR (Click-Through Rate)
    ctr = round(total_clicks / total_impressions * 100, 2) if total_impressions > 0 else 0

    # Breakdown by type
    shop_campaigns = db.query(func.count(AdCampaign.id)).filter(AdCampaign.ad_type == "SHOP").scalar() or 0
    product_campaigns = db.query(func.count(AdCampaign.id)).filter(AdCampaign.ad_type == "PRODUCT").scalar() or 0

    # Status distribution
    status_counts = {}
    for status in ("PENDING", "PAID", "ACTIVE", "EXPIRED"):
        status_counts[status] = db.query(func.count(AdCampaign.id)).filter(
            AdCampaign.status == status
        ).scalar() or 0

    # Top retailers by campaign count
    top_retailers_data = db.query(
        AdCampaign.retailer_id,
        func.count(AdCampaign.id).label("campaign_count"),
        func.coalesce(func.sum(AdCampaign.clicks), 0).label("total_clicks"),
        func.coalesce(func.sum(AdCampaign.impressions), 0).label("total_impressions"),
    ).group_by(AdCampaign.retailer_id).order_by(func.count(AdCampaign.id).desc()).limit(10).all()

    retailer_ids = [r.retailer_id for r in top_retailers_data]
    retailer_names = {
        r.id: r.name for r in db.query(Retailer).filter(Retailer.id.in_(retailer_ids)).all()
    } if retailer_ids else {}

    top_retailers = []
    for r in top_retailers_data:
        r_ctr = round(r.total_clicks / r.total_impressions * 100, 2) if r.total_impressions > 0 else 0
        top_retailers.append({
            "retailer_id": r.retailer_id,
            "retailer_name": retailer_names.get(r.retailer_id, "Unknown"),
            "campaign_count": r.campaign_count,
            "total_clicks": r.total_clicks,
            "total_impressions": r.total_impressions,
            "ctr": r_ctr,
        })

    # Monthly trend (last 6 months)
    from datetime import datetime
    now = utcnow()
    monthly_trend = []
    for i in range(5, -1, -1):
        month = now.month - i
        year = now.year
        while month < 1:
            month += 12
            year -= 1
        month_start = datetime(year, month, 1)
        if month == 12:
            month_end = datetime(year + 1, 1, 1)
        else:
            month_end = datetime(year, month + 1, 1)

        month_campaigns = db.query(func.count(AdCampaign.id)).filter(
            AdCampaign.created_at >= month_start,
            AdCampaign.created_at < month_end,
        ).scalar() or 0

        month_clicks = db.query(func.coalesce(func.sum(AdCampaign.clicks), 0)).filter(
            AdCampaign.created_at >= month_start,
            AdCampaign.created_at < month_end,
        ).scalar() or 0

        month_imps = db.query(func.coalesce(func.sum(AdCampaign.impressions), 0)).filter(
            AdCampaign.created_at >= month_start,
            AdCampaign.created_at < month_end,
        ).scalar() or 0

        monthly_trend.append({
            "month": month_start.strftime("%b %Y"),
            "campaigns": month_campaigns,
            "clicks": month_clicks,
            "impressions": month_imps,
        })

    return {
        "overview": {
            "total_campaigns": total_campaigns,
            "active_campaigns": active_campaigns,
            "total_clicks": total_clicks,
            "total_impressions": total_impressions,
            "ctr": ctr,
            "total_spent": total_spent,
        },
        "by_type": {
            "SHOP": shop_campaigns,
            "PRODUCT": product_campaigns,
        },
        "by_status": status_counts,
        "top_retailers": top_retailers,
        "monthly_trend": monthly_trend,
    }


# ==============================================================================
# PROMO ADS CRUD
# ==============================================================================


@router.get("/promo-ads")
def list_promo_ads(
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_role("catalog")),
):
    """List promo ads. RETAILER sees only their own; others see all."""
    from app.models import PromoAd

    query = db.query(PromoAd)
    if admin.role == AdminRole.RETAILER and admin.vendor_id:
        query = query.filter(
            (PromoAd.retailer_id == admin.vendor_id) | (PromoAd.retailer_id == None)
        )
    promo_ads = query.order_by(PromoAd.created_at.desc()).all()

    return {
        "promo_ads": [
            {
                "id": a.id,
                "title": a.title,
                "ad_subtype": a.ad_subtype,
                "banner_type": a.banner_type,
                "banner_url": a.banner_url,
                "target_url": a.target_url,
                "status": a.status,
                "retailer_id": a.retailer_id,
                "start_date": a.start_date.isoformat() if a.start_date else None,
                "end_date": a.end_date.isoformat() if a.end_date else None,
                "clicks": a.clicks,
                "impressions": a.impressions,
                "note": a.note,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in promo_ads
        ]
    }


@router.post("/promo-ads")
def create_promo_ad(
    data: dict,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_role("catalog")),
):
    """Create a new promo ad. DIR_ADMIN, MANAGEMENT, and RETAILER can create."""
    from app.models import PromoAd

    title = (data.get("title") or "").strip()
    ad_subtype = (data.get("ad_subtype") or "PROMO").upper()
    banner_type = (data.get("banner_type") or "banner").lower()
    banner_url = (data.get("banner_url") or "").strip()
    target_url = (data.get("target_url") or "").strip() or None
    status = (data.get("status") or "ACTIVE").upper()
    note = (data.get("note") or "").strip() or None

    if not title:
        raise HTTPException(status_code=400, detail="title is required")
    if not banner_url:
        raise HTTPException(status_code=400, detail="banner_url is required")
    if ad_subtype not in ("PROMO", "FLASH_SALE", "SUPER_SALE", "HOT_WEEK", "FESTIVAL", "SEASONAL_SALE"):
        raise HTTPException(status_code=400, detail="ad_subtype must be PROMO, FLASH_SALE, SUPER_SALE, HOT_WEEK, FESTIVAL, or SEASONAL_SALE")
    if banner_type not in ("banner", "poster", "flyer"):
        raise HTTPException(status_code=400, detail="banner_type must be banner, poster, or flyer")

    # RETAILER can only create for their own retailer_id
    retailer_id = data.get("retailer_id") or admin.vendor_id
    if admin.role == AdminRole.RETAILER:
        retailer_id = admin.vendor_id

    # Default duration: 30 days
    from datetime import timedelta
    start_date = data.get("start_date") or utcnow()
    end_date = data.get("end_date") or (utcnow() + timedelta(days=30))

    promo_ad = PromoAd(
        title=title,
        ad_subtype=ad_subtype,
        banner_type=banner_type,
        banner_url=banner_url,
        target_url=target_url,
        status=status,
        created_by=admin.id,
        retailer_id=retailer_id,
        start_date=start_date,
        end_date=end_date,
        note=note,
    )
    db.add(promo_ad)
    db.commit()
    db.refresh(promo_ad)

    log_admin_action(db, admin, "create", "promo_ad", promo_ad.id,
                     f"Created promo ad '{title}' ({ad_subtype}/{banner_type})")

    return {"success": True, "id": promo_ad.id}


@router.put("/promo-ads/{ad_id}")
def update_promo_ad(
    ad_id: str,
    data: dict,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_role("catalog")),
):
    """Update a promo ad."""
    from app.models import PromoAd

    promo_ad = db.query(PromoAd).filter(PromoAd.id == ad_id).first()
    if not promo_ad:
        raise HTTPException(status_code=404, detail="Promo ad not found")

    # RETAILER can only update their own ads
    if admin.role == AdminRole.RETAILER:
        if promo_ad.retailer_id != admin.vendor_id:
            raise HTTPException(status_code=403, detail="You can only edit your own promo ads")

    updatable = ["title", "ad_subtype", "banner_type", "banner_url", "target_url",
                 "status", "note", "start_date", "end_date"]
    for key in updatable:
        if key in data:
            setattr(promo_ad, key, data[key])

    promo_ad.updated_at = utcnow()
    db.commit()

    log_admin_action(db, admin, "update", "promo_ad", ad_id, f"Updated promo ad '{promo_ad.title}'")
    return {"success": True}


@router.delete("/promo-ads/{ad_id}")
def delete_promo_ad(
    ad_id: str,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_role("catalog")),
):
    """Delete a promo ad."""
    from app.models import PromoAd

    promo_ad = db.query(PromoAd).filter(PromoAd.id == ad_id).first()
    if not promo_ad:
        raise HTTPException(status_code=404, detail="Promo ad not found")

    # RETAILER can only delete their own ads
    if admin.role == AdminRole.RETAILER:
        if promo_ad.retailer_id != admin.vendor_id:
            raise HTTPException(status_code=403, detail="You can only delete your own promo ads")

    db.delete(promo_ad)
    db.commit()

    log_admin_action(db, admin, "delete", "promo_ad", ad_id, f"Deleted promo ad '{promo_ad.title}'")
    return {"success": True}


# ==============================================================================
# ORDER EARNINGS (Retailer Payout View)
# ==============================================================================


@router.get("/earnings")
def list_earnings(
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_role("catalog")),
):
    """
    Get order earnings for the current retailer.
    RETAILER role sees their own earnings; DIR_ADMIN/MANAGEMENT see all.
    """
    from app.models import OrderEarning

    query = db.query(OrderEarning)
    if admin.role == AdminRole.RETAILER and admin.vendor_id:
        query = query.filter(OrderEarning.retailer_id == admin.vendor_id)

    earnings = query.order_by(OrderEarning.created_at.desc()).limit(100).all()

    # Fetch related order numbers and product names
    order_ids = list(set(e.order_id for e in earnings))
    product_ids = list(set(e.product_id for e in earnings if e.product_id))
    orders = {o.id: o.order_number for o in db.query(Order).filter(Order.id.in_(order_ids)).all()} if order_ids else {}
    products = {p.id: p.name for p in db.query(Product).filter(Product.id.in_(product_ids)).all()} if product_ids else {}

    total_amount = sum(e.amount for e in earnings) if earnings else 0
    total_commission = sum(e.commission for e in earnings) if earnings else 0
    total_net = sum(e.net_amount for e in earnings) if earnings else 0

    return {
        "earnings": [
            {
                "id": e.id,
                "order_id": e.order_id,
                "order_number": orders.get(e.order_id, "Unknown"),
                "product_id": e.product_id,
                "product_name": products.get(e.product_id, "Unknown"),
                "amount": e.amount,
                "commission": e.commission,
                "net_amount": e.net_amount,
                "status": e.status,
                "paid_at": e.paid_at.isoformat() if e.paid_at else None,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in earnings
        ],
        "summary": {
            "total_amount": total_amount,
            "total_commission": total_commission,
            "total_net": total_net,
            "count": len(earnings),
        },
    }


# ==============================================================================
# REQUEST PAYOUT (RETAILER SELF-SERVICE)
# ==============================================================================


@router.post("/earnings/request-payout")
def request_earnings_payout(
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_role("catalog")),
):
    """
    Request payout for all SCHEDULED earnings.

    RETAILER role only — marks all their SCHEDULED/PENDING earnings as PAID.
    This is a self-service payout request that does not require admin approval.
    """
    from app.models import OrderEarning

    if admin.role != AdminRole.RETAILER:
        raise HTTPException(status_code=403, detail="Only RETAILERs can request payouts")

    retailer_id = admin.vendor_id
    if not retailer_id:
        raise HTTPException(status_code=400, detail="Admin user has no vendor_id")

    earnings = db.query(OrderEarning).filter(
        OrderEarning.retailer_id == retailer_id,
        OrderEarning.status.in_(["SCHEDULED", "PENDING"]),
    ).all()

    if not earnings:
        return {"success": True, "marked": 0, "message": "No pending earnings to request payout for"}

    now = utcnow()
    for e in earnings:
        e.status = "PAID"
        e.paid_at = now

    db.commit()

    total_net = sum(e.net_amount for e in earnings)

    log_admin_action(
        db, admin, "request_payout", "order_earning", "",
        f"Requested payout for {len(earnings)} order earnings (total net: ₦{total_net:.2f})"
    )

    # Send payout notification email (non-blocking via BackgroundTasks)
    if admin.email:
        retailer = db.query(Retailer).filter(Retailer.id == retailer_id).first()
        retailer_name = retailer.name if retailer else admin.name or "Retailer"
        try:
            from app.services.email_service import send_payout_email
            # Use dispatch_email_background for non-blocking send
            from app.core.email import dispatch_email_background
            from app.services.email_service import _render_email_template, _base_context
            html = _render_email_template("payout_processed.html", _base_context(
                heading="Payout Processed!",
                subtitle=f"₦{total_net:,.2f} paid",
                body_html=f"<p>Hi <strong>{retailer_name}</strong>, your payout has been processed.</p>",
                amount=total_net,
                earning_count=len(earnings),
                customer_name=retailer_name,
            ))
            dispatch_email_background(admin.email, f"Payout Processed — ForgeStore", html)
        except Exception:
            pass  # Email failure should not block payout

    return {
        "success": True,
        "marked": len(earnings),
        "total_net": total_net,
        "message": f"Marked {len(earnings)} earning(s) as PAID",
    }


# ==============================================================================
# BATCH MARK EARNINGS AS PAID
# ==============================================================================


@router.post("/earnings/batch-mark-paid")
def batch_mark_earnings_paid(
    data: dict,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_admin_role(AdminRole.DIR_ADMIN, AdminRole.MANAGEMENT)),
):
    """
    Batch-mark order earnings as PAID.

    Accepts either:
      - earning_ids: list of specific earning IDs to mark paid
      - filter_all_pending: true to mark ALL PENDING earnings as paid (for the current retailer if RETAILER role)

    DIR_ADMIN and MANAGEMENT only.
    """
    from app.models import OrderEarning

    earning_ids = data.get("earning_ids", None)
    filter_all_pending = data.get("filter_all_pending", False)

    query = db.query(OrderEarning).filter(OrderEarning.status.in_(["PENDING", "SCHEDULED"]))

    if admin.role == AdminRole.RETAILER and admin.vendor_id:
        query = query.filter(OrderEarning.retailer_id == admin.vendor_id)

    if earning_ids and isinstance(earning_ids, list) and len(earning_ids) > 0:
        query = query.filter(OrderEarning.id.in_(earning_ids))
    elif not filter_all_pending:
        raise HTTPException(
            status_code=400,
            detail="Provide earning_ids or set filter_all_pending=true"
        )

    earnings = query.all()
    if not earnings:
        return {"success": True, "marked": 0, "message": "No pending earnings to mark as paid"}

    now = utcnow()
    for e in earnings:
        e.status = "PAID"
        e.paid_at = now

    db.commit()

    log_admin_action(
        db, admin, "batch_mark_paid", "order_earning", "",
        f"Batch-marked {len(earnings)} order earnings as PAID"
    )

    # Send payout notification emails to affected retailers (non-blocking via dispatch_email_background)
    from app.core.email import dispatch_email_background
    from app.services.email_service import _render_email_template, _base_context
    retailer_groups: dict = {}
    for e in earnings:
        if e.retailer_id not in retailer_groups:
            retailer_groups[e.retailer_id] = []
        retailer_groups[e.retailer_id].append(e)

    for r_id, r_earnings in retailer_groups.items():
        r_total_net = sum(e.net_amount for e in r_earnings)
        r_admin = db.query(AdminUser).filter(
            AdminUser.vendor_id == r_id,
            AdminUser.role == AdminRole.RETAILER
        ).first()
        if r_admin and r_admin.email:
            retailer = db.query(Retailer).filter(Retailer.id == r_id).first()
            retailer_name = retailer.name if retailer else r_admin.name or "Retailer"
            try:
                html = _render_email_template("payout_processed.html", _base_context(
                    heading="Payout Processed!",
                    subtitle=f"₦{r_total_net:,.2f} paid",
                    body_html=f"<p>Hi <strong>{retailer_name}</strong>, your payout has been processed.</p>",
                    amount=r_total_net,
                    earning_count=len(r_earnings),
                    customer_name=retailer_name,
                ))
                dispatch_email_background(r_admin.email, f"Payout Processed — ForgeStore", html)
            except Exception:
                pass

    return {
        "success": True,
        "marked": len(earnings),
        "message": f"Marked {len(earnings)} earning(s) as PAID",
    }


# ==============================================================================
# File Upload
# ==============================================================================
@router.post("/upload")
async def upload_file(files: List[UploadFile] = File(...)):
    upload_dir = os.path.join("app", "static", "uploads", "products")
    os.makedirs(upload_dir, exist_ok=True)

    urls = []
    for file in files:
        raw = await file.read()
        compressed, ext = compress_image(raw)
        unique_name = f"{int(utcnow().timestamp())}-{uuid.uuid4().hex[:8]}.{ext}"
        file_path = os.path.join(upload_dir, unique_name)

        with open(file_path, "wb") as f:
            f.write(compressed)

        urls.append(f"/static/uploads/products/{unique_name}")

    return {"urls": urls}


# ==============================================================================
# CUSTOMER ACCOUNT DELETION (Admin)
# ==============================================================================

@router.delete("/customers/{customer_id}")
def admin_delete_customer(
    customer_id: str,
    response: Response,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_admin_role(AdminRole.DIR_ADMIN, AdminRole.MANAGEMENT)),
):
    """
    Admin-force delete a customer account.
    Restricted to DIR_ADMIN and MANAGEMENT roles.
    """
    customer = db.query(User).filter(User.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    # Delete related records in correct order (items before orders)
    order_ids = [o.id for o in db.query(Order.id).filter(Order.customer_id == customer_id).subquery()]
    db.query(OrderItem).filter(OrderItem.order_id.in_(order_ids)).delete(synchronize_session=False)
    db.query(Order).filter(Order.customer_id == customer_id).delete(synchronize_session=False)
    db.query(Review).filter(Review.user_id == customer_id).delete(synchronize_session=False)

    email = customer.email
    name = customer.name
    db.delete(customer)
    db.commit()

    log_admin_action(db, admin, "delete", "customer", customer_id,
                     f"Admin-deleted customer {email} ({name})")

    response.delete_cookie("customer_token")

    return {"success": True, "message": f"Customer {email} deleted successfully"}


# --- Chat Moderation API ---

@router.post("/chat-moderate/{message_id}")
def moderate_chat_message(
    message_id: str,
    data: dict,
    request: Request,
    db: Session = Depends(get_db),
):
    """Moderate a product chat message: flag, hide, unhide, or delete."""
    from app.models import ProductChatMessage, ChatModeration

    admin = get_current_admin(request, db)
    if not admin:
        raise HTTPException(status_code=401, detail="Not authenticated")

    msg = db.query(ProductChatMessage).filter(ProductChatMessage.id == message_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")

    action = data.get("action", "")
    reason = data.get("reason", "")
    notes = data.get("notes", "")

    if action == "flag":
        msg.is_flagged = True
        mod = ChatModeration(
            message_id=message_id,
            status="PENDING",
            reason=reason or "flagged_by_admin",
            notes=notes,
            reviewed_by=admin.id,
        )
        db.add(mod)
    elif action == "unflag":
        msg.is_flagged = False
    elif action == "hide":
        msg.is_hidden = True
        msg.is_flagged = True
        mod = ChatModeration(
            message_id=message_id,
            status="REJECTED",
            reason=reason or "hidden_by_admin",
            notes=notes,
            reviewed_by=admin.id,
            reviewed_at=utcnow(),
        )
        db.add(mod)
    elif action == "unhide":
        msg.is_hidden = False
    elif action == "delete":
        db.delete(msg)
    else:
        raise HTTPException(status_code=400, detail=f"Unknown action: {action}")

    db.commit()
    log_admin_action(db, admin, "moderate", "chat_message", message_id,
                     f"Chat moderation: {action} by {admin.email}")

    return {"success": True}


# ==============================================================================
# PUBLIC VENDOR APPLICATION FUNNEL
# ==============================================================================


@router.post("/vendor/apply")
def vendor_apply(data: dict, db: Session = Depends(get_db)):
    """Public endpoint for vendor applications. No auth required."""
    from app.models import VendorApplication

    email = (data.get("email") or "").strip()
    business_name = (data.get("business_name") or "").strip()
    if not email or not business_name:
        raise HTTPException(status_code=400, detail="email and business_name are required")

    application = VendorApplication(
        full_name=data.get("full_name", ""),
        email=email,
        phone=data.get("phone", ""),
        business_name=business_name,
        description=data.get("description", ""),
        account_number=data.get("account_number", ""),
        bank_code=data.get("bank_code", ""),
        bank_name=data.get("bank_name", ""),
        catalog_category=data.get("catalog_category", ""),
        status="PENDING",
    )
    db.add(application)
    db.commit()
    db.refresh(application)

    # Notify admin
    from app.models import AdminNotification
    notif = AdminNotification(
        type="info",
        title="New Vendor Application",
        message=f"{business_name} ({email}) has applied to become a vendor.",
        link="/admin/settings",
    )
    db.add(notif)
    db.commit()

    return {"success": True, "application_id": application.id}


@router.post("/admin/vendor/approve/{application_id}")
def approve_vendor_application(
    application_id: str,
    data: dict,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_admin_role(AdminRole.DIR_ADMIN, AdminRole.MANAGEMENT)),
):
    """Approve or reject a vendor application. Creates Retailer + AdminUser with RETAILER role."""
    from app.models import VendorApplication, Retailer as RetailerModel, AdminUser as AdminUserModel
    import re

    app = db.query(VendorApplication).filter(VendorApplication.id == application_id).first()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    action = data.get("action", "approve")
    if action not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="action must be 'approve' or 'reject'")

    app.status = "APPROVED" if action == "approve" else "REJECTED"
    app.reviewed_by = admin.id
    app.reviewed_at = utcnow()
    app.notes = data.get("notes", "")

    if action == "approve":
        # Create slug from business name
        slug = re.sub(r'[^a-z0-9]+', '-', app.business_name.lower().strip()).strip('-')
        # Ensure uniqueness
        existing_slug = db.query(RetailerModel).filter(RetailerModel.slug == slug).first()
        if existing_slug:
            slug = f"{slug}-{uuid.uuid4().hex[:6]}"

        retailer = RetailerModel(
            name=app.business_name,
            slug=slug,
            bio=app.description,
            location=app.phone,
            status="ACTIVE",
            bank_name=app.bank_name,
            account_number=app.account_number,
            bank_code=app.bank_code,
        )
        db.add(retailer)
        db.commit()
        db.refresh(retailer)

        # Create admin user with RETAILER role
        temp_password = f"vendor-{uuid.uuid4().hex[:8]}"
        new_admin = AdminUserModel(
            email=app.email,
            password=hash_password(temp_password),
            name=app.full_name or app.business_name,
            role=AdminRole.RETAILER,
            vendor_id=retailer.id,
        )
        db.add(new_admin)
        db.commit()

        # Create vendor wallet
        from app.models import VendorWallet
        wallet = VendorWallet(retailer_id=retailer.id, balance=0.0, pending_balance=0.0)
        db.add(wallet)
        db.commit()

        log_admin_action(db, admin, "approve", "vendor_application", application_id,
                         f"Approved vendor '{app.business_name}' — created retailer {retailer.id}")

        return {"success": True, "retailer_id": retailer.id, "admin_email": app.email, "temp_password": temp_password}
    else:
        log_admin_action(db, admin, "reject", "vendor_application", application_id,
                         f"Rejected vendor '{app.business_name}'")
        db.commit()
        return {"success": True, "status": "REJECTED"}


# ==============================================================================
# AFFILIATE APPLICATION APPROVAL
# ==============================================================================


@router.post("/admin/affiliate/approve/{application_id}")
def approve_affiliate_application(
    application_id: str,
    data: dict,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_admin_role(AdminRole.DIR_ADMIN, AdminRole.MANAGEMENT)),
):
    """Approve or reject an affiliate application. Creates Affiliate record on approval."""
    from app.models import AffiliateApplication, Affiliate as AffiliateModel
    import secrets

    app = db.query(AffiliateApplication).filter(AffiliateApplication.id == application_id).first()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    action = data.get("action", "approve")
    if action not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="action must be 'approve' or 'reject'")

    app.status = "APPROVED" if action == "approve" else "REJECTED"
    app.reviewed_by = admin.id
    app.reviewed_at = utcnow()
    app.notes = data.get("notes", "")

    if action == "approve":
        code = secrets.token_urlsafe(8).upper()
        affiliate = AffiliateModel(
            user_id=app.user_id,
            code=code,
            name=app.full_name,
            email=app.email,
            type="referral",
            commission_rate=5.0,
            status="ACTIVE",
        )
        db.add(affiliate)
        db.commit()

        log_admin_action(db, admin, "approve", "affiliate_application", application_id,
                         f"Approved affiliate for user {app.user_id}")
        return {"success": True, "affiliate_code": code}
    else:
        log_admin_action(db, admin, "reject", "affiliate_application", application_id,
                         f"Rejected affiliate for user {app.user_id}")
        db.commit()
        return {"success": True, "status": "REJECTED"}


# ==============================================================================
# ADMIN VENDOR APPLICATIONS MANAGEMENT
# ==============================================================================


@router.get("/admin/vendor-applications")
def list_vendor_applications(
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_admin_role(AdminRole.DIR_ADMIN, AdminRole.MANAGEMENT)),
):
    """List all vendor applications."""
    from app.models import VendorApplication
    apps = db.query(VendorApplication).order_by(VendorApplication.created_at.desc()).all()
    return {
        "applications": [
            {
                "id": a.id,
                "business_name": a.business_name,
                "email": a.email,
                "phone": a.phone,
                "status": a.status,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in apps
        ]
    }


@router.get("/admin/affiliate-applications")
def list_affiliate_applications(
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_admin_role(AdminRole.DIR_ADMIN, AdminRole.MANAGEMENT)),
):
    """List all affiliate applications."""
    from app.models import AffiliateApplication
    apps = db.query(AffiliateApplication).order_by(AffiliateApplication.created_at.desc()).all()
    return {
        "applications": [
            {
                "id": a.id,
                "user_id": a.user_id,
                "full_name": a.full_name,
                "email": a.email,
                "status": a.status,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in apps
        ]
    }


# ==============================================================================
# VENDOR RISK SAFEGUARD
# ==============================================================================


@router.post("/admin/vendor-risk-check")
def vendor_risk_check(
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_admin_role(AdminRole.DIR_ADMIN, AdminRole.MANAGEMENT)),
):
    """Check all vendor ratings and auto-suspend those below threshold.

    Reads the minimum rating threshold from SystemSettings.
    """
    from app.models import Retailer as RetailerModel, Product, Settings as SettingsModel

    # Get threshold
    setting = db.query(SettingsModel).filter(SettingsModel.key == "vendor_minimum_rating").first()
    threshold = float(setting.value) if setting else 3.0
    if threshold <= 0:
        return {"success": True, "suspended": 0, "message": "Risk check disabled (threshold=0)"}

    suspended = 0
    retailers = db.query(RetailerModel).filter(RetailerModel.status == "ACTIVE").all()
    for r in retailers:
        if r.rating > 0 and r.rating < threshold:
            r.status = "SUSPENDED"
            # Hide all products from public storefront
            db.query(Product).filter(Product.retailer_id == r.id).update({"inventory": 0})
            suspended += 1

    db.commit()

    if suspended > 0:
        log_admin_action(db, admin, "risk_check", "retailer", "",
                         f"Auto-suspended {suspended} vendors below rating threshold {threshold}")

    return {"success": True, "suspended": suspended, "threshold": threshold}


# ==============================================================================
# VENDOR PAYOUT PROCESSING (ADMIN)
# ==============================================================================


@router.post("/admin/payouts/{payout_id}/process")
def process_payout(
    payout_id: str,
    data: dict,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_admin_role(AdminRole.DIR_ADMIN, AdminRole.MANAGEMENT)),
):
    """Approve/reject and process a vendor payout request.

    On APPROVE: triggers a background transfer via Paystack/Flutterwave bulk transfer API.
    On REJECT: returns locked funds to vendor balance.
    """
    from app.models import PayoutRequest, VendorWallet, VendorWalletTransaction

    payout = db.query(PayoutRequest).filter(PayoutRequest.id == payout_id).first()
    if not payout:
        raise HTTPException(status_code=404, detail="Payout request not found")

    action = data.get("action", "approve")
    if action not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="action must be 'approve' or 'reject'")

    payout.processed_by = admin.id
    payout.processed_at = utcnow()

    wallet = db.query(VendorWallet).filter(VendorWallet.retailer_id == payout.retailer_id).first()

    if action == "reject":
        payout.status = "REJECTED"
        payout.notes = data.get("notes", "Rejected by admin")
        # Return locked funds
        if wallet:
            wallet.locked_escrow_balance -= payout.amount
            wallet.balance += payout.amount
            tx = VendorWalletTransaction(
                wallet_id=wallet.id,
                transaction_type="refund",
                amount=payout.amount,
                balance_before=wallet.balance - payout.amount,
                balance_after=wallet.balance,
                reference=f"PAYOUT-REJECT-{payout.id[:8]}",
                description=f"Payout rejected — funds returned",
                status="COMPLETED",
            )
            db.add(tx)
        db.commit()
        log_admin_action(db, admin, "reject_payout", "payout", payout_id,
                         f"Rejected payout ₦{payout.amount:.2f} for {payout.retailer_id}")
        return {"success": True, "status": "REJECTED"}

    # Approve and process
    payout.status = "APPROVED"
    payout.notes = data.get("notes", "")

    # Background transfer via payment provider
    try:
        from app.config import get_settings as gs
        cfg = gs()
        import uuid as _uuid
        ref = f"PAYOUT-{_uuid.uuid4().hex[:12].upper()}"
        payout.payment_reference = ref

        # Attempt Paystack transfer (if configured)
        if cfg.paystack_secret_key and payout.account_number and payout.bank_code:
            import requests as _requests
            resp = _requests.post(
                "https://api.paystack.co/transfer",
                json={
                    "source": "balance",
                    "amount": int(payout.amount * 100),
                    "currency": "NGN",
                    "reason": f"Vendor payout for {payout.retailer_id}",
                    "account_number": payout.account_number,
                    "bank_code": payout.bank_code,
                },
                headers={"Authorization": f"Bearer {cfg.paystack_secret_key}"},
                timeout=30,
            )
            result = resp.json()
            if result.get("status"):
                payout.status = "SUCCESSFUL"
            else:
                payout.status = "FAILED"
                payout.failure_reason = result.get("message", "Transfer failed")
        else:
            # No gateway configured — mark as successful (manual processing)
            payout.status = "SUCCESSFUL"

        # On success: deduct from locked_escrow_balance
        if payout.status == "SUCCESSFUL" and wallet:
            wallet.locked_escrow_balance -= payout.amount
            tx = VendorWalletTransaction(
                wallet_id=wallet.id,
                transaction_type="withdrawal",
                amount=-payout.amount,
                balance_before=wallet.balance,
                balance_after=wallet.balance,
                reference=ref,
                description=f"Payout processed — ₦{payout.amount:.2f} transferred",
                status="COMPLETED",
            )
            db.add(tx)

    except Exception as e:
        payout.status = "FAILED"
        payout.failure_reason = str(e)

    db.commit()
    log_admin_action(db, admin, "process_payout", "payout", payout_id,
                     f"Processed payout ₦{payout.amount:.2f} — status: {payout.status}")

    # Send payout success receipt email via BackgroundTasks (non-blocking)
    if payout.status == "SUCCESSFUL" and payout.retailer_id:
        try:
            from app.core.email import dispatch_email_background
            from app.services.email_service import _render_email_template, _base_context
            r_admin = db.query(AdminUser).filter(
                AdminUser.vendor_id == payout.retailer_id,
                AdminUser.role == AdminRole.RETAILER,
            ).first()
            if r_admin and r_admin.email:
                retailer_obj = db.query(Retailer).filter(Retailer.id == payout.retailer_id).first()
                r_name = retailer_obj.name if retailer_obj else r_admin.name or "Vendor"
                html = _render_email_template("payout_processed.html", _base_context(
                    heading="Payout Processed!",
                    subtitle=f"₦{payout.amount:,.2f} paid",
                    body_html=f"<p>Hi <strong>{r_name}</strong>, your payout has been processed.</p>",
                    amount=payout.amount,
                    earning_count=1,
                    customer_name=r_name,
                ))
                background_tasks.add_task(dispatch_email_background, r_admin.email, f"Payout Processed — ForgeStore", html)
        except Exception:
            pass

    return {"success": True, "status": payout.status, "reference": payout.payment_reference}


@router.post("/admin/payouts/{payout_id}/approve")
def approve_payout_automated(
    payout_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_admin_role(AdminRole.DIR_ADMIN, AdminRole.MANAGEMENT)),
):
    """Approve and automatically process a vendor payout via Paystack Transfer Engine.

    Creates a transfer recipient if needed, initiates bank transfer,
    deducts from locked_escrow_balance on success, flags status to SUCCESSFUL.
    """
    from app.models import PayoutRequest, VendorWallet, VendorWalletTransaction, Retailer

    payout = db.query(PayoutRequest).filter(PayoutRequest.id == payout_id).first()
    if not payout:
        raise HTTPException(status_code=404, detail="Payout request not found")
    if payout.status not in ("PENDING", "APPROVED"):
        raise HTTPException(status_code=400, detail=f"Payout already {payout.status}")

    if not payout.account_number or not payout.bank_code:
        raise HTTPException(status_code=400, detail="Vendor bank details incomplete")

    payout.status = "APPROVED"
    payout.processed_by = admin.id
    payout.processed_at = utcnow()
    db.commit()

    # Attempt automated bank transfer
    from app.services.payment_provider import get_bank_transfer_engine
    engine = get_bank_transfer_engine()

    if engine:
        import uuid as _uuid
        ref = f"PAYOUT-{_uuid.uuid4().hex[:12].upper()}"
        payout.payment_reference = ref

        retailer = db.query(Retailer).filter(Retailer.id == payout.retailer_id).first()
        recipient_name = payout.account_name or (retailer.name if retailer else "Vendor")

        # Step A: Create transfer recipient
        recipient_result = engine.create_transfer_recipient(
            name=recipient_name,
            bank_code=payout.bank_code,
            account_number=payout.account_number,
        )

        if recipient_result.get("success"):
            # Step B: Initiate transfer
            transfer_result = engine.initiate_transfer(
                recipient_code=recipient_result["recipient_code"],
                amount=payout.amount,
                reason=f"Vendor payout — {recipient_name}",
            )
            if transfer_result.get("success"):
                payout.status = "SUCCESSFUL"
            else:
                payout.status = "FAILED"
                payout.failure_reason = transfer_result.get("message", "Transfer failed")
        else:
            payout.status = "FAILED"
            payout.failure_reason = recipient_result.get("message", "Recipient creation failed")
    else:
        # No Paystack configured — mark as manual processing
        payout.status = "SUCCESSFUL"

    # On success: deduct from locked_escrow_balance
    wallet = db.query(VendorWallet).filter(VendorWallet.retailer_id == payout.retailer_id).first()
    if payout.status == "SUCCESSFUL" and wallet:
        wallet.locked_escrow_balance -= payout.amount
        tx = VendorWalletTransaction(
            wallet_id=wallet.id,
            transaction_type="withdrawal",
            amount=-payout.amount,
            balance_before=wallet.balance,
            balance_after=wallet.balance,
            reference=payout.payment_reference or "",
            description=f"Payout processed — ₦{payout.amount:.2f} transferred",
            status="COMPLETED",
        )
        db.add(tx)

    db.commit()
    log_admin_action(db, admin, "approve_payout", "payout", payout_id,
                     f"Approved payout ₦{payout.amount:.2f} — status: {payout.status}")

    # Send email + SMS notification
    if payout.status == "SUCCESSFUL" and payout.retailer_id:
        try:
            from app.core.email import dispatch_email_background
            from app.services.email_service import _render_email_template, _base_context
            r_admin = db.query(AdminUser).filter(
                AdminUser.vendor_id == payout.retailer_id,
                AdminUser.role == AdminRole.RETAILER,
            ).first()
            if r_admin and r_admin.email:
                r_name = (retailer.name if retailer else r_admin.name) or "Vendor"
                html = _render_email_template("payout_processed.html", _base_context(
                    heading="Payout Processed!",
                    subtitle=f"₦{payout.amount:,.2f} paid",
                    body_html=f"<p>Hi <strong>{r_name}</strong>, your payout has been processed.</p>",
                    amount=payout.amount,
                    earning_count=1,
                    customer_name=r_name,
                ))
                background_tasks.add_task(dispatch_email_background, r_admin.email, "Payout Processed — ForgeStore", html)
        except Exception:
            pass

        # WhatsApp notification
        try:
            from app.core.notifications import send_payout_whatsapp
            if retailer and retailer.phone:
                import asyncio
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(send_payout_whatsapp(retailer.phone, payout.amount, payout.status))
                except RuntimeError:
                    pass
        except Exception:
            pass

    return {"success": True, "status": payout.status, "reference": payout.payment_reference}


