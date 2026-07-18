from fastapi import APIRouter, Depends, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from app.utils import utcnow
from app.core.image_compressor import compress_image
import json
import os
import uuid

from app.database import get_db
from app.models import (
    AdminUser, Product, Category, Retailer, Order, OrderItem,
    User, Settings, NewsletterSubscriber,
    BroadcastCampaign, BroadcastTemplate,
    Shipment, Affiliate, AdCampaign, PromoAd,
    ProductChatMessage, ProductFlag,
)
from app.auth import hash_password, verify_password, get_current_user_from_cookie, has_permission, log_admin_action
from app.config import get_settings
from app.templates_shared import render_template

router = APIRouter(prefix="/admin", tags=["admin"])
settings = get_settings()


def get_role_badge(role):
    """Get badge color class for an admin role."""
    badges = {
        "DIR_ADMIN": "bg-purple-100 text-purple-800 border-purple-200",
        "MANAGEMENT": "bg-blue-100 text-blue-800 border-blue-200",
        "TECH_ADMIN": "bg-cyan-100 text-cyan-800 border-cyan-200",
        "RETAILER": "bg-amber-100 text-amber-800 border-amber-200",
        "LOGISTICS": "bg-emerald-100 text-emerald-800 border-emerald-200",
    }
    return badges.get(role, "bg-stone-100 text-stone-800 border-stone-200")


# --- Dashboard ---
@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    admin = get_current_user_from_cookie(request, db)
    if admin:
        role = admin.role.value if hasattr(admin.role, 'value') else admin.role
        if role == "RETAILER":
            return RedirectResponse(url="/vendor/dashboard", status_code=302)
        elif role == "LOGISTICS":
            return RedirectResponse(url="/logistics/dashboard", status_code=302)
        else:
            return RedirectResponse(url="/admin/dashboard", status_code=302)
    return render_template("admin/login.html", {"request": request, "has_permission": has_permission})


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    admin = get_current_user_from_cookie(request, db)
    if not admin:
        return RedirectResponse(url="/admin/login", status_code=302)

    role = admin.role.value if hasattr(admin.role, 'value') else admin.role
    if role == "RETAILER":
        return RedirectResponse(url="/vendor/dashboard", status_code=302)
    elif role == "LOGISTICS":
        return RedirectResponse(url="/logistics/dashboard", status_code=302)

    total_products = db.query(func.count(Product.id)).scalar() or 0
    total_categories = db.query(func.count(Category.id)).scalar() or 0
    total_retailers = db.query(func.count(Retailer.id)).scalar() or 0
    total_orders = db.query(func.count(Order.id)).scalar() or 0
    total_customers = db.query(func.count(User.id)).scalar() or 0
    total_revenue = db.query(func.coalesce(func.sum(Order.total_amount), 0)).scalar() or 0

    recent_orders = (
        db.query(Order).order_by(desc(Order.created_at)).limit(5).all()
    )

    return render_template("admin/dashboard.html", {
        "request": request,
        "admin": admin,
        "stats": {
            "total_products": total_products,
            "total_categories": total_categories,
            "total_retailers": total_retailers,
            "total_orders": total_orders,
            "total_customers": total_customers,
            "total_revenue": float(total_revenue),
        },
        "recent_orders": recent_orders,
        "has_permission": has_permission,
    })


# --- Products ---
@router.get("/catalog", response_class=HTMLResponse)
def product_list(request: Request, db: Session = Depends(get_db)):
    admin = get_current_user_from_cookie(request, db)
    if not admin or not has_permission(admin, "catalog"):
        return RedirectResponse(url="/admin/login", status_code=302)

    # RETAILER role only sees their own products
    products = db.query(Product).order_by(desc(Product.created_at))
    if admin.role.value == "RETAILER" and admin.vendor_id:
        products = products.filter(Product.retailer_id == admin.vendor_id)
    products = products.all()
    
    categories = {c.id: c.name for c in db.query(Category).all()}
    retailers = {r.id: r.name for r in db.query(Retailer).all()}

    flag_counts = dict(
        db.query(ProductFlag.product_id, func.count(ProductFlag.id))
        .filter(ProductFlag.status == "PENDING")
        .group_by(ProductFlag.product_id)
        .all()
    )

    return render_template("admin/catalog/list.html", {
        "request": request,
        "admin": admin,
        "products": products,
        "categories": categories,
        "retailers": retailers,
        "flag_counts": flag_counts,
        "has_permission": has_permission,
    })


@router.get("/catalog/new", response_class=HTMLResponse)
def product_new(request: Request, db: Session = Depends(get_db)):
    admin = get_current_user_from_cookie(request, db)
    if not admin or not has_permission(admin, "catalog"):
        return RedirectResponse(url="/admin/login", status_code=302)

    categories = db.query(Category).all()
    retailers = db.query(Retailer).all()
    
    # RETAILER role can only create products for their own retailer
    if admin.role.value == "RETAILER" and admin.vendor_id:
        retailers = db.query(Retailer).filter(Retailer.id == admin.vendor_id).all()

    return render_template("admin/catalog/new.html", {
        "request": request,
        "admin": admin,
        "categories": categories,
        "retailers": retailers,
        "has_permission": has_permission,
    })


