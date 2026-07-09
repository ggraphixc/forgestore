"""Vendor Portal — isolated router for RETAILER role users."""
from fastapi import APIRouter, Depends, Request, Form, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from datetime import timedelta
import uuid
import csv
import io
import asyncio

from app.database import get_db
from app.models import (
    AdminUser, Product, Category, Retailer, Order, OrderItem,
    VendorAnalytics, VendorPayout, VendorActivityLog, OrderEarning,
    AdCampaign, PromoAd, AdminRole, VendorWallet, VendorWalletTransaction,
    PayoutRequest, Settings, VendorNotification
)
from app.auth import get_current_user_from_cookie, has_permission, AdminRole as AR, log_admin_action, hash_password, verify_password
from app.templates_shared import render_template
from app.utils import utcnow
import json, os
from app.core.image_compressor import compress_image

router = APIRouter(tags=["vendor-portal"])


def get_role_badge(role):
    badges = {
        "DIR_ADMIN": "bg-purple-100 text-purple-800 border-purple-200",
        "MANAGEMENT": "bg-blue-100 text-blue-800 border-blue-200",
        "TECH_ADMIN": "bg-cyan-100 text-cyan-800 border-cyan-200",
        "RETAILER": "bg-amber-100 text-amber-800 border-amber-200",
        "LOGISTICS": "bg-emerald-100 text-emerald-800 border-emerald-200",
    }
    return badges.get(role, "bg-stone-100 text-stone-800 border-stone-200")


def _require_retailer(request: Request, db: Session):
    """Verify the current user has RETAILER role and return admin + retailer."""
    admin = get_current_user_from_cookie(request, db)
    if not admin:
        return None, None, RedirectResponse(url="/admin/login", status_code=302)
    role_val = admin.role.value if hasattr(admin.role, 'value') else admin.role
    if role_val != "RETAILER" and role_val != AR.RETAILER.value:
        if role_val == "LOGISTICS":
            return admin, None, RedirectResponse(url="/logistics/dashboard", status_code=302)
        return admin, None, RedirectResponse(url="/admin/dashboard", status_code=302)
    retailer = None
    if admin.vendor_id:
        retailer = db.query(Retailer).filter(Retailer.id == admin.vendor_id).first()
    return admin, retailer, None


@router.get("/vendor/apply", response_class=HTMLResponse)
def vendor_apply_page(request: Request, db: Session = Depends(get_db)):
    """Public page for vendor applications."""
    from app.config import get_site_settings
    site_settings = get_site_settings(db)
    return render_template("web/apply-vendor.html", {
        "request": request,
        "settings": site_settings,
    })


