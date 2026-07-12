from datetime import datetime
from app.utils import utcnow
from fastapi import APIRouter, Depends, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from urllib.parse import quote

from app.database import get_db
from app.models import Product, Category, Retailer, Order, OrderItem, Review, User, Settings, WishlistItem, AdCampaign, PromoAd
from app.auth import get_current_user_from_cookie, get_current_customer_from_cookie
from app.templates_shared import render_template
from app.config import get_site_settings, get_settings

router = APIRouter(prefix="/shop", tags=["web"])


def _site_settings(db):
    """Get site settings for global template injection."""
    return get_site_settings(db)


def get_currency(db: Session) -> str:
    setting = db.query(Settings).filter(Settings.key == "currency").first()
    return setting.value if setting else "NGN"


def _get_current_customer(request: Request, db: Session):
    return get_current_customer_from_cookie(request, db)


def _render_page(template: str, request: Request, db: Session, context: dict = None, status_code: int = 200):
    if context is None:
        context = {}
    customer = _get_current_customer(request, db)
    _cfg = get_settings()
    categories = db.query(Category).order_by(Category.name).all()
    page_context = {
        "request": request,
        "settings": _site_settings(db),
        "user": customer,
        "categories": categories,
        "paystack_public_key": _cfg.paystack_public_key,
        "default_payment_provider": _cfg.default_payment_provider or "paystack",
    }
    page_context.update(context)
    return render_template(template, page_context, status_code=status_code)


def _product_dict(p) -> dict:
    """Serialize a Product ORM object to a cacheable dict."""
    return {
        "id": p.id,
        "slug": p.slug,
        "name": p.name,
        "price": p.price,
        "discount_price": p.discount_price,
        "images": p.images or [],
        "rating": p.rating or 0,
        "review_count": p.review_count or 0,
        "inventory": p.inventory,
        "is_flagship": p.is_flagship,
        "is_new_arrival": p.is_new_arrival,
        "retailer_id": p.retailer_id,
        "category_id": p.category_id,
        "brand": p.brand,
    }


def _rehydrate_products(db: Session, product_dicts: list[dict]) -> list:
    """Rehydrate product dicts from cache into Product ORM objects for template rendering."""
    if not product_dicts:
        return []
    ids = [d["id"] for d in product_dicts if d.get("id")]
    if not ids:
        return []
    products = db.query(Product).filter(Product.id.in_(ids)).all()
    # Preserve original cache order
    product_map = {p.id: p for p in products}
    return [product_map[pid] for pid in ids if pid in product_map]


def _require_customer(request: Request, db: Session):
    customer = _get_current_customer(request, db)
    if customer:
        customer.updated_at = utcnow()
        db.commit()
        return customer
    next_url = request.url.path
    if request.url.query:
        next_url += f"?{request.url.query}"
    return RedirectResponse(url=f"/shop/login?next={quote(next_url)}", status_code=302)


def log_ad_impressions_background(ad_ids: list[str]):
    """Increment ad impressions in a background task.

    Uses its own database session to avoid holding the request session open
    and to prevent row-locking / 'database is locked' errors on high-traffic
    pages (homepage, marketplace).
    """
    if not ad_ids:
        return
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        for ad_id in ad_ids:
            db.query(AdCampaign).filter(AdCampaign.id == ad_id).update(
                {AdCampaign.impressions: AdCampaign.impressions + 1}
            )
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def format_price(amount: float, currency: str = "NGN", db=None) -> str:
    """Format price with full i18n support from settings."""
    symbols = {"NGN": "₦", "USD": "$", "GBP": "£", "EUR": "€"}
    symbol = symbols.get(currency, "₦")
    position = "before"
    decimal_places = 2
    thousand_sep = ","
    decimal_sep = "."
    if db:
        try:
            from app.services.ai_service import get_setting
            symbol = get_setting(db, "currency_symbol", symbol)
            position = get_setting(db, "currency_symbol_position", "before")
            decimal_places = int(get_setting(db, "currency_decimal_places", "2"))
            thousand_sep = get_setting(db, "currency_thousand_separator", ",")
            decimal_sep = get_setting(db, "currency_decimal_separator", ".")
        except Exception:
            pass
    formatted = f"{amount:,.{decimal_places}f}"
    if thousand_sep != "," or decimal_sep != ".":
        formatted = f"{amount:,.{decimal_places}f}".replace(",", "T").replace(".", "D")
        formatted = formatted.replace("T", thousand_sep).replace("D", decimal_sep)
    if position == "after":
        return f"{formatted}{symbol}"
    return f"{symbol}{formatted}"