@router.post("/catalog/new")
async def product_create(
    request: Request,
    db: Session = Depends(get_db),
    files: list[UploadFile] = File(None),
):
    admin = get_current_user_from_cookie(request, db)
    if not admin or not has_permission(admin, "catalog"):
        return RedirectResponse(url="/admin/login", status_code=302)

    form = await request.form()

    name = form.get("name", "Unnamed Product")
    from app.core.slug import generate_product_slug
    slug = generate_product_slug(name, db)

    price_str = form.get("price", "0")
    try:
        price = float(price_str.replace(",", ""))
    except ValueError:
        price = 0.0

    discount_str = form.get("discount_price", "")
    discount_price = None
    if discount_str:
        try:
            discount_price = float(discount_str.replace(",", ""))
        except ValueError:
            pass

    try:
        inventory = int(form.get("inventory", "0"))
    except ValueError:
        inventory = 0

    # Start with any images provided via form JSON
    images_json = form.get("images", "[]")
    try:
        images = json.loads(images_json)
    except (json.JSONDecodeError, TypeError):
        images = []

    # Handle uploaded files, if any
    if files:
        from app.core.cloudinary_upload import is_cloudinary_configured, upload_to_cloudinary
        use_cloudinary = is_cloudinary_configured()
        upload_dir = os.path.join("app", "static", "uploads", "products")
        os.makedirs(upload_dir, exist_ok=True)
        for file in files:
            raw = await file.read()
            from app.core.image_compressor import get_max_upload_size_bytes
            max_bytes = get_max_upload_size_bytes(db)
            if len(raw) > max_bytes:
                raise HTTPException(status_code=400, detail=f"File too large. Maximum size is {max_bytes // (1024*1024)}MB.")
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

    # RETAILER role can only create products for their own retailer
    retailer_id = form.get("retailer_id", None)
    if admin.role.value == "RETAILER" and admin.vendor_id:
        retailer_id = admin.vendor_id

    product = Product(
        name=name,
        slug=slug,
        brand=form.get("brand", None),
        description=form.get("description", None),
        price=price,
        discount_price=discount_price,
        images=images,
        video_url=form.get("video_url") or None,
        category_id=form.get("category_id", None),
        retailer_id=retailer_id,
        inventory=inventory,
        is_new_arrival=form.get("is_new_arrival") == "true",
        is_flagship=form.get("is_flagship") == "true",
        status="APPROVED",
    )
    db.add(product)
    db.commit()
    db.refresh(product)

    log_admin_action(db, admin, "create", "product", product.id, f"Created product '{product.name}'")

    return RedirectResponse(url=f"/admin/catalog/{product.id}", status_code=302)


@router.get("/catalog/{product_id}/edit", response_class=HTMLResponse)
def product_edit(request: Request, product_id: str, db: Session = Depends(get_db)):
    admin = get_current_user_from_cookie(request, db)
    if not admin or not has_permission(admin, "catalog"):
        return RedirectResponse(url="/admin/login", status_code=302)

    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        return HTMLResponse("Product not found", status_code=404)
    
    # RETAILER role can only edit their own products
    if admin.role.value == "RETAILER" and admin.vendor_id:
        if product.retailer_id != admin.vendor_id:
            return HTMLResponse("You don't have permission to edit this product", status_code=403)

    categories = db.query(Category).all()
    retailers = db.query(Retailer).all()
    if admin.role.value == "RETAILER" and admin.vendor_id:
        retailers = db.query(Retailer).filter(Retailer.id == admin.vendor_id).all()

    return render_template("admin/catalog/edit.html", {
        "request": request,
        "admin": admin,
        "product": product,
        "categories": categories,
        "retailers": retailers,
        "has_permission": has_permission,
    })


@router.get("/catalog/{product_id}", response_class=HTMLResponse)
def product_detail(request: Request, product_id: str, db: Session = Depends(get_db)):
    admin = get_current_user_from_cookie(request, db)
    if not admin or not has_permission(admin, "catalog"):
        return RedirectResponse(url="/admin/login", status_code=302)

    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        return HTMLResponse("Product not found", status_code=404)
    
    # RETAILER role can only view their own products
    if admin.role.value == "RETAILER" and admin.vendor_id:
        if product.retailer_id != admin.vendor_id:
            return HTMLResponse("Product not found", status_code=404)

    return render_template("admin/catalog/detail.html", {
        "request": request,
        "admin": admin,
        "product": product,
        "has_permission": has_permission,
    })


# --- Categories ---
@router.get("/categories", response_class=HTMLResponse)
def category_list(request: Request, db: Session = Depends(get_db)):
    admin = get_current_user_from_cookie(request, db)
    if not admin or not has_permission(admin, "categories"):
        return RedirectResponse(url="/admin/login", status_code=302)

    categories = db.query(Category).order_by(Category.name).all()
    product_counts = {}
    for cat in categories:
        product_counts[cat.id] = db.query(func.count(Product.id)).filter(Product.category_id == cat.id).scalar() or 0

    return render_template("admin/categories/list.html", {
        "request": request,
        "admin": admin,
        "categories": categories,
        "product_counts": product_counts,
        "has_permission": has_permission,
    })


@router.get("/categories/{category_id}/edit", response_class=HTMLResponse)
def category_edit(request: Request, category_id: str, db: Session = Depends(get_db)):
    admin = get_current_user_from_cookie(request, db)
    if not admin or not has_permission(admin, "categories"):
        return RedirectResponse(url="/admin/login", status_code=302)

    category = db.query(Category).filter(Category.id == category_id).first()
    if not category:
        return HTMLResponse("Category not found", status_code=404)

    return render_template("admin/categories/edit.html", {
        "request": request,
        "admin": admin,
        "category": category,
        "has_permission": has_permission,
    })