@router.get("/vendor/dashboard", response_class=HTMLResponse)
def vendor_dashboard(request: Request, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return redirect

    total_products = 0
    total_orders = 0
    total_revenue = 0.0
    recent_orders = []
    low_stock_count = 0
    low_stock_items = []

    if retailer:
        total_products = db.query(func.count(Product.id)).filter(Product.retailer_id == retailer.id).scalar() or 0
        order_ids = [oi.order_id for oi in db.query(OrderItem).join(Product).filter(Product.retailer_id == retailer.id).all()]
        if order_ids:
            total_orders = db.query(func.count(Order.id)).filter(Order.id.in_(order_ids)).scalar() or 0
            total_revenue = db.query(func.coalesce(func.sum(Order.total_amount), 0)).filter(Order.id.in_(order_ids)).scalar() or 0
            recent_orders = db.query(Order).filter(Order.id.in_(order_ids)).order_by(desc(Order.created_at)).limit(5).all()

        # Low-stock check
        from app.models import Settings as SettingsModel
        threshold_setting = db.query(SettingsModel).filter(SettingsModel.key == "low_stock_limit").first()
        try:
            threshold_value = int(threshold_setting.value) if threshold_setting else 5
        except (ValueError, TypeError):
            threshold_value = 5

        low_stock_items = db.query(Product).filter(
            Product.retailer_id == retailer.id,
            Product.inventory <= threshold_value,
        ).all()
        low_stock_count = len(low_stock_items)

    return render_template("vendor/dashboard.html", {
        "request": request,
        "admin": admin,
        "retailer": retailer,
        "total_products": total_products,
        "total_orders": total_orders,
        "total_revenue": float(total_revenue),
        "recent_orders": recent_orders,
        "low_stock_count": low_stock_count,
        "low_stock_items": low_stock_items[:5],
        "has_permission": has_permission,
    })


@router.get("/vendor/products", response_class=HTMLResponse)
def vendor_products(request: Request, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return redirect

    products = []
    if retailer:
        products = db.query(Product).filter(Product.retailer_id == retailer.id).order_by(desc(Product.created_at)).all()
    categories = {c.id: c.name for c in db.query(Category).all()}

    return render_template("vendor/products.html", {
        "request": request,
        "admin": admin,
        "retailer": retailer,
        "products": products,
        "categories": categories,
        "has_permission": has_permission,
    })


@router.get("/vendor/orders", response_class=HTMLResponse)
def vendor_orders(request: Request, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return redirect

    orders = []
    customers = {}
    if retailer:
        order_ids = list({oi.order_id for oi in db.query(OrderItem).join(Product).filter(Product.retailer_id == retailer.id).all()})
        if order_ids:
            orders = db.query(Order).filter(Order.id.in_(order_ids)).order_by(desc(Order.created_at)).all()
            for o in orders:
                user = db.query(func.count()).select_from(Order).join(OrderItem).filter(
                    OrderItem.order_id == o.id, OrderItem.product.has(retailer_id=retailer.id)
                ).scalar()
                customer = db.query(AdminUser.id).filter(AdminUser.id == o.customer_id).first() if False else None
                from app.models import User
                cust = db.query(User).filter(User.id == o.customer_id).first()
                customers[o.id] = cust.name if cust else "Unknown"

    return render_template("vendor/orders.html", {
        "request": request,
        "admin": admin,
        "retailer": retailer,
        "orders": orders,
        "customers": customers,
        "has_permission": has_permission,
    })


@router.get("/vendor/earnings", response_class=HTMLResponse)
def vendor_earnings(request: Request, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return redirect

    earnings = []
    total_net = 0.0
    if retailer:
        earnings = db.query(OrderEarning).filter(
            OrderEarning.retailer_id == retailer.id
        ).order_by(desc(OrderEarning.created_at)).limit(100).all()
        total_net = sum(e.net_amount for e in earnings)

    return render_template("vendor/earnings.html", {
        "request": request,
        "admin": admin,
        "retailer": retailer,
        "earnings": earnings,
        "total_net": total_net,
        "has_permission": has_permission,
    })


@router.get("/vendor/analytics", response_class=HTMLResponse)
def vendor_analytics(request: Request, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return redirect

    analytics = []
    if retailer:
        analytics = db.query(VendorAnalytics).filter(
            VendorAnalytics.retailer_id == retailer.id
        ).order_by(desc(VendorAnalytics.period_start)).limit(30).all()

    return render_template("vendor/analytics.html", {
        "request": request,
        "admin": admin,
        "retailer": retailer,
        "analytics": analytics,
        "has_permission": has_permission,
    })


# ── Vendor Payout Request ──

@router.post("/api/vendor/payout/request")
def vendor_payout_request(
    data: dict,
    request: Request,
    db: Session = Depends(get_db),
):
    """Vendor requests payout of available earnings balance.

    Locks the requested amount from the vendor wallet into escrow.
    """
    admin = get_current_user_from_cookie(request, db)
    if not admin:
        raise HTTPException(status_code=401, detail="Not authenticated")
    role_val = admin.role.value if hasattr(admin.role, 'value') else admin.role
    if role_val != "RETAILER" and role_val != AR.RETAILER.value:
        raise HTTPException(status_code=403, detail="Only vendors can request payouts")
    if not admin.vendor_id:
        raise HTTPException(status_code=400, detail="No vendor profile linked")

    amount = float(data.get("amount", 0))
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")

    # Get vendor wallet
    wallet = db.query(VendorWallet).filter(VendorWallet.retailer_id == admin.vendor_id).first()
    if not wallet:
        raise HTTPException(status_code=400, detail="Vendor wallet not found")
    if wallet.balance < amount:
        raise HTTPException(status_code=400, detail=f"Insufficient balance. Available: ₦{wallet.balance:.2f}")

    # Lock amount: deduct from balance, move to locked_escrow_balance
    balance_before = wallet.balance
    wallet.balance -= amount
    wallet.locked_escrow_balance += amount

    # Create wallet transaction
    tx = VendorWalletTransaction(
        wallet_id=wallet.id,
        transaction_type="withdrawal",
        amount=-amount,
        balance_before=balance_before,
        balance_after=wallet.balance,
        reference=f"PAYOUT-{uuid.uuid4().hex[:12].upper()}",
        description=f"Payout request for ₦{amount:.2f}",
        status="PENDING",
    )
    db.add(tx)

    # Get bank details from retailer or request
    retailer = db.query(Retailer).filter(Retailer.id == admin.vendor_id).first()
    bank_name = data.get("bank_name") or (retailer.bank_name if retailer else "")
    account_number = data.get("account_number") or (retailer.account_number if retailer else "")
    bank_code = data.get("bank_code") or (retailer.bank_code if retailer else "")
    account_name = data.get("account_name") or (retailer.account_name if retailer else "")

    payout = PayoutRequest(
        retailer_id=admin.vendor_id,
        amount=amount,
        locked_amount=amount,
        status="PENDING",
        bank_name=bank_name,
        account_number=account_number,
        bank_code=bank_code,
        account_name=account_name,
    )
    db.add(payout)
    db.commit()
    db.refresh(payout)

    log_admin_action(db, admin, "payout_request", "payout", payout.id,
                     f"Vendor requested payout of ₦{amount:.2f}")

    return {"success": True, "payout_id": payout.id, "locked": amount, "remaining_balance": wallet.balance}


# ── Bulk CSV Product Import ──

@router.post("/api/vendor/products/bulk-import")
async def vendor_bulk_import_products(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Bulk import products from CSV file. All items assigned to the authenticated vendor."""
    admin = get_current_user_from_cookie(request, db)
    if not admin:
        raise HTTPException(status_code=401, detail="Not authenticated")
    role_val = admin.role.value if hasattr(admin.role, 'value') else admin.role
    if role_val != "RETAILER" and role_val != AR.RETAILER.value:
        raise HTTPException(status_code=403, detail="Only vendors can import products")
    if not admin.vendor_id:
        raise HTTPException(status_code=400, detail="No vendor profile linked")

    # Validate file type
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only .csv files are accepted")

    content = await file.read()
    try:
        decoded = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            decoded = content.decode("latin-1")
        except UnicodeDecodeError:
            raise HTTPException(status_code=400, detail="Could not decode CSV file")

    reader = csv.DictReader(io.StringIO(decoded))
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV file has no headers")

    # Normalize column names
    normalized = {f.strip().lower(): f.strip() for f in reader.fieldnames}

    # Map required columns
    name_key = normalized.get("name")
    price_key = normalized.get("price")
    if not name_key or not price_key:
        raise HTTPException(status_code=400, detail="CSV must have 'name' and 'price' columns")

    desc_key = normalized.get("description")
    stock_key = normalized.get("stock_quantity") or normalized.get("inventory")
    sku_key = normalized.get("sku")
    cat_key = normalized.get("category")

    # Get or resolve category map
    categories = {c.name.lower(): c.id for c in db.query(Category).all()}

    created = 0
    errors = []
    retailer = db.query(Retailer).filter(Retailer.id == admin.vendor_id).first()

    for row_idx, row in enumerate(reader, start=2):
        try:
            name = (row.get(name_key) or "").strip()
            price_str = (row.get(price_key) or "0").strip().replace(",", "")

            if not name:
                errors.append({"row": row_idx, "error": "Missing product name"})
                continue

            try:
                price = float(price_str)
            except ValueError:
                errors.append({"row": row_idx, "error": f"Invalid price: {price_str}"})
                continue

            if price <= 0:
                errors.append({"row": row_idx, "error": f"Price must be positive: {price}"})
                continue

            # Parse stock/inventory
            inventory = 0
            if stock_key:
                try:
                    inventory = max(0, int(float((row.get(stock_key) or "0").strip())))
                except ValueError:
                    pass

            # Resolve category
            category_id = None
            if cat_key:
                cat_name = (row.get(cat_key) or "").strip().lower()
                if cat_name:
                    category_id = categories.get(cat_name)

            # Generate slug
            slug = name.lower().replace(" ", "-").replace("'", "")
            slug = ''.join(c for c in slug if c.isalnum() or c == '-')[:80]
            # Ensure uniqueness
            existing_slug = db.query(Product).filter(Product.slug == slug).first()
            if existing_slug:
                slug = f"{slug}-{uuid.uuid4().hex[:6]}"

            product = Product(
                name=name,
                slug=slug,
                description=(row.get(desc_key) or "").strip() if desc_key else "",
                price=price,
                inventory=inventory,
                retailer_id=admin.vendor_id,
                images=["/static/img/placeholder.svg"],
                category_id=category_id,
                brand=retailer.name if retailer else "",
            )
            db.add(product)
            created += 1

        except Exception as e:
            errors.append({"row": row_idx, "error": str(e)[:200]})

    db.commit()

    log_admin_action(db, admin, "bulk_import", "product", "",
                     f"Bulk imported {created} products ({len(errors)} errors)")

    return {
        "success": True,
        "created": created,
        "errors": len(errors),
        "error_details": errors[:50],
        "total_rows": created + len(errors),
    }


# ── Vendor Notifications ──

@router.get("/api/vendor/notifications")
def vendor_notifications(
    request: Request,
    db: Session = Depends(get_db),
):
    """Get vendor notifications — low-stock alerts, order alerts, etc."""
    admin = get_current_user_from_cookie(request, db)
    if not admin:
        raise HTTPException(status_code=401, detail="Not authenticated")
    role_val = admin.role.value if hasattr(admin.role, 'value') else admin.role
    if role_val != "RETAILER" and role_val != AR.RETAILER.value:
        raise HTTPException(status_code=403, detail="Only vendors can access notifications")
    if not admin.vendor_id:
        return {"notifications": [], "unread_count": 0}

    notifications = db.query(VendorNotification).filter(
        VendorNotification.retailer_id == admin.vendor_id
    ).order_by(desc(VendorNotification.created_at)).limit(50).all()

    unread_count = db.query(func.count(VendorNotification.id)).filter(
        VendorNotification.retailer_id == admin.vendor_id,
        VendorNotification.is_read == False,
    ).scalar() or 0

    return {
        "notifications": [
            {
                "id": n.id,
                "message": n.message_text,
                "severity": n.severity_level,
                "type": n.notification_type,
                "is_read": n.is_read,
                "product_id": n.related_product_id,
                "created_at": n.created_at.isoformat() if n.created_at else None,
            }
            for n in notifications
        ],
        "unread_count": unread_count,
    }


# ── Low-Stock Alerts ──

@router.get("/api/vendor/alerts/low-stock")
def vendor_low_stock_alerts(
    request: Request,
    db: Session = Depends(get_db),
):
    """Get products at or below the low-stock threshold for this vendor."""
    admin = get_current_user_from_cookie(request, db)
    if not admin:
        raise HTTPException(status_code=401, detail="Not authenticated")
    role_val = admin.role.value if hasattr(admin.role, 'value') else admin.role
    if role_val != "RETAILER" and role_val != AR.RETAILER.value:
        raise HTTPException(status_code=403, detail="Only vendors can access low-stock alerts")
    if not admin.vendor_id:
        raise HTTPException(status_code=400, detail="No vendor profile linked")

    from app.models import Settings as SettingsModel
    threshold_setting = db.query(SettingsModel).filter(SettingsModel.key == "low_stock_limit").first()
    try:
        threshold_value = int(threshold_setting.value) if threshold_setting else 5
    except (ValueError, TypeError):
        threshold_value = 5

    low_stock_items = db.query(Product).filter(
        Product.retailer_id == admin.vendor_id,
        Product.inventory <= threshold_value,
    ).all()

    return {
        "threshold_evaluated": threshold_value,
        "count": len(low_stock_items),
        "items": [
            {
                "id": p.id,
                "name": p.name,
                "slug": p.slug,
                "current_stock": p.inventory,
                "price": p.price,
            }
            for p in low_stock_items
        ],
    }


@router.post("/api/vendor/notifications/{notif_id}/read")
def vendor_mark_notification_read(
    notif_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Mark a vendor notification as read."""
    admin = get_current_user_from_cookie(request, db)
    if not admin:
        raise HTTPException(status_code=401, detail="Not authenticated")

    notif = db.query(VendorNotification).filter(VendorNotification.id == notif_id).first()
    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found")

    # Ensure vendor owns this notification
    if admin.vendor_id and notif.retailer_id != admin.vendor_id:
        raise HTTPException(status_code=403, detail="Not your notification")

    notif.is_read = True
    db.commit()
    return {"success": True}


@router.post("/api/vendor/notifications/read-all")
def vendor_mark_all_notifications_read(
    request: Request,
    db: Session = Depends(get_db),
):
    """Mark all vendor notifications as read."""
    admin = get_current_user_from_cookie(request, db)
    if not admin:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if not admin.vendor_id:
        return {"success": True, "marked": 0}

    updated = db.query(VendorNotification).filter(
        VendorNotification.retailer_id == admin.vendor_id,
        VendorNotification.is_read == False,
    ).update({"is_read": True})
    db.commit()

    return {"success": True, "marked": updated}


# ── Vendor Payout Request (Bank Transfer) ──

@router.post("/api/vendor/payouts/request")
def vendor_request_payout(
    data: dict,
    request: Request,
    db: Session = Depends(get_db),
):
    """Request payout of cleared wallet balance to verified bank account.

    Validates available balance (balance - locked_escrow_balance) is sufficient.
    Deducts from balance, locks into escrow, creates PayoutRequest record.
    """
    admin = get_current_user_from_cookie(request, db)
    if not admin:
        raise HTTPException(status_code=401, detail="Not authenticated")
    role_val = admin.role.value if hasattr(admin.role, 'value') else admin.role
    if role_val != "RETAILER" and role_val != AR.RETAILER.value:
        raise HTTPException(status_code=403, detail="Only vendors can request payouts")
    if not admin.vendor_id:
        raise HTTPException(status_code=400, detail="No vendor profile linked")

    amount = float(data.get("amount", 0))
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")

    wallet = db.query(VendorWallet).filter(VendorWallet.retailer_id == admin.vendor_id).first()
    if not wallet:
        raise HTTPException(status_code=400, detail="Vendor wallet not found")

    accessible = wallet.balance - wallet.locked_escrow_balance
    if amount > accessible:
        raise HTTPException(status_code=400, detail=f"Insufficient accessible balance. Available: ₦{accessible:.2f}")

    # Get bank details
    retailer = db.query(Retailer).filter(Retailer.id == admin.vendor_id).first()
    bank_name = data.get("bank_name") or (retailer.bank_name if retailer else "")
    account_number = data.get("account_number") or (retailer.account_number if retailer else "")
    bank_code = data.get("bank_code") or (retailer.bank_code if retailer else "")
    account_name = data.get("account_name") or (retailer.account_name if retailer else "")

    if not account_number or not bank_code:
        raise HTTPException(status_code=400, detail="Bank account number and bank code are required")

    # Lock funds
    balance_before = wallet.balance
    wallet.balance -= amount
    wallet.locked_escrow_balance += amount

    tx = VendorWalletTransaction(
        wallet_id=wallet.id,
        transaction_type="withdrawal",
        amount=-amount,
        balance_before=balance_before,
        balance_after=wallet.balance,
        reference=f"PAYOUT-{uuid.uuid4().hex[:12].upper()}",
        description=f"Payout request for ₦{amount:.2f}",
        status="PENDING",
    )
    db.add(tx)

    payout = PayoutRequest(
        retailer_id=admin.vendor_id,
        amount=amount,
        locked_amount=amount,
        status="PENDING",
        bank_name=bank_name,
        account_number=account_number,
        bank_code=bank_code,
        account_name=account_name,
    )
    db.add(payout)
    db.commit()
    db.refresh(payout)

    log_admin_action(db, admin, "payout_request", "payout", payout.id,
                     f"Vendor requested payout of ₦{amount:.2f}")

    return {"success": True, "payout_id": payout.id, "locked": amount, "remaining_balance": wallet.balance}


# ── Vendor Self-Service Ad Campaign Launch ──

@router.post("/api/vendor/ads/launch")
def vendor_launch_ad_campaign(
    data: dict,
    request: Request,
    db: Session = Depends(get_db),
):
    """Launch a self-service ad campaign for a vendor's product.

    Expects: product_id, ad_type (PRODUCT/SHOP), banner_url, start_date, end_date, budget.
    Deducts budget from vendor wallet, creates PENDING_REVIEW AdCampaign.
    """
    admin = get_current_user_from_cookie(request, db)
    if not admin:
        raise HTTPException(status_code=401, detail="Not authenticated")
    role_val = admin.role.value if hasattr(admin.role, 'value') else admin.role
    if role_val != "RETAILER" and role_val != AR.RETAILER.value:
        raise HTTPException(status_code=403, detail="Only vendors can launch ad campaigns")
    if not admin.vendor_id:
        raise HTTPException(status_code=400, detail="No vendor profile linked")

    product_id = data.get("product_id")
    ad_type = data.get("ad_type", "PRODUCT")
    banner_url = data.get("banner_url", "")
    start_date_str = data.get("start_date")
    end_date_str = data.get("end_date")
    budget = float(data.get("budget", 0))
    ad_subtype = data.get("ad_subtype")
    banner_type = data.get("banner_type", "banner")
    note = data.get("note", "")

    if not banner_url:
        raise HTTPException(status_code=400, detail="banner_url is required")
    if budget <= 0:
        raise HTTPException(status_code=400, detail="Budget must be positive")

    # Validate product ownership if PRODUCT ad
    if ad_type == "PRODUCT" and product_id:
        product = db.query(Product).filter(
            Product.id == product_id,
            Product.retailer_id == admin.vendor_id,
        ).first()
        if not product:
            raise HTTPException(status_code=404, detail="Product not found or not owned by you")

    # Check wallet balance
    wallet = db.query(VendorWallet).filter(VendorWallet.retailer_id == admin.vendor_id).first()
    if not wallet:
        raise HTTPException(status_code=400, detail="Vendor wallet not found")
    if wallet.balance < budget:
        raise HTTPException(status_code=400, detail=f"Insufficient wallet balance. Required: ₦{budget:.2f}, Available: ₦{wallet.balance:.2f}")

    # Deduct budget from wallet
    balance_before = wallet.balance
    wallet.balance -= budget

    tx = VendorWalletTransaction(
        wallet_id=wallet.id,
        transaction_type="fee",
        amount=-budget,
        balance_before=balance_before,
        balance_after=wallet.balance,
        reference=f"AD-{uuid.uuid4().hex[:12].upper()}",
        description=f"Ad campaign budget for {ad_type} ad",
        status="COMPLETED",
    )
    db.add(tx)

    # Parse dates
    from datetime import datetime as _dt
    start_date = None
    end_date = None
    if start_date_str:
        try:
            start_date = _dt.fromisoformat(start_date_str.replace("Z", "+00:00")).replace(tzinfo=None)
        except (ValueError, AttributeError):
            pass
    if end_date_str:
        try:
            end_date = _dt.fromisoformat(end_date_str.replace("Z", "+00:00")).replace(tzinfo=None)
        except (ValueError, AttributeError):
            pass

    import uuid as _uuid
    ref = f"ADV-{_uuid.uuid4().hex[:12].upper()}"

    campaign = AdCampaign(
        retailer_id=admin.vendor_id,
        product_id=product_id if ad_type == "PRODUCT" else None,
        ad_type=ad_type,
        status="PENDING",
        banner_url=banner_url,
        start_date=start_date or utcnow(),
        end_date=end_date,
        payment_reference=ref,
        ad_subtype=ad_subtype,
        banner_type=banner_type,
        note=note,
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)

    log_admin_action(db, admin, "launch_ad_campaign", "ad_campaign", campaign.id,
                     f"Vendor launched {ad_type} ad campaign (budget: ₦{budget:.2f})")

    return {
        "success": True,
        "campaign_id": campaign.id,
        "status": "PENDING",
        "budget_deducted": budget,
        "remaining_balance": wallet.balance,
    }


@router.get("/vendor/ads", response_class=HTMLResponse)
def vendor_ads_page(request: Request, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return redirect

    campaigns = []
    promos = []
    products = []
    if retailer:
        campaigns = db.query(AdCampaign).filter(
            AdCampaign.retailer_id == retailer.id
        ).order_by(desc(AdCampaign.created_at)).all()
        promos = db.query(PromoAd).filter(
            PromoAd.retailer_id == retailer.id
        ).order_by(desc(PromoAd.created_at)).all()
        products = db.query(Product).filter(
            Product.retailer_id == retailer.id,
        ).all()

    def _campaign_dict(c):
        return {
            "id": c.id, "ad_type": c.ad_type, "status": c.status,
            "clicks": c.clicks or 0, "impressions": c.impressions or 0,
            "banner_url": c.banner_url, "target_url": c.target_url,
            "ad_subtype": c.ad_subtype, "banner_type": c.banner_type,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "product_id": c.product_id, "retailer_id": c.retailer_id,
        }
    def _promo_dict(p):
        return {
            "id": p.id, "title": p.title, "ad_subtype": p.ad_subtype,
            "banner_type": p.banner_type, "banner_url": p.banner_url,
            "target_url": p.target_url, "status": p.status,
            "start_date": p.start_date.isoformat() if p.start_date else None,
            "end_date": p.end_date.isoformat() if p.end_date else None,
            "note": p.note, "retailer_id": p.retailer_id,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        }

    return render_template("vendor/ads.html", {
        "request": request,
        "admin": admin,
        "retailer": retailer,
        "campaigns": [_campaign_dict(c) for c in campaigns],
        "promos": [_promo_dict(p) for p in promos],
        "products": [{"id": p.id, "name": p.name, "image": (p.images[0] if p.images else "")} for p in products],
        "has_permission": has_permission,
    })


@router.get("/vendor/support", response_class=HTMLResponse)
def vendor_support(request: Request, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return redirect
    return render_template("vendor/support.html", {
        "request": request, "admin": admin, "retailer": retailer,
        "has_permission": has_permission,
    })


@router.get("/vendor/notifications", response_class=HTMLResponse)
def vendor_notifications(request: Request, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return redirect
    return render_template("vendor/notifications.html", {
        "request": request, "admin": admin, "retailer": retailer,
        "has_permission": has_permission,
    })


# ─── Vendor Product Routes ───────────────────────────────────────────────

@router.get("/vendor/products/new", response_class=HTMLResponse)
def vendor_product_new(request: Request, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return redirect
    categories = db.query(Category).all()
    return render_template("vendor/product_form.html", {
        "request": request, "admin": admin, "retailer": retailer,
        "categories": categories, "product": None,
        "has_permission": has_permission,
    })


@router.post("/vendor/products/new")
async def vendor_product_create(request: Request, db: Session = Depends(get_db),
                                files: list[UploadFile] = File(None)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return redirect

    form = await request.form()
    slug = form.get("slug", "")
    if not slug:
        slug = form.get("name", "unknown-product").lower().replace(" ", "-")

    name = form.get("name", "Unnamed Product")
    try:
        price = float(form.get("price", "0").replace(",", ""))
    except ValueError:
        price = 0.0
    discount_price = None
    ds = form.get("discount_price", "")
    if ds:
        try:
            discount_price = float(ds.replace(",", ""))
        except ValueError:
            pass
    try:
        inventory = int(form.get("inventory", "0"))
    except ValueError:
        inventory = 0

    images_json = form.get("images", "[]")
    try:
        images = json.loads(images_json)
    except (json.JSONDecodeError, TypeError):
        images = []

    if files:
        from app.core.cloudinary_upload import is_cloudinary_configured, upload_to_cloudinary
        use_cloudinary = is_cloudinary_configured()
        upload_dir = os.path.join("app", "static", "uploads", "products")
        os.makedirs(upload_dir, exist_ok=True)
        for file in files:
            raw = await file.read()
            if use_cloudinary:
                url = upload_to_cloudinary(raw, folder="forgestore/products")
                if url:
                    images.append(url)
                    continue
            compressed, ext = compress_image(raw)
            unique_name = f"{int(utcnow().timestamp())}-{uuid.uuid4().hex[:8]}.{ext}"
            file_path = os.path.join(upload_dir, unique_name)
            with open(file_path, "wb") as f:
                f.write(compressed)
            images.append(f"/static/uploads/products/{unique_name}")

    product = Product(
        name=name, slug=slug, brand=form.get("brand"),
        description=form.get("description"), price=price,
        discount_price=discount_price, images=images,
        category_id=form.get("category_id"),
        retailer_id=admin.vendor_id, inventory=inventory,
        is_new_arrival=form.get("is_new_arrival") == "true",
        is_flagship=form.get("is_flagship") == "true",
        specifications=json.loads(form.get("specifications") or "{}"),
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    log_admin_action(db, admin, "create", "product", product.id, f"Created product '{product.name}'")
    return RedirectResponse(url=f"/vendor/products/{product.id}", status_code=302)


@router.get("/vendor/products/{product_id}", response_class=HTMLResponse)
def vendor_product_detail(request: Request, product_id: str, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return redirect
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product or product.retailer_id != admin.vendor_id:
        return RedirectResponse(url="/vendor/products", status_code=302)
    return render_template("vendor/product_detail.html", {
        "request": request, "admin": admin, "retailer": retailer,
        "product": product, "has_permission": has_permission,
    })


@router.get("/vendor/products/{product_id}/edit", response_class=HTMLResponse)
def vendor_product_edit(request: Request, product_id: str, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return redirect
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product or product.retailer_id != admin.vendor_id:
        return RedirectResponse(url="/vendor/products", status_code=302)
    categories = db.query(Category).all()
    return render_template("vendor/product_form.html", {
        "request": request, "admin": admin, "retailer": retailer,
        "categories": categories, "product": product,
        "has_permission": has_permission,
    })


@router.post("/vendor/products/{product_id}/edit")
async def vendor_product_update(request: Request, product_id: str,
                                db: Session = Depends(get_db),
                                files: list[UploadFile] = File(None)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return redirect
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product or product.retailer_id != admin.vendor_id:
        return RedirectResponse(url="/vendor/products", status_code=302)

    form = await request.form()
    product.name = form.get("name", product.name)
    product.slug = form.get("slug", product.slug)
    product.brand = form.get("brand", product.brand)
    product.description = form.get("description", product.description)
    try:
        product.price = float(form.get("price", str(product.price)).replace(",", ""))
    except ValueError:
        pass
    ds = form.get("discount_price", "")
    if ds:
        try:
            product.discount_price = float(ds.replace(",", ""))
        except ValueError:
            pass
    try:
        product.inventory = int(form.get("inventory", str(product.inventory)))
    except ValueError:
        pass
    product.category_id = form.get("category_id", product.category_id)
    product.is_new_arrival = form.get("is_new_arrival") == "true"
    product.is_flagship = form.get("is_flagship") == "true"
    specs_raw = form.get("specifications")
    if specs_raw:
        try:
            product.specifications = json.loads(specs_raw)
        except (json.JSONDecodeError, TypeError):
            pass

    images_json = form.get("images", None)
    if images_json is not None:
        try:
            product.images = json.loads(images_json)
        except (json.JSONDecodeError, TypeError):
            pass

    if files:
        from app.core.cloudinary_upload import is_cloudinary_configured, upload_to_cloudinary
        use_cloudinary = is_cloudinary_configured()
        upload_dir = os.path.join("app", "static", "uploads", "products")
        os.makedirs(upload_dir, exist_ok=True)
        existing = product.images or []
        for file in files:
            raw = await file.read()
            if use_cloudinary:
                url = upload_to_cloudinary(raw, folder="forgestore/products")
                if url:
                    existing.append(url)
                    continue
            compressed, ext = compress_image(raw)
            unique_name = f"{int(utcnow().timestamp())}-{uuid.uuid4().hex[:8]}.{ext}"
            file_path = os.path.join(upload_dir, unique_name)
            with open(file_path, "wb") as f:
                f.write(compressed)
            existing.append(f"/static/uploads/products/{unique_name}")
        product.images = existing

    db.commit()
    log_admin_action(db, admin, "update", "product", product.id, f"Updated product '{product.name}'")
    return RedirectResponse(url=f"/vendor/products/{product.id}", status_code=302)


# ─── Vendor Profile ──────────────────────────────────────────────────────

@router.get("/vendor/me", response_class=HTMLResponse)
def vendor_profile(request: Request, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return redirect
    product_count = db.query(func.count(Product.id)).filter(
        Product.retailer_id == admin.vendor_id
    ).scalar() if admin.vendor_id else 0
    days_active = (utcnow() - admin.created_at).days if admin.created_at else 0
    return render_template("vendor/profile.html", {
        "request": request, "admin": admin, "retailer": retailer,
        "product_count": product_count, "days_active": days_active,
        "get_role_badge": get_role_badge, "has_permission": has_permission,
        "success": request.query_params.get("success"), "error": None,
    })


@router.post("/vendor/me")
async def vendor_profile_update(request: Request, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return redirect
    form = await request.form()
    name = form.get("name", "").strip()
    current_password = form.get("current_password", "")
    new_password = form.get("new_password", "")
    confirm_password = form.get("confirm_password", "")

    product_count = db.query(func.count(Product.id)).filter(
        Product.retailer_id == admin.vendor_id
    ).scalar() if admin.vendor_id else 0
    days_active = (utcnow() - admin.created_at).days if admin.created_at else 0

    ctx = {
        "request": request, "admin": admin, "retailer": retailer,
        "product_count": product_count, "days_active": days_active,
        "get_role_badge": get_role_badge, "has_permission": has_permission,
        "success": None, "error": None,
    }

    if name and name != admin.name:
        admin.name = name
    if new_password:
        if not current_password:
            ctx["error"] = "Please enter your current password to set a new one."
            return render_template("vendor/profile.html", ctx)
        if not verify_password(current_password, admin.password):
            ctx["error"] = "Current password is incorrect."
            return render_template("vendor/profile.html", ctx)
        if len(new_password) < 6:
            ctx["error"] = "New password must be at least 6 characters."
            return render_template("vendor/profile.html", ctx)
        if new_password != confirm_password:
            ctx["error"] = "New passwords do not match."
            return render_template("vendor/profile.html", ctx)
        admin.password = hash_password(new_password)

    db.commit()
    return RedirectResponse(url="/vendor/me?success=Profile+updated+successfully.", status_code=302)


# ─── VENDOR AI TOOLS API ──────────────────────────────────────────────

@router.post("/api/vendor/ai/generate-description")
async def vendor_ai_generate_description(request: Request, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return JSONResponse({"success": False, "message": "Unauthorized"}, status_code=401)
    from app.services.ai_service import generate_product_description
    data = await request.json()
    images = data.get("images", [])
    description = await asyncio.to_thread(
        generate_product_description,
        product_name=data.get("name", ""),
        category=data.get("category", ""),
        brand=data.get("brand", ""),
        keywords=data.get("keywords", ""),
        tone=data.get("tone", "professional"),
        images=images if images else None,
    )
    if description:
        log_admin_action(db, admin, "ai_generate", "description", "", f"Generated description for '{data.get('name')}'")
        return {"success": True, "description": description}
    return {"success": False, "message": "AI is not configured. Set your API key in Settings."}


@router.post("/api/vendor/ai/generate-specifications")
async def vendor_ai_generate_specs(request: Request, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return JSONResponse({"success": False, "message": "Unauthorized"}, status_code=401)
    from app.services.ai_service import generate_product_specifications
    data = await request.json()
    images = data.get("images", [])
    specs = await asyncio.to_thread(
        generate_product_specifications,
        product_name=data.get("name", ""),
        category=data.get("category", ""),
        brand=data.get("brand", ""),
        description=data.get("description", ""),
        images=images if images else None,
    )
    if specs:
        log_admin_action(db, admin, "ai_generate", "specifications", "", f"Generated specs for '{data.get('name')}'")
        return {"success": True, "specifications": specs}
    return {"success": False, "message": "AI could not generate specifications."}


@router.post("/api/vendor/ai/generate-tags")
async def vendor_ai_generate_tags(request: Request, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return JSONResponse({"success": False, "message": "Unauthorized"}, status_code=401)
    from app.services.ai_service import generate_product_tags
    data = await request.json()
    tags = await asyncio.to_thread(
        generate_product_tags,
        product_name=data.get("name", ""),
        description=data.get("description", ""),
    )
    if tags:
        log_admin_action(db, admin, "ai_generate", "tags", "", f"Generated tags for '{data.get('name')}'")
        return {"success": True, "tags": tags}
    return {"success": False, "message": "AI is not configured."}


@router.post("/api/vendor/ai/optimize-title")
async def vendor_ai_optimize_title(request: Request, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return JSONResponse({"success": False, "message": "Unauthorized"}, status_code=401)
    from app.services.ai_service import optimize_product_title
    data = await request.json()
    title = await asyncio.to_thread(
        optimize_product_title,
        product_name=data.get("name", ""),
        category=data.get("category", ""),
        brand=data.get("brand", ""),
    )
    if title:
        log_admin_action(db, admin, "ai_generate", "title", "", f"Optimized title for '{data.get('name')}'")
        return {"success": True, "title": title}
    return {"success": False, "message": "AI could not optimize the title."}


@router.post("/api/vendor/ai/pricing-advisor")
async def vendor_ai_pricing_advisor(request: Request, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return JSONResponse({"success": False, "message": "Unauthorized"}, status_code=401)
    from app.services.ai_service import generate_pricing_advisor
    data = await request.json()
    advice = await asyncio.to_thread(
        generate_pricing_advisor,
        product_name=data.get("name", ""),
        category=data.get("category", ""),
        current_price=float(data.get("price", 0) or 0),
        description=data.get("description", ""),
    )
    if advice:
        log_admin_action(db, admin, "ai_generate", "pricing", "", f"Pricing advice for '{data.get('name')}'")
        return {"success": True, "advice": advice}
    return {"success": False, "message": "AI could not generate pricing advice."}


@router.post("/api/vendor/ai/batch-generate")
async def vendor_ai_batch_generate(request: Request, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return JSONResponse({"success": False, "message": "Unauthorized"}, status_code=401)
    from app.services.ai_service import (
        generate_product_description,
        generate_product_specifications,
        generate_product_tags,
        optimize_product_title,
    )
    data = await request.json()
    name = data.get("name", "")
    category = data.get("category", "")
    brand = data.get("brand", "")
    images = data.get("images", [])
    results = {}

    def _do_batch():
        r = {}
        d = generate_product_description(
            product_name=name, category=category, brand=brand,
            keywords=data.get("keywords", ""), tone=data.get("tone", "professional"),
            images=images if images else None,
        )
        if d:
            r["description"] = d
        s = generate_product_specifications(
            product_name=name, category=category, brand=brand,
            description=d or "", images=images if images else None,
        )
        if s:
            r["specifications"] = s
        t = generate_product_tags(product_name=name, description=d or "")
        if t:
            r["tags"] = t
        ti = optimize_product_title(product_name=name, category=category, brand=brand)
        if ti:
            r["title"] = ti
        return r

    results = await asyncio.to_thread(_do_batch)
    log_admin_action(db, admin, "ai_generate", "batch", "", f"Batch generate for '{name}'")
    return {"success": True, "results": results}
