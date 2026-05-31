"""Vendor Portal — isolated router for RETAILER role users."""
from fastapi import APIRouter, Depends, Request, Form, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from datetime import timedelta
import uuid
import csv
import io

from app.database import get_db
from app.models import (
    AdminUser, Product, Category, Retailer, Order, OrderItem,
    VendorAnalytics, VendorPayout, VendorActivityLog, OrderEarning,
    AdCampaign, PromoAd, AdminRole, VendorWallet, VendorWalletTransaction,
    PayoutRequest, Settings, VendorNotification
)
from app.auth import get_current_user_from_cookie, has_permission, AdminRole as AR, log_admin_action, hash_password
from app.templates_shared import render_template
from app.utils import utcnow

router = APIRouter(tags=["vendor-portal"])


def _require_retailer(request: Request, db: Session):
    """Verify the current user has RETAILER role and return admin + retailer."""
    admin = get_current_user_from_cookie(request, db)
    if not admin:
        return None, None, RedirectResponse(url="/admin/login", status_code=302)
    role_val = admin.role.value if hasattr(admin.role, 'value') else admin.role
    if role_val != "RETAILER" and role_val != AR.RETAILER.value:
        return admin, None, RedirectResponse(url="/admin/dashboard", status_code=302)
    retailer = None
    if admin.vendor_id:
        retailer = db.query(Retailer).filter(Retailer.id == admin.vendor_id).first()
    return admin, retailer, None


@router.get("/vendor/apply", response_class=HTMLResponse)
def vendor_apply_page(request: Request, db: Session = Depends(get_db)):
    """Public page for vendor applications."""
    return render_template("web/apply-vendor.html", {"request": request})


@router.get("/vendor/dashboard", response_class=HTMLResponse)
def vendor_dashboard(request: Request, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return redirect

    total_products = 0
    total_orders = 0
    total_revenue = 0.0
    recent_orders = []

    if retailer:
        total_products = db.query(func.count(Product.id)).filter(Product.retailer_id == retailer.id).scalar() or 0
        order_ids = [oi.order_id for oi in db.query(OrderItem).join(Product).filter(Product.retailer_id == retailer.id).all()]
        if order_ids:
            total_orders = db.query(func.count(Order.id)).filter(Order.id.in_(order_ids)).scalar() or 0
            total_revenue = db.query(func.coalesce(func.sum(Order.total_amount), 0)).filter(Order.id.in_(order_ids)).scalar() or 0
            recent_orders = db.query(Order).filter(Order.id.in_(order_ids)).order_by(desc(Order.created_at)).limit(5).all()

    return render_template("vendor/dashboard.html", {
        "request": request,
        "admin": admin,
        "retailer": retailer,
        "total_products": total_products,
        "total_orders": total_orders,
        "total_revenue": float(total_revenue),
        "recent_orders": recent_orders,
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