# --- Retailers ---
@router.get("/retailers", response_class=HTMLResponse)
def retailer_list(request: Request, db: Session = Depends(get_db)):
    admin = get_current_user_from_cookie(request, db)
    if not admin or not has_permission(admin, "retailers"):
        return RedirectResponse(url="/admin/login", status_code=302)

    retailers = db.query(Retailer).order_by(Retailer.name).all()
    product_counts = {}
    for r in retailers:
        product_counts[r.id] = db.query(func.count(Product.id)).filter(Product.retailer_id == r.id).scalar() or 0

    return render_template("admin/retailers/list.html", {
        "request": request,
        "admin": admin,
        "retailers": retailers,
        "product_counts": product_counts,
        "has_permission": has_permission,
    })


@router.get("/retailers/new", response_class=HTMLResponse)
def retailer_new(request: Request, db: Session = Depends(get_db)):
    admin = get_current_user_from_cookie(request, db)
    if not admin or not has_permission(admin, "retailers"):
        return RedirectResponse(url="/admin/login", status_code=302)

    return render_template("admin/retailers/new.html", {
        "request": request,
        "admin": admin,
        "has_permission": has_permission,
    })


@router.get("/retailers/{slug}", response_class=HTMLResponse)
def retailer_detail(request: Request, slug: str, db: Session = Depends(get_db)):
    admin = get_current_user_from_cookie(request, db)
    if not admin or not has_permission(admin, "retailers"):
        return RedirectResponse(url="/admin/login", status_code=302)

    retailer = db.query(Retailer).filter(Retailer.slug == slug).first()
    if not retailer:
        return HTMLResponse("Retailer not found", status_code=404)

    products = db.query(Product).filter(Product.retailer_id == retailer.id).all()

    return render_template("admin/retailers/detail.html", {
        "request": request,
        "admin": admin,
        "retailer": retailer,
        "products": products,
        "has_permission": has_permission,
    })


@router.get("/retailers/{slug}/edit", response_class=HTMLResponse)
def retailer_edit(request: Request, slug: str, db: Session = Depends(get_db)):
    admin = get_current_user_from_cookie(request, db)
    if not admin or not has_permission(admin, "retailers"):
        return RedirectResponse(url="/admin/login", status_code=302)

    retailer = db.query(Retailer).filter(Retailer.slug == slug).first()
    if not retailer:
        return HTMLResponse("Retailer not found", status_code=404)

    return render_template("admin/retailers/edit.html", {
        "request": request,
        "admin": admin,
        "retailer": retailer,
        "has_permission": has_permission,
    })


# --- Orders ---
@router.get("/orders", response_class=HTMLResponse)
def order_list(request: Request, db: Session = Depends(get_db)):
    admin = get_current_user_from_cookie(request, db)
    if not admin or not has_permission(admin, "orders"):
        return RedirectResponse(url="/admin/login", status_code=302)

    orders = db.query(Order).order_by(desc(Order.created_at)).all()
    customers = {}
    for o in orders:
        user = db.query(User).filter(User.id == o.customer_id).first()
        customers[o.id] = user.name if user else "Unknown"

    return render_template("admin/orders/list.html", {
        "request": request,
        "admin": admin,
        "orders": orders,
        "customers": customers,
        "has_permission": has_permission,
    })


@router.get("/orders/{order_id}", response_class=HTMLResponse)
def order_detail(request: Request, order_id: str, db: Session = Depends(get_db)):
    admin = get_current_user_from_cookie(request, db)
    if not admin or not has_permission(admin, "orders"):
        return RedirectResponse(url="/admin/login", status_code=302)

    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        return HTMLResponse("Order not found", status_code=404)

    items = db.query(OrderItem).filter(OrderItem.order_id == order_id).all()
    customer = db.query(User).filter(User.id == order.customer_id).first()

    return render_template("admin/orders/detail.html", {
        "request": request,
        "admin": admin,
        "order": order,
        "items": items,
        "customer": customer,
        "has_permission": has_permission,
    })


# --- Customers ---
@router.get("/customers", response_class=HTMLResponse)
def customer_list(request: Request, db: Session = Depends(get_db)):
    admin = get_current_user_from_cookie(request, db)
    if not admin or not has_permission(admin, "customers"):
        return RedirectResponse(url="/admin/login", status_code=302)

    customers = db.query(User).order_by(desc(User.created_at)).all()

    # Compute order count per customer (not stored in DB model)
    order_counts = {}
    for c in customers:
        order_counts[c.id] = db.query(func.count(Order.id)).filter(
            Order.customer_id == c.id
        ).scalar() or 0
        c.order_count = order_counts[c.id]

    return render_template("admin/customers/list.html", {
        "request": request,
        "admin": admin,
        "customers": customers,
        "has_permission": has_permission,
    })