# --- Homepage ---
@router.get("", response_class=HTMLResponse)
def homepage(request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    customer = _get_current_customer(request, db)

    currency = get_currency(db)

    # Try Redis cache for product grids — falls back to DB on miss
    import json as _json
    flagship_products = None
    new_arrivals = None
    top_products = None

    try:
        from app.core.redis_manager import get_redis
        r = get_redis()
        client = r.get_sync()

        raw_flagship = client.get("cache:homepage:flagship")
        if raw_flagship:
            flagship_products_data = _json.loads(raw_flagship)
            # Rehydrate as detached Product-like dicts for template rendering
            flagship_products = _rehydrate_products(db, flagship_products_data)

        raw_new = client.get("cache:homepage:new_arrivals")
        if raw_new:
            new_arrivals_data = _json.loads(raw_new)
            new_arrivals = _rehydrate_products(db, new_arrivals_data)

        raw_top = client.get("cache:homepage:top_products")
        if raw_top:
            top_products_data = _json.loads(raw_top)
            top_products = _rehydrate_products(db, top_products_data)
    except Exception:
        pass

    # DB fallback for any cache misses
    if flagship_products is None:
        flagship_products = db.query(Product).filter(Product.is_flagship == True).order_by(desc(Product.created_at)).limit(5).all()
        try:
            from app.core.redis_manager import get_redis
            r = get_redis()
            client = r.get_sync()
            client.set("cache:homepage:flagship", _json.dumps([_product_dict(p) for p in flagship_products], default=str), ex=300)
        except Exception:
            pass

    if new_arrivals is None:
        new_arrivals = db.query(Product).filter(Product.is_new_arrival == True).order_by(desc(Product.created_at)).limit(8).all()
        try:
            from app.core.redis_manager import get_redis
            r = get_redis()
            client = r.get_sync()
            client.set("cache:homepage:new_arrivals", _json.dumps([_product_dict(p) for p in new_arrivals], default=str), ex=300)
        except Exception:
            pass

    if top_products is None:
        top_products = db.query(Product).order_by(desc(Product.rating)).limit(8).all()
        try:
            from app.core.redis_manager import get_redis
            r = get_redis()
            client = r.get_sync()
            client.set("cache:homepage:top_products", _json.dumps([_product_dict(p) for p in top_products], default=str), ex=300)
        except Exception:
            pass

    featured_retailers = db.query(Retailer).filter(Retailer.status == "ACTIVE").order_by(desc(Retailer.rating)).limit(6).all()
    categories = db.query(Category).all()

    # Product counts per retailer
    retailer_counts = {}
    for r in featured_retailers:
        retailer_counts[r.id] = db.query(func.count(Product.id)).filter(Product.retailer_id == r.id).scalar() or 0

    # Active ad campaigns for homepage banners — chronological expiration enforced
    # Ordered by impressions (proxy for budget/weight) descending for bidding priority
    active_ads = db.query(AdCampaign).filter(
        AdCampaign.status == "ACTIVE",
        AdCampaign.end_date > utcnow()
    ).order_by(desc(AdCampaign.impressions), desc(AdCampaign.created_at)).limit(5).all()

    # Active promo ads (admin-created flash sales, holiday deals, etc.)
    active_promo_ads = db.query(PromoAd).filter(
        PromoAd.status == "ACTIVE",
        (PromoAd.end_date == None) | (PromoAd.end_date > utcnow())
    ).order_by(desc(PromoAd.created_at)).limit(6).all()

    # Track impressions asynchronously — avoids blocking page load
    if active_ads:
        background_tasks.add_task(log_ad_impressions_background, [ad.id for ad in active_ads])

    return _render_page("web/index.html", request, db, {
        "currency": currency,
        "format_price": format_price,
        "flagship_products": flagship_products,
        "new_arrivals": new_arrivals,
        "featured_retailers": featured_retailers,
        "retailer_counts": retailer_counts,
        "categories": categories,
        "top_products": top_products,
        "active_ads": active_ads,
        "active_promo_ads": active_promo_ads,
    })


# --- Marketplace ---
@router.get("/marketplace", response_class=HTMLResponse)
def marketplace(request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    customer = _get_current_customer(request, db)

    currency = get_currency(db)
    category_slug = request.query_params.get("category")

    query = db.query(Product)
    if category_slug:
        cat = db.query(Category).filter(Category.slug == category_slug).first()
        if cat:
            query = query.filter(Product.category_id == cat.id)

    products = query.order_by(desc(Product.created_at)).all()
    categories = db.query(Category).all()

    # Get retailer names
    retailers = {r.id: r.name for r in db.query(Retailer).all()}

    # Product counts per category
    cat_counts = {}
    for cat in categories:
        cat_counts[cat.id] = db.query(func.count(Product.id)).filter(Product.category_id == cat.id).scalar() or 0

    # Active ad campaigns for marketplace banners — chronological expiration enforced
    active_ad_campaigns = db.query(AdCampaign).filter(
        AdCampaign.status == "ACTIVE",
        AdCampaign.end_date > utcnow()
    ).order_by(desc(AdCampaign.created_at)).limit(4).all()

    # Active promo ads (admin-created flash sales, holiday deals, etc.)
    active_promo_ads = db.query(PromoAd).filter(
        PromoAd.status == "ACTIVE",
        (PromoAd.end_date == None) | (PromoAd.end_date > utcnow())
    ).order_by(desc(PromoAd.created_at)).limit(6).all()

    # Track impressions asynchronously — avoids blocking page load
    if active_ad_campaigns:
        background_tasks.add_task(log_ad_impressions_background, [ad.id for ad in active_ad_campaigns])

    return _render_page("web/marketplace.html", request, db, {
        "currency": currency,
        "format_price": format_price,
        "products": products,
        "categories": categories,
        "retailers": retailers,
        "cat_counts": cat_counts,
        "active_ad_campaigns": active_ad_campaigns,
        "active_promo_ads": active_promo_ads,
        "utcnow": utcnow,
    })


# --- Shops ---
@router.get("/shops", response_class=HTMLResponse)
def shops_list(request: Request, db: Session = Depends(get_db)):
    customer = _require_customer(request, db)
    if isinstance(customer, RedirectResponse):
        return customer

    currency = get_currency(db)
    retailers = db.query(Retailer).filter(Retailer.status == "ACTIVE").order_by(Retailer.name).all()

    product_counts = {}
    for r in retailers:
        product_counts[r.id] = db.query(func.count(Product.id)).filter(Product.retailer_id == r.id).scalar() or 0

    return _render_page("web/shops.html", request, db, {
        "currency": currency,
        "format_price": format_price,
        "retailers": retailers,
        "product_counts": product_counts,
    })


# --- Shop Detail ---
@router.get("/shops/{slug}", response_class=HTMLResponse)
def shop_detail(request: Request, slug: str, db: Session = Depends(get_db)):
    customer = _require_customer(request, db)
    if isinstance(customer, RedirectResponse):
        return customer

    currency = get_currency(db)
    retailer = db.query(Retailer).filter(Retailer.slug == slug).first()
    if not retailer:
        return _render_page("web/404.html", request, db, status_code=404)

    products = db.query(Product).filter(Product.retailer_id == retailer.id).all()
    categories = db.query(Category).all()

    return _render_page("web/shop-detail.html", request, db, {
        "currency": currency,
        "format_price": format_price,
        "retailer": retailer,
        "products": products,
        "categories": categories,
    })


# --- Product Detail ---
@router.get("/products/{slug}", response_class=HTMLResponse)
def product_detail(request: Request, slug: str, db: Session = Depends(get_db)):

    currency = get_currency(db)
    product = db.query(Product).filter(Product.slug == slug).first()
    if not product:
        return _render_page("web/404.html", request, db, status_code=404)

    # Increment views count
    try:
        product.views_count = (product.views_count or 0) + 1
        db.commit()
    except Exception:
        db.rollback()

    retailer = db.query(Retailer).filter(Retailer.id == product.retailer_id).first() if product.retailer_id else None
    category = db.query(Category).filter(Category.id == product.category_id).first() if product.category_id else None
    reviews = db.query(Review).filter(Review.product_id == product.id).order_by(desc(Review.created_at)).all()

    # Related products from same retailer
    related = []
    if retailer:
        related = db.query(Product).filter(
            Product.retailer_id == retailer.id,
            Product.id != product.id
        ).limit(4).all()

    return _render_page("web/product-detail.html", request, db, {
        "currency": currency,
        "format_price": format_price,
        "product": product,
        "retailer": retailer,
        "category": category,
        "reviews": reviews,
        "related": related,
    })


# --- Cart ---
@router.get("/cart", response_class=HTMLResponse)
def cart_page(request: Request, db: Session = Depends(get_db)):
    customer = _require_customer(request, db)
    if isinstance(customer, RedirectResponse):
        return customer
    return _render_page("web/cart.html", request, db)


# --- Checkout ---
@router.get("/checkout", response_class=HTMLResponse)
def checkout_page(request: Request, db: Session = Depends(get_db)):
    order_id = request.query_params.get("order_id", "")
    reference = request.query_params.get("reference", "")

    # Allow guest checkout — no login required
    customer = get_current_customer_from_cookie(request, db)

    order = None
    items = []
    product_map = {}

    if order_id:
        query = db.query(Order).filter(Order.id == order_id)
        if customer:
            query = query.filter(Order.customer_id == customer.id)
        order = query.first()

        if order:
            items = db.query(OrderItem).filter(OrderItem.order_id == order.id).all()
            pids = [i.product_id for i in items]
            product_map = {p.id: p for p in db.query(Product).filter(Product.id.in_(pids)).all()}

    currency = get_currency(db)

    return _render_page("web/checkout.html", request, db, {
        "checkout_order_id": order_id,
        "checkout_reference": reference,
        "order": order,
        "order_items": items,
        "product_map": product_map,
        "currency": currency,
        "format_price": format_price,
    })


# --- Order Success ---
@router.get("/order-success", response_class=HTMLResponse)
def order_success(request: Request, db: Session = Depends(get_db)):
    customer = get_current_customer_from_cookie(request, db)
    order_id = request.query_params.get("order_id", "")
    reference = request.query_params.get("reference", "")

    order = None
    items = []
    product_map = {}

    if order_id:
        query = db.query(Order).filter(Order.id == order_id)
        if customer:
            query = query.filter(Order.customer_id == customer.id)
        else:
            # Allow guest to view their just-placed order
            pass
        order = query.first()

        if order:
            items = db.query(OrderItem).filter(OrderItem.order_id == order.id).all()
            pids = [i.product_id for i in items]
            product_map = {p.id: p for p in db.query(Product).filter(Product.id.in_(pids)).all()}

    currency = get_currency(db)

    return _render_page("web/success.html", request, db, {
        "order": order,
        "order_items": items,
        "product_map": product_map,
        "reference": reference,
        "currency": currency,
        "format_price": format_price,
    })


# --- Login ---
@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    customer = get_current_customer_from_cookie(request, db)
    if customer:
        redirect_target = request.query_params.get("next", "/shop/account")
        return RedirectResponse(url=redirect_target, status_code=302)
    return _render_page("web/login.html", request, db)


# --- Signup ---
@router.get("/signup", response_class=HTMLResponse)
def signup_page(request: Request, db: Session = Depends(get_db)):
    customer = get_current_customer_from_cookie(request, db)
    if customer:
        redirect_target = request.query_params.get("next", "/shop/account")
        return RedirectResponse(url=redirect_target, status_code=302)
    return _render_page("web/signup.html", request, db)


# --- Logout ---
@router.get("/logout")
def customer_logout():
    from fastapi.responses import RedirectResponse
    resp = RedirectResponse(url="/shop", status_code=302)
    resp.delete_cookie("customer_token")
    return resp


# --- Account Dashboard ---
@router.get("/account", response_class=HTMLResponse)
def account_dashboard(request: Request, db: Session = Depends(get_db)):
    customer = get_current_customer_from_cookie(request, db)
    if not customer:
        return RedirectResponse(url="/shop/login", status_code=302)

    orders = db.query(Order).filter(
        Order.customer_id == customer.id
    ).order_by(Order.created_at.desc()).all()

    currency = get_currency(db)
    categories = db.query(Category).order_by(Category.name).all()

    return render_template("web/account/dashboard.html", {
        "request": request,
        "settings": _site_settings(db),
        "user": customer,
        "categories": categories,
        "orders": orders,
        "currency": currency,
        "format_price": format_price,
    })


@router.get("/account/orders", response_class=HTMLResponse)
def account_orders(request: Request, db: Session = Depends(get_db)):
    customer = get_current_customer_from_cookie(request, db)
    if not customer:
        return RedirectResponse(url="/shop/login", status_code=302)

    orders = db.query(Order).filter(
        Order.customer_id == customer.id
    ).order_by(Order.created_at.desc()).all()

    currency = get_currency(db)
    categories = db.query(Category).order_by(Category.name).all()

    return render_template("web/account/orders.html", {
        "request": request,
        "settings": _site_settings(db),
        "user": customer,
        "categories": categories,
        "orders": orders,
        "currency": currency,
        "format_price": format_price,
    })


@router.get("/account/orders/{order_id}", response_class=HTMLResponse)
def account_order_detail(request: Request, order_id: str, db: Session = Depends(get_db)):
    customer = get_current_customer_from_cookie(request, db)
    if not customer:
        return RedirectResponse(url="/shop/login", status_code=302)

    order = db.query(Order).filter(
        Order.id == order_id,
        Order.customer_id == customer.id,
    ).first()
    if not order:
        return _render_page("web/404.html", request, db, status_code=404)

    items = db.query(OrderItem).filter(OrderItem.order_id == order.id).all()
    currency = get_currency(db)
    categories = db.query(Category).order_by(Category.name).all()

    return render_template("web/account/order-detail.html", {
        "request": request,
        "settings": _site_settings(db),
        "user": customer,
        "categories": categories,
        "order": order,
        "items": items,
        "currency": currency,
        "format_price": format_price,
    })


@router.get("/account/tracking", response_class=HTMLResponse)
def account_tracking(request: Request, db: Session = Depends(get_db)):
    customer = get_current_customer_from_cookie(request, db)
    if not customer:
        return RedirectResponse(url="/shop/login", status_code=302)

    categories = db.query(Category).order_by(Category.name).all()

    return render_template("web/account/tracking.html", {
        "request": request,
        "settings": _site_settings(db),
        "user": customer,
        "categories": categories,
    })


@router.get("/account/reviews", response_class=HTMLResponse)
def account_reviews(request: Request, db: Session = Depends(get_db)):
    customer = get_current_customer_from_cookie(request, db)
    if not customer:
        return RedirectResponse(url="/shop/login", status_code=302)

    reviews = db.query(Review).filter(
        Review.user_id == customer.id
    ).order_by(desc(Review.created_at)).all()

    # Get product names for each review
    product_ids = [r.product_id for r in reviews]
    products_map = {p.id: p for p in db.query(Product).filter(Product.id.in_(product_ids)).all()}
    categories = db.query(Category).order_by(Category.name).all()

    return render_template("web/account/reviews.html", {
        "request": request,
        "settings": _site_settings(db),
        "user": customer,
        "categories": categories,
        "reviews": reviews,
        "products": products_map,
    })


@router.get("/account/settings", response_class=HTMLResponse)
def account_settings(request: Request, db: Session = Depends(get_db)):
    customer = get_current_customer_from_cookie(request, db)
    if not customer:
        return RedirectResponse(url="/shop/login", status_code=302)

    categories = db.query(Category).order_by(Category.name).all()

    return render_template("web/account/settings.html", {
        "request": request,
        "settings": _site_settings(db),
        "user": customer,
        "categories": categories,
    })


# --- Password Reset Pages ---

@router.get("/forgot-password", response_class=HTMLResponse)
def forgot_password_page(request: Request, db: Session = Depends(get_db)):
    return _render_page("web/forgot-password.html", request, db)


@router.get("/reset-password/{token}", response_class=HTMLResponse)
def reset_password_page(request: Request, token: str, db: Session = Depends(get_db)):
    return _render_page("web/reset-password.html", request, db, {"token": token})


# --- Support ---
@router.get("/support", response_class=HTMLResponse)
def support_page(request: Request, db: Session = Depends(get_db)):
    return _render_page("web/support.html", request, db)


# --- Contact ---
@router.get("/contact", response_class=HTMLResponse)
def contact_page(request: Request, db: Session = Depends(get_db)):
    return _render_page("web/contact.html", request, db)


# --- Shipping ---
@router.get("/shipping", response_class=HTMLResponse)
def shipping_page(request: Request, db: Session = Depends(get_db)):
    return _render_page("web/shipping.html", request, db)


# --- Returns ---
@router.get("/returns", response_class=HTMLResponse)
def returns_page(request: Request, db: Session = Depends(get_db)):
    return _render_page("web/returns.html", request, db)


# --- FAQ ---
@router.get("/faq", response_class=HTMLResponse)
def faq_page(request: Request, db: Session = Depends(get_db)):
    return _render_page("web/faq.html", request, db)


# --- Wishlist ---
@router.get("/wishlist", response_class=HTMLResponse)
def wishlist_page(request: Request, db: Session = Depends(get_db)):
    customer = _require_customer(request, db)
    if isinstance(customer, RedirectResponse):
        return customer
    return _render_page("web/wishlist.html", request, db)
