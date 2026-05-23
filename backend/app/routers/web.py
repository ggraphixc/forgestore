from datetime import datetime
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from urllib.parse import quote

from app.database import get_db
from app.models import Product, Category, Retailer, Order, OrderItem, Review, User, Settings, WishlistItem
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
    page_context = {
        "request": request,
        "settings": _site_settings(db),
        "user": customer,
        "paystack_public_key": _cfg.paystack_public_key,
    }
    page_context.update(context)
    return render_template(template, page_context, status_code=status_code)


def _require_customer(request: Request, db: Session):
    customer = _get_current_customer(request, db)
    if customer:
        customer.updated_at = datetime.utcnow()
        db.commit()
        return customer
    next_url = request.url.path
    if request.url.query:
        next_url += f"?{request.url.query}"
    return RedirectResponse(url=f"/shop/login?next={quote(next_url)}", status_code=302)


def format_price(amount: float, currency: str = "NGN") -> str:
    symbols = {"NGN": "₦", "USD": "$", "GBP": "£", "EUR": "€"}
    symbol = symbols.get(currency, "₦")
    return f"{symbol}{amount:,.2f}"


# --- Homepage ---
@router.get("", response_class=HTMLResponse)
def homepage(request: Request, db: Session = Depends(get_db)):
    customer = _require_customer(request, db)
    if isinstance(customer, RedirectResponse):
        return customer

    currency = get_currency(db)

    flagship_products = db.query(Product).filter(Product.is_flagship == True).order_by(desc(Product.created_at)).limit(5).all()
    new_arrivals = db.query(Product).filter(Product.is_new_arrival == True).order_by(desc(Product.created_at)).limit(8).all()
    featured_retailers = db.query(Retailer).filter(Retailer.status == "ACTIVE").order_by(desc(Retailer.rating)).limit(6).all()
    categories = db.query(Category).all()

    # Product counts per retailer
    retailer_counts = {}
    for r in featured_retailers:
        retailer_counts[r.id] = db.query(func.count(Product.id)).filter(Product.retailer_id == r.id).scalar() or 0

    # Top rated products for marketplace section
    top_products = db.query(Product).order_by(desc(Product.rating)).limit(8).all()

    return _render_page("web/index.html", request, db, {
        "currency": currency,
        "format_price": format_price,
        "flagship_products": flagship_products,
        "new_arrivals": new_arrivals,
        "featured_retailers": featured_retailers,
        "retailer_counts": retailer_counts,
        "categories": categories,
        "top_products": top_products,
    })


# --- Marketplace ---
@router.get("/marketplace", response_class=HTMLResponse)
def marketplace(request: Request, db: Session = Depends(get_db)):
    customer = _require_customer(request, db)
    if isinstance(customer, RedirectResponse):
        return customer

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

    return _render_page("web/marketplace.html", request, db, {
        "currency": currency,
        "format_price": format_price,
        "products": products,
        "categories": categories,
        "retailers": retailers,
        "cat_counts": cat_counts,
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
    customer = _require_customer(request, db)
    if isinstance(customer, RedirectResponse):
        return customer

    currency = get_currency(db)
    product = db.query(Product).filter(Product.slug == slug).first()
    if not product:
        return _render_page("web/404.html", request, db, status_code=404)

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

    return render_template("web/account/dashboard.html", {
        "request": request,
        "settings": _site_settings(db),
        "user": customer,
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

    return render_template("web/account/orders.html", {
        "request": request,
        "settings": _site_settings(db),
        "user": customer,
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

    return render_template("web/account/order-detail.html", {
        "request": request,
        "settings": _site_settings(db),
        "user": customer,
        "order": order,
        "items": items,
        "currency": currency,
        "format_price": format_price,
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
    products = {p.id: p for p in db.query(Product).filter(Product.id.in_(product_ids)).all()}

    return render_template("web/account/reviews.html", {
        "request": request,
        "settings": _site_settings(db),
        "user": customer,
        "reviews": reviews,
        "products": products,
    })


@router.get("/account/settings", response_class=HTMLResponse)
def account_settings(request: Request, db: Session = Depends(get_db)):
    customer = get_current_customer_from_cookie(request, db)
    if not customer:
        return RedirectResponse(url="/shop/login", status_code=302)

    return render_template("web/account/settings.html", {
        "request": request,
        "settings": _site_settings(db),
        "user": customer,
    })


# --- Password Reset Pages ---

@router.get("/forgot-password", response_class=HTMLResponse)
def forgot_password_page(request: Request, db: Session = Depends(get_db)):
    return _render_page("web/forgot-password.html", request, db)


@router.get("/reset-password/{token}", response_class=HTMLResponse)
def reset_password_page(request: Request, token: str, db: Session = Depends(get_db)):
    return _render_page("web/reset-password.html", request, db, {"token": token})


# --- Wishlist ---
@router.get("/wishlist", response_class=HTMLResponse)
def wishlist_page(request: Request, db: Session = Depends(get_db)):
    customer = _require_customer(request, db)
    if isinstance(customer, RedirectResponse):
        return customer
    return _render_page("web/wishlist.html", request, db)