@router.get("/customers/{customer_id}", response_class=HTMLResponse)
def customer_detail_page(
    request: Request,
    customer_id: str,
    db: Session = Depends(get_db),
):
    admin = get_current_user_from_cookie(request, db)
    if not admin or not has_permission(admin, "customers"):
        return RedirectResponse(url="/admin/login", status_code=302)

    customer = db.query(User).filter(User.id == customer_id).first()
    if not customer:
        return RedirectResponse(url="/admin/customers", status_code=302)

    # Get customer orders
    orders = db.query(Order).filter(Order.customer_id == customer_id).order_by(desc(Order.created_at)).all()

    # Get order count and total spent
    order_count = len(orders)
    total_spent = sum(
        sum(item.subtotal for item in (order.items or []))
        for order in orders
    ) if orders else 0

    # Get addresses
    addresses = []

    return render_template("admin/customers/detail.html", {
        "request": request,
        "admin": admin,
        "customer": customer,
        "orders": orders,
        "order_count": order_count,
        "total_spent": total_spent,
        "addresses": addresses,
        "has_permission": has_permission,
    })


# --- Settings ---
@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, db: Session = Depends(get_db)):
    admin = get_current_user_from_cookie(request, db)
    if not admin or not has_permission(admin, "settings"):
        return RedirectResponse(url="/admin/login", status_code=302)

    from app.config import get_categorized_settings
    categorized = get_categorized_settings(db)

    # Determine which categories this admin can edit
    from app.routers.admin_api import SETTINGS_CATEGORY_PERMISSIONS, SETTINGS_SUPER_PERMISSION
    accessible_categories = {}
    for cat in SETTINGS_CATEGORY_PERMISSIONS:
        perm = SETTINGS_CATEGORY_PERMISSIONS.get(cat, "settings_other")
        accessible_categories[cat] = has_permission(admin, perm) or has_permission(admin, SETTINGS_SUPER_PERMISSION)

    return render_template("admin/settings/index.html", {
        "request": request,
        "admin": admin,
        "categorized_settings": categorized,
        "accessible_categories": accessible_categories,
        "has_permission": has_permission,
    })


# --- Newsletter Subscribers ---
@router.get("/newsletter/broadcast", response_class=HTMLResponse)
def newsletter_broadcast(request: Request, db: Session = Depends(get_db)):
    admin = get_current_user_from_cookie(request, db)
    if not admin or not has_permission(admin, "settings"):
        return RedirectResponse(url="/admin/login", status_code=302)

    return render_template("admin/newsletter/broadcast.html", {
        "request": request,
        "admin": admin,
        "has_permission": has_permission,
    })


@router.get("/newsletter/broadcast-analytics", response_class=HTMLResponse)
def newsletter_broadcast_analytics(request: Request, db: Session = Depends(get_db)):
    admin = get_current_user_from_cookie(request, db)
    if not admin or not has_permission(admin, "settings"):
        return RedirectResponse(url="/admin/login", status_code=302)

    campaigns = db.query(BroadcastCampaign).order_by(BroadcastCampaign.created_at.desc()).all()
    return render_template("admin/newsletter/analytics.html", {
        "request": request,
        "admin": admin,
        "campaigns": campaigns,
        "has_permission": has_permission,
    })


@router.get("/newsletter/templates", response_class=HTMLResponse)
def newsletter_templates(request: Request, db: Session = Depends(get_db)):
    admin = get_current_user_from_cookie(request, db)
    if not admin or not has_permission(admin, "settings"):
        return RedirectResponse(url="/admin/login", status_code=302)

    templates = db.query(BroadcastTemplate).order_by(BroadcastTemplate.updated_at.desc()).all()
    # Compute campaign_count for each template (not stored in DB)
    for t in templates:
        t.campaign_count = db.query(func.count(BroadcastCampaign.id)).filter(
            BroadcastCampaign.template_id == t.id
        ).scalar() or 0

    return render_template("admin/newsletter/templates.html", {
        "request": request,
        "admin": admin,
        "templates": templates,
        "has_permission": has_permission,
    })


@router.get("/newsletter-subscribers", response_class=HTMLResponse)
def newsletter_subscribers(request: Request, db: Session = Depends(get_db)):
    admin = get_current_user_from_cookie(request, db)
    if not admin or not has_permission(admin, "settings"):
        return RedirectResponse(url="/admin/login", status_code=302)

    subscribers = db.query(NewsletterSubscriber).order_by(NewsletterSubscriber.created_at.desc()).all()
    confirmed_count = db.query(NewsletterSubscriber).filter(NewsletterSubscriber.confirmed == True).count()
    pending_count = db.query(NewsletterSubscriber).filter(NewsletterSubscriber.confirmed == False).count()

    # Check for expired confirmations
    now = utcnow()
    expired_count = db.query(NewsletterSubscriber).filter(
        NewsletterSubscriber.confirmed == False,
        NewsletterSubscriber.confirm_expires_at != None,
        NewsletterSubscriber.confirm_expires_at < now,
    ).count()

    return render_template("admin/newsletter/list.html", {
        "request": request,
        "admin": admin,
        "subscribers": subscribers,
        "confirmed_count": confirmed_count,
        "pending_count": pending_count,
        "expired_count": expired_count,
        "now": utcnow,
        "has_permission": has_permission,
    })


# --- Admin Users Management ---
@router.get("/admin-users", response_class=HTMLResponse)
def admin_users_list(request: Request, db: Session = Depends(get_db)):
    admin = get_current_user_from_cookie(request, db)
    if not admin or not has_permission(admin, "admin_users"):
        return RedirectResponse(url="/admin/login", status_code=302)

    admin_users = db.query(AdminUser).order_by(AdminUser.created_at).all()
    
    return render_template("admin/users/list.html", {
        "request": request,
        "admin": admin,
        "admin_users": admin_users,
        "get_role_badge": get_role_badge,
        "has_permission": has_permission,
    })


@router.get("/admin-users/new", response_class=HTMLResponse)
def admin_users_new(request: Request, db: Session = Depends(get_db)):
    admin = get_current_user_from_cookie(request, db)
    if not admin or not has_permission(admin, "admin_users"):
        return RedirectResponse(url="/admin/login", status_code=302)

    retailers = db.query(Retailer).order_by(Retailer.name).all()

    return render_template("admin/users/new.html", {
        "request": request,
        "admin": admin,
        "retailers": retailers,
        "has_permission": has_permission,
    })


@router.post("/admin-users/new")
async def admin_users_create(request: Request, db: Session = Depends(get_db)):
    admin = get_current_user_from_cookie(request, db)
    if not admin or not has_permission(admin, "admin_users"):
        return RedirectResponse(url="/admin/login", status_code=302)

    form = await request.form()
    email = form.get("email", "")
    password = form.get("password", "")
    name = form.get("name", "")
    role = form.get("role", "LOGISTICS")
    vendor_id = form.get("vendor_id", None) or None

    if not email or not password:
        return render_template("admin/users/new.html", {
            "request": request,
            "admin": admin,
            "error": "Email and password are required",
            "has_permission": has_permission,
        })

    existing = db.query(AdminUser).filter(AdminUser.email == email).first()
    if existing:
        return render_template("admin/users/new.html", {
            "request": request,
            "admin": admin,
            "error": "An admin with this email already exists",
            "has_permission": has_permission,
        })

    new_admin = AdminUser(
        email=email,
        password=hash_password(password),
        name=name,
        role=role,
        vendor_id=vendor_id,
    )
    db.add(new_admin)
    db.commit()

    log_admin_action(db, admin, "create", "admin_user", new_admin.id, f"Created admin user {email} with role {role}")

    return RedirectResponse(url="/admin/admin-users", status_code=302)


@router.get("/admin-users/{admin_id}/edit", response_class=HTMLResponse)
def admin_users_edit(request: Request, admin_id: str, db: Session = Depends(get_db)):
    admin = get_current_user_from_cookie(request, db)
    if not admin or not has_permission(admin, "admin_users"):
        return RedirectResponse(url="/admin/login", status_code=302)

    target_admin = db.query(AdminUser).filter(AdminUser.id == admin_id).first()
    if not target_admin:
        return HTMLResponse("Admin user not found", status_code=404)

    retailers = db.query(Retailer).order_by(Retailer.name).all()

    return render_template("admin/users/edit.html", {
        "request": request,
        "admin": admin,
        "target_admin": target_admin,
        "retailers": retailers,
        "has_permission": has_permission,
    })


@router.post("/admin-users/{admin_id}/edit")
async def admin_users_update(request: Request, admin_id: str, db: Session = Depends(get_db)):
    admin = get_current_user_from_cookie(request, db)
    if not admin or not has_permission(admin, "admin_users"):
        return RedirectResponse(url="/admin/login", status_code=302)

    target_admin = db.query(AdminUser).filter(AdminUser.id == admin_id).first()
    if not target_admin:
        return HTMLResponse("Admin user not found", status_code=404)

    form = await request.form()
    target_admin.name = form.get("name", target_admin.name)
    target_admin.role = form.get("role", target_admin.role.value if hasattr(target_admin.role, 'value') else target_admin.role)
    target_admin.vendor_id = form.get("vendor_id", None) or None

    password = form.get("password", "")
    if password:
        target_admin.password = hash_password(password)

    db.commit()

    log_admin_action(db, admin, "update", "admin_user", admin_id, f"Updated admin user {target_admin.email}")

    return RedirectResponse(url="/admin/admin-users", status_code=302)


@router.get("/admin/users/{admin_id}/delete")
def admin_users_delete(request: Request, admin_id: str, db: Session = Depends(get_db)):
    admin = get_current_user_from_cookie(request, db)
    if not admin or not has_permission(admin, "admin_users"):
        return RedirectResponse(url="/admin/login", status_code=302)

    target_admin = db.query(AdminUser).filter(AdminUser.id == admin_id).first()
    if not target_admin:
        return HTMLResponse("Admin user not found", status_code=404)

    # Don't allow deleting yourself
    if target_admin.id == admin.id:
        return HTMLResponse("You cannot delete your own account", status_code=400)

    db.delete(target_admin)
    db.commit()

    log_admin_action(db, admin, "delete", "admin_user", admin_id, f"Deleted admin user {target_admin.email}")

    return RedirectResponse(url="/admin/admin-users", status_code=302)


# --- Notifications ---
@router.get("/notifications", response_class=HTMLResponse)
def notifications_page(request: Request, db: Session = Depends(get_db)):
    admin = get_current_user_from_cookie(request, db)
    if not admin:
        return RedirectResponse(url="/admin/login", status_code=302)

    return render_template("admin/notifications.html", {
        "request": request,
        "admin": admin,
        "has_permission": has_permission,
    })


# --- Intelligence Dashboard ---
@router.get("/intelligence", response_class=HTMLResponse)
def intelligence_dashboard(request: Request, db: Session = Depends(get_db)):
    admin = get_current_user_from_cookie(request, db)
    if not admin:
        return RedirectResponse(url="/admin/login", status_code=302)
    role_val = admin.role.value if hasattr(admin.role, 'value') else admin.role
    if role_val not in ("DIR_ADMIN", "MANAGEMENT", "TECH_ADMIN"):
        return RedirectResponse(url="/admin/dashboard", status_code=302)

    from app.models import AnalyticsSnapshot, CustomerLifetimeValue, FraudDetectionEvent, PredictiveForecast
    from sqlalchemy import func as sqlfunc

    total_orders = db.query(sqlfunc.count(Order.id)).scalar() or 0
    total_revenue = db.query(sqlfunc.coalesce(sqlfunc.sum(Order.total_amount), 0)).scalar() or 0
    total_customers = db.query(sqlfunc.count(User.id)).scalar() or 0
    total_products = db.query(sqlfunc.count(Product.id)).scalar() or 0
    total_retailers = db.query(sqlfunc.count(Retailer.id)).scalar() or 0
    total_shipments = db.query(sqlfunc.count(Shipment.id)).scalar() or 0

    clv_records = db.query(sqlfunc.count(CustomerLifetimeValue.id)).scalar() or 0
    fraud_events = db.query(sqlfunc.count(FraudDetectionEvent.id)).scalar() or 0
    forecasts = db.query(sqlfunc.count(PredictiveForecast.id)).scalar() or 0
    snapshots = db.query(sqlfunc.count(AnalyticsSnapshot.id)).scalar() or 0

    recent_orders = db.query(Order).order_by(desc(Order.created_at)).limit(10).all()

    return render_template("admin/intelligence.html", {
        "request": request,
        "admin": admin,
        "stats": {
            "total_orders": total_orders,
            "total_revenue": float(total_revenue),
            "total_customers": total_customers,
            "total_products": total_products,
            "total_retailers": total_retailers,
            "total_shipments": total_shipments,
            "clv_records": clv_records,
            "fraud_events": fraud_events,
            "forecasts": forecasts,
            "snapshots": snapshots,
        },
        "recent_orders": recent_orders,
        "has_permission": has_permission,
    })


# --- Retailer Banking & Ads ---
@router.get("/retailer/banking", response_class=HTMLResponse)
def retailer_banking(request: Request, db: Session = Depends(get_db)):
    admin = get_current_user_from_cookie(request, db)
    if not admin or not has_permission(admin, "catalog"):
        return RedirectResponse(url="/admin/login", status_code=302)

    retailer_id = admin.vendor_id
    retailer = None
    if retailer_id:
        retailer = db.query(Retailer).filter(Retailer.id == retailer_id).first()

    # Fetch available banks for the dropdown (from Paystack)
    banks = []
    from app.config import get_settings as gs
    cfg = gs()
    if cfg.paystack_secret_key:
        import requests
        from app.config import get_db_setting
        paystack_base = get_db_setting("paystack_api_base", "https://api.paystack.co")
        try:
            resp = requests.get(
                f"{paystack_base}/bank?country=nigeria&perPage=100",
                headers={"Authorization": f"Bearer {cfg.paystack_secret_key}"},
                timeout=10,
            )
            data = resp.json()
            if data.get("status"):
                banks = [{"code": b["code"], "name": b["name"]} for b in data.get("data", [])]
                banks.sort(key=lambda x: x["name"])
        except Exception:
            banks = []

    return render_template("admin/retailers/banking.html", {
        "request": request,
        "admin": admin,
        "retailer": retailer,
        "banks": banks,
        "has_permission": has_permission,
    })


@router.get("/retailer/ads", response_class=HTMLResponse)
def retailer_ads(request: Request, db: Session = Depends(get_db)):
    admin = get_current_user_from_cookie(request, db)
    if not admin or not has_permission(admin, "ads"):
        return RedirectResponse(url="/admin/login", status_code=302)

    selected_retailer_id = request.query_params.get("retailer_id") or admin.vendor_id

    if selected_retailer_id:
        retailer = db.query(Retailer).filter(Retailer.id == selected_retailer_id).first()
        campaigns = db.query(AdCampaign).filter(
            AdCampaign.retailer_id == selected_retailer_id
        ).order_by(AdCampaign.created_at.desc()).all()
        products = db.query(Product).filter(Product.retailer_id == selected_retailer_id).all()
    else:
        retailer = None
        campaigns = []
        products = []

    # DIR_ADMIN/MANAGEMENT can pick which retailer to manage
    all_retailers = []
    if not admin.vendor_id and admin.role.value in ("DIR_ADMIN", "MANAGEMENT"):
        all_retailers = db.query(Retailer).order_by(Retailer.name).all()

    from app.routers.admin_api import AD_PRICING
    from app.models import PromoAd

    # Fetch promo ads for this retailer (or all if admin)
    promo_query = db.query(PromoAd).order_by(PromoAd.created_at.desc())
    if selected_retailer_id:
        promo_query = promo_query.filter(
            (PromoAd.retailer_id == selected_retailer_id) | (PromoAd.retailer_id == None)
        )
    promo_ads = promo_query.limit(20).all()

    return render_template("admin/retailers/ads.html", {
        "request": request,
        "admin": admin,
        "retailer": retailer,
        "campaigns": campaigns,
        "products": products,
        "all_retailers": all_retailers,
        "selected_retailer_id": selected_retailer_id,
        "ad_pricing": AD_PRICING,
        "promo_ads": promo_ads,
        "utcnow": utcnow,
        "has_permission": has_permission,
    })


@router.get("/ads/dashboard", response_class=HTMLResponse)
def ads_dashboard(request: Request, db: Session = Depends(get_db)):
    admin = get_current_user_from_cookie(request, db)
    if not admin or not has_permission(admin, "ads"):
        return RedirectResponse(url="/admin/login", status_code=302)
    return render_template("admin/ads/dashboard.html", {
        "request": request, "admin": admin, "has_permission": has_permission,
    })


@router.get("/ads/manage", response_class=HTMLResponse)
def manage_ads(request: Request, db: Session = Depends(get_db)):
    admin = get_current_user_from_cookie(request, db)
    if not admin or not has_permission(admin, "settings"):
        return RedirectResponse(url="/admin/login", status_code=302)

    campaigns = db.query(AdCampaign).order_by(AdCampaign.created_at.desc()).all()
    retailers_map = {r.id: r for r in db.query(Retailer).all()}
    products_map = {p.id: p for p in db.query(Product).all()}

    return render_template("admin/ads/manage.html", {
        "request": request,
        "admin": admin,
        "campaigns": campaigns,
        "retailers": retailers_map,
        "products": products_map,
        "has_permission": has_permission,
    })


@router.get("/ads/analytics", response_class=HTMLResponse)
def ad_analytics_page(request: Request, db: Session = Depends(get_db)):
    admin = get_current_user_from_cookie(request, db)
    if not admin or not has_permission(admin, "settings"):
        return RedirectResponse(url="/admin/login", status_code=302)

    return render_template("admin/ads/analytics.html", {
        "request": request,
        "admin": admin,
        "has_permission": has_permission,
    })


# --- Ads Pricing & Provider Settings ---
@router.get("/ads/settings", response_class=HTMLResponse)
def ads_settings_page(request: Request, db: Session = Depends(get_db)):
    admin = get_current_user_from_cookie(request, db)
    if not admin:
        return RedirectResponse(url="/admin/login", status_code=302)
    role_val = admin.role.value if hasattr(admin.role, 'value') else admin.role
    if role_val not in ("DIR_ADMIN", "MANAGEMENT"):
        return RedirectResponse(url="/admin/dashboard", status_code=302)

    from app.routers.admin_api import AD_PRICING, PROMO_PRICING, AD_PROVIDERS
    from app.models import PromoAd

    # Get existing settings
    settings_keys = [
        "ads_default_provider", "ads_auto_approve", "ads_max_duration_days",
        "ads_min_budget", "promo_ads_enabled", "promo_flash_sale_enabled",
        "promo_hot_week_enabled", "promo_festival_enabled",
    ]
    site_settings = {}
    for key in settings_keys:
        s = db.query(Settings).filter(Settings.key == key).first()
        site_settings[key] = s.value if s else ""

    # Get promo ad counts by subtype
    subtype_counts = dict(
        db.query(PromoAd.ad_subtype, func.count(PromoAd.id))
        .group_by(PromoAd.ad_subtype)
        .all()
    )

    return render_template("admin/ads/settings.html", {
        "request": request,
        "admin": admin,
        "ad_pricing": AD_PRICING,
        "promo_pricing": PROMO_PRICING,
        "ad_providers": AD_PROVIDERS,
        "site_settings": site_settings,
        "subtype_counts": subtype_counts,
        "has_permission": has_permission,
    })


# --- Shipments ---
@router.get("/shipments", response_class=HTMLResponse)
def shipment_list(request: Request, db: Session = Depends(get_db)):
    admin = get_current_user_from_cookie(request, db)
    if not admin or not has_permission(admin, "orders"):
        return RedirectResponse(url="/admin/login", status_code=302)

    shipments = db.query(Shipment).order_by(Shipment.created_at.desc()).all()
    
    return render_template("admin/shipments.html", {
        "request": request,
        "admin": admin,
        "shipments": shipments,
        "has_permission": has_permission,
    })


# --- Affiliates ---
@router.get("/affiliates", response_class=HTMLResponse)
def affiliate_list(request: Request, db: Session = Depends(get_db)):
    admin = get_current_user_from_cookie(request, db)
    if not admin or not has_permission(admin, "settings"):
        return RedirectResponse(url="/admin/login", status_code=302)

    affiliates = db.query(Affiliate).order_by(Affiliate.created_at.desc()).all()
    
    return render_template("admin/affiliates.html", {
        "request": request,
        "admin": admin,
        "affiliates": affiliates,
        "has_permission": has_permission,
    })


# --- Chat Moderation ---
@router.get("/chat-moderation", response_class=HTMLResponse)
def chat_moderation_page(request: Request, db: Session = Depends(get_db)):
    admin = get_current_user_from_cookie(request, db)
    if not admin or not has_permission(admin, "settings"):
        return RedirectResponse(url="/admin/login", status_code=302)

    messages = (
        db.query(ProductChatMessage)
        .order_by(ProductChatMessage.created_at.desc())
        .limit(200)
        .all()
    )

    # Attach product names for display
    product_ids = list({m.product_id for m in messages})
    products_map = {p.id: p.name for p in db.query(Product).filter(Product.id.in_(product_ids)).all()}
    for m in messages:
        m.product_name = products_map.get(m.product_id, "Deleted")

    flagged_count = sum(1 for m in messages if m.is_flagged)
    hidden_count = sum(1 for m in messages if m.is_hidden)
    pending_count = sum(1 for m in messages if m.is_flagged and not m.is_hidden)

    return render_template("admin/chat-moderation.html", {
        "request": request,
        "admin": admin,
        "messages": messages,
        "flagged_count": flagged_count,
        "hidden_count": hidden_count,
        "pending_count": pending_count,
        "has_permission": has_permission,
    })


@router.get("/moderation", response_class=HTMLResponse)
def moderation_page(request: Request, db: Session = Depends(get_db)):
    admin = get_current_user_from_cookie(request, db)
    if not admin or not has_permission(admin, "catalog"):
        return RedirectResponse(url="/admin/login", status_code=302)
    return render_template("admin/moderation/dashboard.html", {
        "request": request,
        "admin": admin,
        "has_permission": has_permission,
    })


@router.get("/flags", response_class=HTMLResponse)
def flags_page(request: Request, db: Session = Depends(get_db)):
    admin = get_current_user_from_cookie(request, db)
    if not admin or not has_permission(admin, "catalog"):
        return RedirectResponse(url="/admin/login", status_code=302)
    return render_template("admin/flags/queue.html", {
        "request": request,
        "admin": admin,
        "has_permission": has_permission,
    })


# --- Logout ---
# --- Profile / Me ---
@router.get("/me", response_class=HTMLResponse)
def admin_profile(request: Request, db: Session = Depends(get_db)):
    admin = get_current_user_from_cookie(request, db)
    if not admin:
        return RedirectResponse(url="/admin/login", status_code=302)

    # Compute additional context
    product_count = db.query(func.count(Product.id)).filter(
        Product.retailer_id == admin.vendor_id
    ).scalar() if admin.vendor_id else 0

    days_active = (utcnow() - admin.created_at).days if admin.created_at else 0

    return render_template("admin/me.html", {
        "request": request,
        "admin": admin,
        "product_count": product_count,
        "days_active": days_active,
        "get_role_badge": get_role_badge,
        "has_permission": has_permission,
        "success": request.query_params.get("success"),
        "error": None,
    })


@router.post("/me")
async def admin_profile_update(request: Request, db: Session = Depends(get_db)):
    admin = get_current_user_from_cookie(request, db)
    if not admin:
        return RedirectResponse(url="/admin/login", status_code=302)

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
        "request": request,
        "admin": admin,
        "product_count": product_count,
        "days_active": days_active,
        "get_role_badge": get_role_badge,
        "has_permission": has_permission,
        "success": None,
        "error": None,
    }

    # Update name if provided
    if name and name != admin.name:
        admin.name = name

    # Update password if provided
    if new_password:
        if not current_password:
            ctx["error"] = "Please enter your current password to set a new one."
            return render_template("admin/me.html", ctx)
        if not verify_password(current_password, admin.password):
            ctx["error"] = "Current password is incorrect."
            return render_template("admin/me.html", ctx)
        from app.services.ai_service import get_setting
        min_len = int(get_setting(db, "password_min_length", "6"))
        if len(new_password) < min_len:
            ctx["error"] = f"New password must be at least {min_len} characters."
            return render_template("admin/me.html", ctx)
        if new_password != confirm_password:
            ctx["error"] = "New passwords do not match."
            return render_template("admin/me.html", ctx)
        admin.password = hash_password(new_password)

    db.commit()

    return RedirectResponse(url="/admin/me?success=Profile+updated+successfully.", status_code=302)


# --- Promo Ads ---
@router.get("/promo-ads", response_class=HTMLResponse)
def promo_ads_page(request: Request, db: Session = Depends(get_db)):
    admin = get_current_user_from_cookie(request, db)
    if not admin or not has_permission(admin, "ads"):
        return RedirectResponse(url="/admin/login", status_code=302)

    # RETAILER sees own promo ads; admins see all
    query = db.query(PromoAd).order_by(PromoAd.created_at.desc())
    if admin.role.value == "RETAILER" and admin.vendor_id:
        query = query.filter(
            (PromoAd.retailer_id == admin.vendor_id) | (PromoAd.retailer_id == None)
        )
    promo_ads = query.all()

    retailers_map = {r.id: r.name for r in db.query(Retailer).all()}
    admin_users_map = {u.id: u.name for u in db.query(AdminUser).all()}

    return render_template("admin/ads/promo_ads.html", {
        "request": request,
        "admin": admin,
        "promo_ads": promo_ads,
        "retailers_map": retailers_map,
        "admin_users_map": admin_users_map,
        "has_permission": has_permission,
    })


# --- Earnings ---
@router.get("/earnings", response_class=HTMLResponse)
def earnings_page(request: Request, db: Session = Depends(get_db)):
    admin = get_current_user_from_cookie(request, db)
    if not admin or not has_permission(admin, "ads"):
        return RedirectResponse(url="/admin/login", status_code=302)

    return render_template("admin/ads/earnings.html", {
        "request": request,
        "admin": admin,
        "has_permission": has_permission,
    })


@router.get("/support", response_class=HTMLResponse)
def admin_support_page(request: Request, db: Session = Depends(get_db)):
    admin = get_current_user_from_cookie(request, db)
    if not admin:
        return RedirectResponse(url="/admin/login", status_code=302)
    return render_template("admin/support.html", {
        "request": request,
        "admin": admin,
        "has_permission": has_permission,
    })


@router.get("/logout")
def admin_logout():
    resp = RedirectResponse(url="/admin/login", status_code=302)
    resp.delete_cookie("access_token")
    return resp
