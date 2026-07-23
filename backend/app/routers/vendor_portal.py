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
    PayoutRequest, Settings, VendorNotification, ReturnRequest, ReturnEvent,
    ProductChatMessage, User, Review, Shipment, ShipmentEvent, VendorPromotion
)
from app.auth import get_current_user_from_cookie, has_permission, AdminRole as AR, log_admin_action, hash_password, verify_password
from app.templates_shared import render_template
from app.utils import utcnow
import json, os, logging
logger = logging.getLogger(__name__)
from app.core.image_compressor import compress_image

router = APIRouter(tags=["vendor-portal"])


def format_price(value):
    try:
        return f"₦{float(value):,.2f}"
    except (TypeError, ValueError):
        return "₦0.00"


def _get_vendor_settings(db: Session) -> dict:
    """Get all admin settings relevant to the vendor portal as a dict."""
    settings = {}
    keys = [
        # Feature toggles
        "inventory_tracking_enabled", "bulk_order_enabled", "cod_enabled",
        "flash_sales_enabled", "loyalty_points_enabled", "referral_program_enabled",
        "ai_assistant_enabled", "ai_recommendations_enabled", "vendor_chat_enabled",
        "live_chat_enabled", "comparison_enabled", "product_video_enabled",
        "product_tags_enabled", "order_tracking_enabled",
        # Financial
        "market_commission_percentage", "payout_schedule", "payout_hold_days",
        "auto_settlement_enabled", "max_order_amount", "auto_invoice_enabled",
        "invoice_prefix", "tax_enabled", "tax_percentage", "tax_name",
        # Returns/Refunds
        "refund_window_days", "return_window_days", "partial_refund_enabled",
        # Limits
        "low_stock_limit", "minimum_payout_amount", "max_discount_percent",
        "max_order_items",
    ]
    for key in keys:
        row = db.query(Settings).filter(Settings.key == key).first()
        settings[key] = row.value if row else None
    # Defaults for booleans
    for key in [
        "inventory_tracking_enabled", "bulk_order_enabled", "cod_enabled",
        "flash_sales_enabled", "loyalty_points_enabled", "referral_program_enabled",
        "ai_assistant_enabled", "ai_recommendations_enabled", "vendor_chat_enabled",
        "live_chat_enabled", "comparison_enabled", "product_video_enabled",
        "product_tags_enabled", "order_tracking_enabled",
        "auto_settlement_enabled", "auto_invoice_enabled",
        "tax_enabled", "partial_refund_enabled",
    ]:
        if settings[key] is None:
            settings[key] = "true"
    # Defaults for numbers
    for key, default in [
        ("market_commission_percentage", "10.0"), ("low_stock_limit", "5"),
        ("minimum_payout_amount", "5000"), ("max_discount_percent", "70"),
        ("max_order_amount", "0"), ("max_order_items", "50"),
        ("payout_hold_days", "7"), ("refund_window_days", "7"),
        ("return_window_days", "14"), ("tax_percentage", "0"),
    ]:
        if settings[key] is None:
            settings[key] = default
    if settings["payout_schedule"] is None:
        settings["payout_schedule"] = "weekly"
    if settings["invoice_prefix"] is None:
        settings["invoice_prefix"] = "INV-"
    if settings["tax_name"] is None:
        settings["tax_name"] = "VAT"
    return settings


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


def _feature_disabled(db: Session, setting_key: str) -> bool:
    """Check if a vendor feature is disabled via admin settings."""
    from app.models import Settings
    val = db.query(Settings.value).filter(Settings.key == setting_key).scalar()
    return val is not None and val.lower() == "false"


@router.get("/vendor/apply", response_class=HTMLResponse)
def vendor_apply_page(request: Request, db: Session = Depends(get_db)):
    """Public page for vendor applications."""
    from app.config import get_site_settings
    from app.models import AdminUser, AdminRole
    site_settings = get_site_settings(db)
    vendor_count = db.query(AdminUser).filter(AdminUser.role == AdminRole.RETAILER).count()
    return render_template("web/apply-vendor.html", {
        "request": request,
        "settings": site_settings,
        "vendor_count": vendor_count,
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
    wallet_balance = 0.0
    pending_earnings = 0.0
    total_earnings = 0.0
    active_campaigns = 0

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

        # Wallet & earnings
        wallet = db.query(VendorWallet).filter(VendorWallet.retailer_id == retailer.id).first()
        if wallet:
            wallet_balance = wallet.balance or 0

        earnings = db.query(OrderEarning).filter(OrderEarning.retailer_id == retailer.id).all()
        total_earnings = sum(e.net_amount or 0 for e in earnings)
        pending_earnings = sum(e.net_amount or 0 for e in earnings if e.status == "PENDING")

        # Active ad campaigns
        active_campaigns = db.query(func.count(AdCampaign.id)).filter(
            AdCampaign.retailer_id == retailer.id,
            AdCampaign.status == "ACTIVE",
        ).scalar() or 0

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
        "wallet_balance": float(wallet_balance),
        "pending_earnings": float(pending_earnings),
        "total_earnings": float(total_earnings),
        "active_campaigns": active_campaigns,
        "has_permission": has_permission,
        "vendor_settings": _get_vendor_settings(db),
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
        "vendor_settings": _get_vendor_settings(db),
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
        "vendor_settings": _get_vendor_settings(db),
    })


@router.post("/vendor/orders/{order_id}/ship")
async def vendor_mark_shipped(order_id: str, request: Request, db: Session = Depends(get_db)):
    """Vendor marks their fulfillment as shipped — triggers logistics assignment."""
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    from app.models import VendorFulfillment, Shipment, ShipmentEvent
    import uuid

    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        return JSONResponse({"error": "Order not found"}, status_code=404)

    vf = db.query(VendorFulfillment).filter(
        VendorFulfillment.order_id == order.id,
        VendorFulfillment.retailer_id == retailer.id
    ).first()

    if vf:
        vf.status = "SHIPPED"
        vf.assigned_driver_id = None

        existing_shipment = db.query(Shipment).filter(Shipment.order_id == order.id).first()
        if not existing_shipment:
            tracking = f"FS-{uuid.uuid4().hex[:8].upper()}"
            shipment = Shipment(
                order_id=order.id,
                tracking_number=tracking,
                status="PENDING",
                origin=vf.origin_address or (retailer.name if retailer else ""),
                destination=vf.destination_address or str(order.shipping_address),
                carrier=None,
            )
            db.add(shipment)

        db.commit()
        return JSONResponse({"ok": True, "message": "Shipment created, awaiting logistics assignment"})

    return JSONResponse({"error": "No vendor fulfillment found for this order"}, status_code=404)


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
        "vendor_settings": _get_vendor_settings(db),
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
        "vendor_settings": _get_vendor_settings(db),
    })


@router.get("/api/vendor/analytics")
def vendor_analytics_api(
    request: Request,
    period: str = "daily",
    days: int = 30,
    db: Session = Depends(get_db),
):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        raise HTTPException(status_code=401, detail="Not authenticated")

    if not retailer:
        raise HTTPException(status_code=400, detail="No vendor profile")

    # ── Period analytics ──
    period_records = db.query(VendorAnalytics).filter(
        VendorAnalytics.retailer_id == retailer.id,
        VendorAnalytics.period == period,
    ).order_by(desc(VendorAnalytics.period_start)).limit(days).all()

    # ── Totals from period records ──
    total_revenue = sum(r.total_revenue or 0 for r in period_records)
    total_orders = sum(r.total_orders or 0 for r in period_records)
    total_products_sold = sum(r.total_products_sold or 0 for r in period_records)
    total_customers = sum(r.unique_customers or 0 for r in period_records)
    avg_order_value = total_revenue / total_orders if total_orders > 0 else 0
    avg_conversion = sum(r.conversion_rate or 0 for r in period_records) / len(period_records) if period_records else 0
    total_page_views = sum(r.page_views or 0 for r in period_records)

    # ── Earnings breakdown ──
    earnings = db.query(OrderEarning).filter(
        OrderEarning.retailer_id == retailer.id,
    ).order_by(desc(OrderEarning.created_at)).limit(200).all()
    net_earnings = sum(e.net_amount or 0 for e in earnings)
    gross_earnings = sum(e.amount or 0 for e in earnings)
    total_commission = sum(e.commission or 0 for e in earnings)
    pending_earnings = sum(e.net_amount or 0 for e in earnings if e.status == "PENDING")
    paid_earnings = sum(e.net_amount or 0 for e in earnings if e.status == "PAID")

    # ── Top products ──
    from app.models import Product
    product_sales = {}
    for item in db.query(OrderItem).join(
        Product, OrderItem.product_id == Product.id
    ).filter(Product.retailer_id == retailer.id).all():
        pid = item.product_id
        if pid not in product_sales:
            product_sales[pid] = {"qty": 0, "revenue": 0}
        product_sales[pid]["qty"] += item.quantity or 1
        product_sales[pid]["revenue"] += (item.price or 0) * (item.quantity or 1)

    top_products = []
    for pid, data in sorted(product_sales.items(), key=lambda x: x[1]["revenue"], reverse=True)[:5]:
        product = db.query(Product).filter(Product.id == pid).first()
        top_products.append({
            "name": product.name if product else "Unknown",
            "qty": data["qty"],
            "revenue": data["revenue"],
            "image": product.images[0] if product and product.images else None,
        })

    # ── Recent orders for table ──
    recent_orders = []
    order_query = db.query(Order).join(OrderItem).join(
        Product, OrderItem.product_id == Product.id
    ).filter(Product.retailer_id == retailer.id).order_by(desc(Order.created_at)).limit(10).all()
    seen_orders = set()
    for o in order_query:
        if o.id not in seen_orders:
            seen_orders.add(o.id)
            recent_orders.append({
                "id": o.id,
                "order_number": o.order_number,
                "status": o.status.value if hasattr(o.status, 'value') else str(o.status),
                "total": o.total_amount,
                "created_at": o.created_at.isoformat() if o.created_at else None,
            })

    # ── Status distribution ──
    status_dist = {}
    for o in order_query:
        s = o.status.value if hasattr(o.status, 'value') else str(o.status)
        status_dist[s] = status_dist.get(s, 0) + 1

    return JSONResponse({
        "period_records": [{
            "period": r.period,
            "period_start": r.period_start.isoformat() if r.period_start else None,
            "revenue": r.total_revenue,
            "orders": r.total_orders,
            "products_sold": r.total_products_sold,
            "customers": r.unique_customers,
            "avg_order_value": r.avg_order_value,
            "conversion_rate": r.conversion_rate,
            "page_views": r.page_views,
        } for r in reversed(period_records)],
        "totals": {
            "revenue": total_revenue,
            "orders": total_orders,
            "products_sold": total_products_sold,
            "customers": total_customers,
            "avg_order_value": round(avg_order_value, 2),
            "avg_conversion": round(avg_conversion, 2),
            "page_views": total_page_views,
        },
        "earnings": {
            "net": net_earnings,
            "gross": gross_earnings,
            "commission": total_commission,
            "pending": pending_earnings,
            "paid": paid_earnings,
        },
        "top_products": top_products,
        "recent_orders": recent_orders,
        "status_distribution": status_dist,
    })


# ═══════════════════════════════════════════════════════════════════════════════
# ENHANCED ANALYTICS — Date Range, CSV Export, AI Insights
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/api/vendor/analytics/export")
def vendor_analytics_export(
    request: Request,
    start_date: str = "",
    end_date: str = "",
    db: Session = Depends(get_db),
):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return JSONResponse({"success": False}, status_code=401)

    from datetime import datetime as dt
    start = dt.fromisoformat(start_date) if start_date else utcnow() - timedelta(days=30)
    end = dt.fromisoformat(end_date) if end_date else utcnow()

    # Get orders in date range
    order_items = db.query(OrderItem).join(Order).join(Product).filter(
        Product.retailer_id == admin.vendor_id,
        Order.created_at >= start,
        Order.created_at <= end,
    ).all()

    import io, csv
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Date", "Order", "Product", "Qty", "Unit Price", "Total", "Status"])
    for oi in order_items:
        product = db.query(Product).filter(Product.id == oi.product_id).first()
        order = db.query(Order).filter(Order.id == oi.order_id).first()
        writer.writerow([
            order.created_at.strftime("%Y-%m-%d") if order else "",
            order.order_number if order else "",
            product.name if product else "",
            oi.quantity,
            f"{oi.price:.2f}",
            f"{(oi.price or 0) * (oi.quantity or 1):.2f}",
            order.status if order else "",
        ])

    from fastapi.responses import StreamingResponse
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=analytics_{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}.csv"},
    )


@router.get("/api/vendor/analytics/pdf-export")
def vendor_analytics_pdf_export(
    request: Request,
    start_date: str = "",
    end_date: str = "",
    db: Session = Depends(get_db),
):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return JSONResponse({"success": False}, status_code=401)

    from datetime import datetime as dt
    start = dt.fromisoformat(start_date) if start_date else utcnow() - timedelta(days=30)
    end = dt.fromisoformat(end_date) if end_date else utcnow()

    order_items = db.query(OrderItem).join(Order).join(Product).filter(
        Product.retailer_id == admin.vendor_id,
        Order.created_at >= start,
        Order.created_at <= end,
    ).all()

    rows = ""
    for oi in order_items:
        product = db.query(Product).filter(Product.id == oi.product_id).first()
        order = db.query(Order).filter(Order.id == oi.order_id).first()
        rows += f"<tr><td>{order.created_at.strftime('%Y-%m-%d') if order else ''}</td><td>{order.order_number if order else ''}</td><td>{product.name if product else ''}</td><td>{oi.quantity}</td><td>₦{oi.price:.2f}</td><td>₦{(oi.price or 0) * (oi.quantity or 1):.2f}</td><td>{order.status if order else ''}</td></tr>"

    html = f"""<!DOCTYPE html><html><head><title>Analytics Report</title>
    <style>body{{font-family:sans-serif;padding:2rem;}}table{{width:100%;border-collapse:collapse;font-size:12px;}}th,td{{border:1px solid #ddd;padding:6px 8px;text-align:left;}}th{{background:#f5f5f5;font-weight:700;}}h1{{font-size:18px;}}</style>
    </head><body><h1>Analytics Report — {admin.name}</h1>
    <p>Period: {start.strftime('%b %d, %Y')} — {end.strftime('%b %d, %Y')}</p>
    <p>Total Items: {len(order_items)}</p>
    <table><thead><tr><th>Date</th><th>Order</th><th>Product</th><th>Qty</th><th>Price</th><th>Total</th><th>Status</th></tr></thead>
    <tbody>{rows}</tbody></table></body></html>"""

    from fastapi.responses import HTMLResponse
    return HTMLResponse(content=html, headers={"Content-Disposition": f"attachment; filename=analytics_{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}.html"})


@router.get("/api/vendor/analytics/ai-insights")
def vendor_analytics_ai_insights(
    request: Request,
    days: int = 30,
    db: Session = Depends(get_db),
):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return JSONResponse({"success": False}, status_code=401)

    from app.services.vendor_analytics_service import VendorAnalyticsService
    from app.services.ai_service import get_ai_client, get_active_model, _call_llm_sync

    service = VendorAnalyticsService(db)
    forecast = service.get_inventory_forecast(admin.vendor_id)

    # Gather data for AI
    period_records = db.query(VendorAnalytics).filter(
        VendorAnalytics.retailer_id == retailer.id,
    ).order_by(desc(VendorAnalytics.period_start)).limit(days).all()

    total_revenue = sum(r.total_revenue or 0 for r in period_records)
    total_orders = sum(r.total_orders or 0 for r in period_records)
    avg_order_value = total_revenue / total_orders if total_orders > 0 else 0
    out_of_stock = sum(1 for f in forecast if f["current_inventory"] == 0)
    low_stock = sum(1 for f in forecast if 0 < f["days_until_out"] <= 14)

    prompt = f"""Analyze this vendor's performance and give 3-5 actionable insights:

Revenue (last {days}d): ₦{total_revenue:,.0f}
Orders: {total_orders}
Avg Order Value: ₦{avg_order_value:,.0f}
Products: {len(forecast)}
Out of Stock: {out_of_stock}
Low Stock: {low_stock}

Give concise, specific recommendations in JSON format:
{{"insights": [{{"title": "...", "detail": "...", "impact": "high|medium|low"}}]}}"""

    try:
        client, model = get_ai_client()
        result = _call_llm_sync(client, model, prompt, max_tokens=1000)
        import json
        # Try to parse JSON from response
        text = result.get("content", "")
        # Extract JSON from possible markdown code block
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        insights = json.loads(text.strip())
        return {"success": True, "insights": insights.get("insights", [])}
    except Exception as e:
        # Fallback: rule-based insights
        insights = []
        if out_of_stock > 0:
            insights.append({"title": "Out of Stock Alert", "detail": f"{out_of_stock} products are out of stock. Restock immediately to avoid lost sales.", "impact": "high"})
        if low_stock > 3:
            insights.append({"title": "Low Stock Warning", "detail": f"{low_stock} products will run out within 2 weeks based on current sales velocity.", "impact": "high"})
        if avg_order_value < 5000:
            insights.append({"title": "Increase AOV", "detail": "Your average order value is below ₦5,000. Consider bundling products or offering free shipping above a threshold.", "impact": "medium"})
        if total_orders < 10:
            insights.append({"title": "Boost Marketing", "detail": "Low order volume. Run ad campaigns or offer discounts to drive more traffic.", "impact": "medium"})
        if not insights:
            insights.append({"title": "On Track", "detail": "Your store is performing well. Keep maintaining inventory levels and customer service.", "impact": "low"})
        return {"success": True, "insights": insights}


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
    from app.core.image_compressor import get_max_upload_size_bytes
    max_bytes = get_max_upload_size_bytes(db)
    if len(content) > max_bytes:
        raise HTTPException(status_code=400, detail=f"File too large. Maximum size is {max_bytes // (1024*1024)}MB.")
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

    # Validate minimum payout amount
    from app.models import Settings as SettingsModel
    min_payout_setting = db.query(SettingsModel).filter(SettingsModel.key == "minimum_payout_amount").first()
    min_payout = float(min_payout_setting.value) if min_payout_setting else 0.0
    if min_payout > 0 and amount < min_payout:
        raise HTTPException(status_code=400, detail=f"Minimum payout is ₦{min_payout:,.2f}")

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

AD_PRICING = {
    "SHOP": 10000,
    "PRODUCT": 5000,
}

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
    ad_type = data.get("ad_type", "PRODUCT").upper()
    banner_url = data.get("banner_url", "")
    start_date_str = data.get("start_date")
    end_date_str = data.get("end_date")
    duration_months = int(data.get("duration_months", 1))
    target_url = data.get("target_url", "")
    ad_subtype = data.get("ad_subtype")
    banner_type = data.get("banner_type", "banner")
    note = data.get("note", "")

    # Calculate budget from pricing table
    if ad_type not in AD_PRICING:
        raise HTTPException(status_code=400, detail=f"Invalid ad_type '{ad_type}'")
    budget = AD_PRICING[ad_type] * duration_months

    # Use default banner URL if not provided
    if not banner_url:
        banner_url = "/static/uploads/products/default-ad-banner.jpg"

    # Validate product ownership if PRODUCT ad
    if ad_type == "PRODUCT" and product_id:
        product = db.query(Product).filter(
            Product.id == product_id,
            Product.retailer_id == admin.vendor_id,
        ).first()
        if not product:
            raise HTTPException(status_code=404, detail="Product not found or not owned by you")

    # Auto-create wallet if missing
    wallet = db.query(VendorWallet).filter(VendorWallet.retailer_id == admin.vendor_id).first()
    if not wallet:
        wallet = VendorWallet(retailer_id=admin.vendor_id, balance=0)
        db.add(wallet)
        db.flush()

    # Check wallet balance
    if wallet.balance < budget:
        raise HTTPException(status_code=400, detail=f"Insufficient wallet balance. Required: ₦{budget:,.0f}, Available: ₦{wallet.balance:,.0f}. Please top up your wallet first.")

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
        description=f"Ad campaign: {ad_type} ({duration_months}mo)",
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
        "budget": budget,
        "remaining_balance": wallet.balance,
    }


@router.post("/api/vendor/wallet/topup")
async def vendor_wallet_topup(
    request: Request,
    db: Session = Depends(get_db),
):
    """Initialize a wallet top-up via Paystack for the vendor."""
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return JSONResponse({"success": False, "message": "Unauthorized"}, status_code=401)

    data = await request.json()
    amount = float(data.get("amount", 0))
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")

    from app.services.payment_provider import get_payment_provider
    from app.config import get_settings
    cfg = get_settings()

    # Ensure wallet exists
    wallet = db.query(VendorWallet).filter(VendorWallet.retailer_id == admin.vendor_id).first()
    if not wallet:
        wallet = VendorWallet(retailer_id=admin.vendor_id, balance=0)
        db.add(wallet)
        db.flush()

    import uuid
    reference = f"VW-{uuid.uuid4().hex[:12].upper()}"
    callback_url = f"{cfg.site_base_url.rstrip('/')}/vendor/wallet/callback"
    metadata = {"vendor_id": admin.vendor_id, "purpose": "vendor_wallet_topup", "wallet_id": wallet.id}

    provider = get_payment_provider()
    result = provider.initialize_payment(
        email=admin.email or "vendor@forgestore.com",
        amount=amount,
        reference=reference,
        callback_url=callback_url,
        currency="NGN",
        metadata=metadata,
    )

    if result.get("success"):
        return {"success": True, "authorization_url": result.get("authorization_url", ""), "reference": reference}
    else:
        return JSONResponse({"success": False, "detail": result.get("message", "Payment initialization failed")}, status_code=400)


@router.get("/vendor/wallet/callback")
def vendor_wallet_callback(request: Request, db: Session = Depends(get_db)):
    """Paystack callback after wallet top-up — verify payment and credit vendor wallet."""
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return redirect

    reference = request.query_params.get("reference", "")
    if not reference:
        return RedirectResponse(url="/vendor/ads?wallet=error", status_code=302)

    try:
        from app.services.payment_provider import get_payment_provider
        provider = get_payment_provider()
        result = provider.verify_payment(reference)

        if result.get("success") and result.get("status") == "success":
            amount = result.get("amount", 0) / 100  # Convert kobo to naira

            wallet = db.query(VendorWallet).filter(VendorWallet.retailer_id == admin.vendor_id).first()
            if wallet:
                balance_before = wallet.balance
                wallet.balance += amount

                txn = VendorWalletTransaction(
                    wallet_id=wallet.id,
                    transaction_type="topup",
                    amount=amount,
                    balance_before=balance_before,
                    balance_after=wallet.balance,
                    reference=reference,
                    description=f"Wallet top-up of ₦{amount:,.2f}",
                )
                db.add(txn)
                db.commit()
                return RedirectResponse(url="/vendor/ads?wallet=success", status_code=302)

        return RedirectResponse(url="/vendor/ads?wallet=failed", status_code=302)
    except Exception as e:
        logger.error("Wallet callback error: %s", e)
        return RedirectResponse(url="/vendor/ads?wallet=error", status_code=302)


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

    # Get wallet balance
    wallet_balance = 0
    if retailer:
        wallet = db.query(VendorWallet).filter(VendorWallet.retailer_id == retailer.id).first()
        if wallet:
            wallet_balance = wallet.balance

    return render_template("vendor/ads.html", {
        "request": request,
        "admin": admin,
        "retailer": retailer,
        "campaigns": [_campaign_dict(c) for c in campaigns],
        "promos": [_promo_dict(p) for p in promos],
        "products": [{"id": p.id, "name": p.name, "image": (p.images[0] if p.images else "")} for p in products],
        "wallet_balance": wallet_balance,
        "has_permission": has_permission,
        "vendor_settings": _get_vendor_settings(db),
    })


@router.get("/vendor/support", response_class=HTMLResponse)
def vendor_support(request: Request, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return redirect
    return render_template("vendor/support.html", {
        "request": request, "admin": admin, "retailer": retailer,
        "has_permission": has_permission,
        "vendor_settings": _get_vendor_settings(db),
    })


@router.get("/vendor/notifications", response_class=HTMLResponse)
def vendor_notifications(request: Request, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return redirect
    return render_template("vendor/notifications.html", {
        "request": request, "admin": admin, "retailer": retailer,
        "has_permission": has_permission,
        "vendor_settings": _get_vendor_settings(db),
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
        "vendor_settings": _get_vendor_settings(db),
    })


@router.post("/vendor/products/new")
async def vendor_product_create(request: Request, db: Session = Depends(get_db),
                                files: list[UploadFile] = File(None)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return redirect

    form = await request.form()

    name = form.get("name", "Unnamed Product")
    from app.core.slug import generate_product_slug
    slug = generate_product_slug(name, db)
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

    product = Product(
        name=name, slug=slug, brand=form.get("brand"),
        description=form.get("description"), price=price,
        discount_price=discount_price, images=images,
        video_url=form.get("video_url") or None,
        category_id=form.get("category_id"),
        retailer_id=admin.vendor_id, inventory=inventory,
        is_new_arrival=form.get("is_new_arrival") == "true",
        is_flagship=form.get("is_flagship") == "true",
        specifications=json.loads(form.get("specifications") or "{}"),
        status="PENDING_REVIEW",
    )
    db.add(product)
    db.commit()
    db.refresh(product)

    # Run AI moderation
    try:
        from app.services.product_moderation import run_moderation
        category_name = ""
        if product.category_id:
            cat = db.query(Category).filter(Category.id == product.category_id).first()
            category_name = cat.name if cat else ""
        moderation_result = run_moderation({
            "name": product.name, "brand": product.brand or "",
            "description": product.description or "",
            "price": product.price,
            "discount_price": product.discount_price,
            "images": product.images or [],
            "inventory": product.inventory,
            "category_name": category_name,
            "sub_category": product.sub_category or "",
        })
        product.ai_confidence_score = moderation_result["confidence"]
        product.ai_moderation_result = moderation_result
        if moderation_result["decision"] == "APPROVE":
            product.status = "APPROVED"
            product.moderated_at = utcnow()
            product.moderation_note = moderation_result["reasoning"]
        elif moderation_result["decision"] == "REJECT":
            product.status = "REJECTED"
            product.moderated_at = utcnow()
            product.moderation_note = moderation_result["reasoning"]
        db.commit()
        # Log moderation
        from app.models import ProductModerationLog
        log = ProductModerationLog(
            product_id=product.id,
            action=f"auto_{moderation_result['decision'].lower()}",
            ai_score=moderation_result["confidence"],
            ai_reasoning=moderation_result["reasoning"],
        )
        db.add(log)
        db.commit()
    except Exception as e:
        import logging
        logging.getLogger("forgestore.moderation").error(f"Moderation failed for product {product.id}: {e}")

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
        "vendor_settings": _get_vendor_settings(db),
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
        "vendor_settings": _get_vendor_settings(db),
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
    new_name = form.get("name", product.name)
    product.name = new_name
    # Auto-regenerate slug when name changes
    if new_name != product.name or not product.slug:
        from app.core.slug import generate_product_slug
        product.slug = generate_product_slug(new_name, db, exclude_id=product.id)
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
    product.video_url = form.get("video_url") or product.video_url
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
            from app.core.image_compressor import get_max_upload_size_bytes
            max_bytes = get_max_upload_size_bytes(db)
            if len(raw) > max_bytes:
                raise HTTPException(status_code=400, detail=f"File too large. Maximum size is {max_bytes // (1024*1024)}MB.")
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


# ─── Vendor Theme Toggle ─────────────────────────────────────────────────

@router.post("/api/vendor/theme")
async def vendor_theme_toggle(request: Request, db: Session = Depends(get_db)):
    """Save vendor's dark mode preference to admin Settings (theme_mode)."""
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return JSONResponse({"success": False, "message": "Unauthorized"}, status_code=401)
    data = await request.json()
    mode = data.get("mode", "light")
    if mode not in ("light", "dark", "system"):
        mode = "light"
    setting = db.query(Settings).filter(Settings.key == "theme_mode").first()
    if setting:
        setting.value = mode
    else:
        db.add(Settings(key="theme_mode", value=mode, category="design", setting_type="select",
                        label="Theme Mode", description="Default color scheme."))
    db.commit()
    from app.config import invalidate_settings_cache
    invalidate_settings_cache()
    return {"success": True, "mode": mode}


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

    # Load notification preferences
    import json as _json
    notif_prefs = {"notify_orders": True, "notify_reviews": True, "notify_payouts": False, "notify_announcements": False}
    if admin.vendor_id:
        notif_key = f"vendor_notif_prefs_{admin.vendor_id}"
        from app.models import Settings as SettingsModel
        saved = db.query(SettingsModel).filter(SettingsModel.key == notif_key).first()
        if saved and saved.value:
            try:
                notif_prefs.update(_json.loads(saved.value))
            except Exception:
                pass

    return render_template("vendor/profile.html", {
        "request": request, "admin": admin, "retailer": retailer,
        "product_count": product_count, "days_active": days_active,
        "get_role_badge": get_role_badge, "has_permission": has_permission,
        "success": request.query_params.get("success"), "error": None,
        "notif_prefs": notif_prefs,
        "vendor_settings": _get_vendor_settings(db),
    })


@router.post("/vendor/me")
async def vendor_profile_update(request: Request, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return redirect

    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        data = await request.json()
    else:
        form = await request.form()
        data = dict(form)

    name = (data.get("name") or "").strip()
    current_password = data.get("current_password", "")
    new_password = data.get("new_password", "")
    confirm_password = data.get("confirm_password", "")

    # Store fields
    store_name = (data.get("store_name") or "").strip()
    store_bio = (data.get("store_bio") or "").strip()
    store_location = (data.get("store_location") or "").strip()
    logo_url = data.get("logo_url", "")
    banner_url = data.get("banner_url", "")

    # Notification preferences
    notify_orders = data.get("notify_orders")
    notify_reviews = data.get("notify_reviews")
    notify_payouts = data.get("notify_payouts")
    notify_announcements = data.get("notify_announcements")

    product_count = db.query(func.count(Product.id)).filter(
        Product.retailer_id == admin.vendor_id
    ).scalar() if admin.vendor_id else 0
    days_active = (utcnow() - admin.created_at).days if admin.created_at else 0

    ctx = {
        "request": request, "admin": admin, "retailer": retailer,
        "product_count": product_count, "days_active": days_active,
        "get_role_badge": get_role_badge, "has_permission": has_permission,
        "success": None, "error": None,
        "vendor_settings": _get_vendor_settings(db),
    }

    def _error_response(msg):
        ctx["error"] = msg
        if "application/json" in content_type:
            return JSONResponse({"success": False, "message": msg}, status_code=400)
        return render_template("vendor/profile.html", ctx)

    if name and name != admin.name:
        admin.name = name
    if new_password:
        if not current_password:
            return _error_response("Please enter your current password to set a new one.")
        if not verify_password(current_password, admin.password):
            return _error_response("Current password is incorrect.")
        from app.services.ai_service import get_setting
        min_len = int(get_setting(db, "password_min_length", "6"))
        if len(new_password) < min_len:
            return _error_response(f"New password must be at least {min_len} characters.")
        if new_password != confirm_password:
            return _error_response("New passwords do not match.")
        admin.password = hash_password(new_password)

    # Update retailer store profile
    if retailer:
        if store_name:
            retailer.name = store_name
        if store_bio is not None:
            retailer.bio = store_bio
        if store_location is not None:
            retailer.location = store_location
        if logo_url is not None:
            retailer.logo_url = logo_url
        if banner_url is not None:
            retailer.banner_url = banner_url
        retailer.updated_at = utcnow()

    # Save notification preferences via Settings model
    import json as _json
    notif_prefs = {
        "notify_orders": bool(notify_orders) if notify_orders is not None else True,
        "notify_reviews": bool(notify_reviews) if notify_reviews is not None else True,
        "notify_payouts": bool(notify_payouts) if notify_payouts is not None else False,
        "notify_announcements": bool(notify_announcements) if notify_announcements is not None else False,
    }
    if retailer:
        notif_key = f"vendor_notif_prefs_{admin.vendor_id}"
        from app.models import Settings as SettingsModel
        existing = db.query(SettingsModel).filter(SettingsModel.key == notif_key).first()
        if existing:
            existing.value = _json.dumps(notif_prefs)
        else:
            db.add(SettingsModel(key=notif_key, value=_json.dumps(notif_prefs), category="other"))

    db.commit()
    if "application/json" in content_type:
        return JSONResponse({"success": True, "message": "Profile updated successfully.", "redirect": "/vendor/me?success=Profile+updated+successfully."})
    return RedirectResponse(url="/vendor/me?success=Profile+updated+successfully.", status_code=302)


# ─── VENDOR FILE UPLOAD ──────────────────────────────────────────────────────

@router.post("/api/vendor/upload")
async def vendor_upload_file(
    files: list[UploadFile] = File(...),
    request: Request = None,
    db: Session = Depends(get_db),
):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    from app.core.cloudinary_upload import is_cloudinary_configured, upload_to_cloudinary
    from app.core.image_compressor import compress_image, get_max_upload_size_bytes
    import os

    use_cloudinary = is_cloudinary_configured()
    urls = []
    upload_dir = os.path.join("app", "static", "uploads", "products")
    os.makedirs(upload_dir, exist_ok=True)

    for file in files:
        try:
            raw = await file.read()
            max_bytes = get_max_upload_size_bytes()
            if len(raw) > max_bytes:
                continue
            if use_cloudinary:
                url = upload_to_cloudinary(raw, folder="forgestore/products")
                if url:
                    urls.append(url)
                    continue
            compressed, ext = compress_image(raw)
            unique_name = f"{int(utcnow().timestamp())}-{uuid.uuid4().hex[:8]}.{ext}"
            file_path = os.path.join(upload_dir, unique_name)
            with open(file_path, "wb") as f:
                f.write(compressed)
            urls.append(f"/static/uploads/products/{unique_name}")
        except Exception:
            continue

    return {"urls": urls}


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
    # Check product_tags_enabled setting
    from app.models import Settings as SettingsModel
    tags_setting = db.query(SettingsModel).filter(SettingsModel.key == "product_tags_enabled").first()
    if tags_setting and tags_setting.value.lower() == "false":
        return JSONResponse({"success": False, "message": "Product tags are disabled"}, status_code=400)
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


# ===== Bulk Orders =====

@router.get("/vendor/bulk-orders", response_class=HTMLResponse)
def vendor_bulk_orders(request: Request, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return redirect
    if _feature_disabled(db, "bulk_order_enabled"):
        return RedirectResponse(url="/vendor/products", status_code=302)
    from app.models import BulkOrder, Product
    orders = db.query(BulkOrder).filter(BulkOrder.retailer_id == admin.vendor_id).order_by(BulkOrder.created_at.desc()).all()
    return render_template("vendor/bulk_orders.html", {
        "request": request, "admin": admin, "retailer": retailer,
        "orders": orders, "format_price": format_price,
        "has_permission": has_permission,
        "vendor_settings": _get_vendor_settings(db),
    })


@router.post("/api/vendor/bulk-orders/{order_id}/approve")
async def vendor_approve_bulk_order(order_id: str, request: Request, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return JSONResponse({"success": False, "message": "Unauthorized"}, status_code=401)
    if _feature_disabled(db, "bulk_order_enabled"):
        return JSONResponse({"success": False, "message": "Bulk orders disabled"}, status_code=403)
    from app.models import BulkOrder
    order = db.query(BulkOrder).filter(BulkOrder.id == order_id, BulkOrder.retailer_id == admin.vendor_id).first()
    if not order:
        return JSONResponse({"success": False, "message": "Not found"}, status_code=404)
    data = await request.json()
    order.status = "APPROVED"
    order.vendor_notes = data.get("notes", "")
    order.unit_price = data.get("unit_price", order.unit_price)
    order.total_price = order.unit_price * order.quantity
    db.commit()
    log_admin_action(db, admin, "update", "bulk_order", order.id, f"Approved bulk order for {order.quantity} units")
    return {"success": True}


@router.post("/api/vendor/bulk-orders/{order_id}/reject")
async def vendor_reject_bulk_order(order_id: str, request: Request, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return JSONResponse({"success": False, "message": "Unauthorized"}, status_code=401)
    if _feature_disabled(db, "bulk_order_enabled"):
        return JSONResponse({"success": False, "message": "Bulk orders disabled"}, status_code=403)
    from app.models import BulkOrder
    order = db.query(BulkOrder).filter(BulkOrder.id == order_id, BulkOrder.retailer_id == admin.vendor_id).first()
    if not order:
        return JSONResponse({"success": False, "message": "Not found"}, status_code=404)
    data = await request.json()
    order.status = "REJECTED"
    order.vendor_notes = data.get("reason", "")
    db.commit()
    log_admin_action(db, admin, "update", "bulk_order", order.id, f"Rejected bulk order")
    return {"success": True}


# ═══════════════════════════════════════════════════════════════════════════════
# VENDOR RETURNS MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════════

REASON_LABELS = {
    "FAILED_DELIVERY": "Failed Delivery",
    "DAMAGED": "Damaged Item",
    "WRONG_ITEM": "Wrong Item Sent",
    "NOT_RECEIVED": "Not Received",
    "CUSTOMER_CANCEL": "Customer Cancelled",
    "QUALITY_ISSUE": "Quality Issue",
}

STATUS_LABELS = {
    "PENDING": "Pending Review",
    "APPROVED": "Approved",
    "PICKUP_SCHEDULED": "Pickup Scheduled",
    "IN_TRANSIT": "In Transit",
    "RECEIVED": "Received",
    "REFUNDED": "Refunded",
    "REJECTED": "Rejected",
}

STATUS_COLORS = {
    "PENDING": "var(--yellow)",
    "APPROVED": "var(--green)",
    "PICKUP_SCHEDULED": "var(--blue)",
    "IN_TRANSIT": "var(--blue)",
    "RECEIVED": "var(--green)",
    "REFUNDED": "var(--muted)",
    "REJECTED": "var(--red)",
}


@router.get("/vendor/returns", response_class=HTMLResponse)
def vendor_returns_page(request: Request, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return redirect
    return render_template("vendor/returns.html", {
        "request": request,
        "admin": admin,
        "retailer": retailer,
        "reason_labels": REASON_LABELS,
        "status_labels": STATUS_LABELS,
        "status_colors": STATUS_COLORS,
        "has_permission": has_permission,
        "vendor_settings": _get_vendor_settings(db),
    })


@router.get("/api/vendor/returns")
def vendor_returns_list(
    request: Request,
    status: str = "",
    page: int = 1,
    per_page: int = 15,
    db: Session = Depends(get_db),
):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return JSONResponse({"success": False}, status_code=401)

    q = db.query(ReturnRequest).filter(ReturnRequest.retailer_id == admin.vendor_id)
    if status:
        q = q.filter(ReturnRequest.status == status.upper())

    total = q.count()
    returns = q.order_by(desc(ReturnRequest.created_at)).offset((page - 1) * per_page).limit(per_page).all()

    items = []
    for r in returns:
        order = db.query(Order).filter(Order.id == r.order_id).first()
        customer = db.query(User).filter(User.id == r.customer_id).first()
        items.append({
            "id": r.id,
            "return_number": r.return_number,
            "order_number": order.order_number if order else "—",
            "customer_name": customer.name if customer else "—",
            "reason": r.reason,
            "reason_label": REASON_LABELS.get(r.reason, r.reason),
            "status": r.status,
            "status_label": STATUS_LABELS.get(r.status, r.status),
            "return_fee": r.return_fee,
            "refund_amount": r.refund_amount,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "description": r.description or "",
        })

    return {
        "returns": items,
        "total": total,
        "page": page,
        "pages": max(1, -(-total // per_page)),
    }


@router.get("/vendor/returns/{return_id}", response_class=HTMLResponse)
def vendor_return_detail_page(return_id: str, request: Request, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return redirect

    rr = db.query(ReturnRequest).filter(
        ReturnRequest.id == return_id,
        ReturnRequest.retailer_id == admin.vendor_id,
    ).first()
    if not rr:
        return RedirectResponse(url="/vendor/returns", status_code=302)

    events = db.query(ReturnEvent).filter(ReturnEvent.return_id == rr.id).order_by(ReturnEvent.created_at).all()
    order = db.query(Order).filter(Order.id == rr.order_id).first()
    customer = db.query(User).filter(User.id == rr.customer_id).first()

    return render_template("vendor/return_detail.html", {
        "request": request,
        "admin": admin,
        "retailer": retailer,
        "rr": rr,
        "events": events,
        "order": order,
        "customer": customer,
        "reason_labels": REASON_LABELS,
        "status_labels": STATUS_LABELS,
        "status_colors": STATUS_COLORS,
        "has_permission": has_permission,
        "vendor_settings": _get_vendor_settings(db),
    })


@router.get("/api/vendor/returns/{return_id}")
def vendor_return_detail_api(return_id: str, request: Request, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return JSONResponse({"success": False}, status_code=401)

    rr = db.query(ReturnRequest).filter(
        ReturnRequest.id == return_id,
        ReturnRequest.retailer_id == admin.vendor_id,
    ).first()
    if not rr:
        return JSONResponse({"success": False, "detail": "Not found"}, status_code=404)

    events = db.query(ReturnEvent).filter(ReturnEvent.return_id == rr.id).order_by(ReturnEvent.created_at).all()
    order = db.query(Order).filter(Order.id == rr.order_id).first()
    customer = db.query(User).filter(User.id == rr.customer_id).first()

    # Get order items
    order_items = []
    if order:
        oi_list = db.query(OrderItem).filter(OrderItem.order_id == order.id).all()
        for oi in oi_list:
            product = db.query(Product).filter(Product.id == oi.product_id).first()
            order_items.append({
                "name": oi.product_name or (product.name if product else "Product"),
                "price": oi.price,
                "quantity": oi.quantity,
                "image": product.images[0] if product and product.images else None,
            })

    return {
        "return": {
            "id": rr.id,
            "return_number": rr.return_number,
            "reason": rr.reason,
            "reason_label": REASON_LABELS.get(rr.reason, rr.reason),
            "status": rr.status,
            "status_label": STATUS_LABELS.get(rr.status, rr.status),
            "description": rr.description or "",
            "return_fee": rr.return_fee,
            "refund_amount": rr.refund_amount,
            "pickup_address": rr.pickup_address or "",
            "delivery_address": rr.delivery_address or "",
            "evidence_urls": rr.evidence_urls or [],
            "created_at": rr.created_at.isoformat() if rr.created_at else None,
            "updated_at": rr.updated_at.isoformat() if rr.updated_at else None,
        },
        "order": {
            "id": order.id,
            "order_number": order.order_number,
            "total": order.total_amount,
        } if order else None,
        "customer": {
            "name": customer.name if customer else "—",
            "email": customer.email if customer else "",
        } if customer else None,
        "order_items": order_items,
        "events": [{
            "status": e.status,
            "description": e.description or "",
            "created_by": e.created_by or "",
            "created_at": e.created_at.isoformat() if e.created_at else None,
        } for e in events],
    }


@router.post("/api/vendor/returns/{return_id}/respond")
async def vendor_respond_return(return_id: str, request: Request, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return JSONResponse({"success": False}, status_code=401)

    rr = db.query(ReturnRequest).filter(
        ReturnRequest.id == return_id,
        ReturnRequest.retailer_id == admin.vendor_id,
    ).first()
    if not rr:
        return JSONResponse({"success": False, "detail": "Not found"}, status_code=404)
    if rr.status != "PENDING":
        return JSONResponse({"success": False, "detail": "Return already processed"}, status_code=400)

    data = await request.json()
    action = data.get("action", "")
    notes = data.get("notes", "")

    if action == "approve":
        rr.status = "APPROVED"
        rr.resolution_notes = notes
        event_desc = f"Vendor approved return"
    elif action == "reject":
        rr.status = "REJECTED"
        rr.resolution_notes = notes
        rr.resolved_by = admin.id
        event_desc = f"Vendor rejected return: {notes}"
    else:
        return JSONResponse({"success": False, "detail": "Invalid action"}, status_code=400)

    event = ReturnEvent(
        return_id=rr.id,
        status=rr.status,
        description=event_desc,
        created_by=admin.id,
    )
    db.add(event)
    db.commit()

    # Notify customer
    try:
        from app.core.notifications import send_whatsapp_message
        customer = db.query(User).filter(User.id == rr.customer_id).first()
        if customer and customer.phone:
            msg = f"Your return request {rr.return_number} has been {rr.status.lower().replace('_', ' ')}."
            if notes:
                msg += f"\nNote: {notes}"
            send_whatsapp_message(customer.phone, msg)
    except Exception:
        pass

    log_admin_action(db, admin, "update", "return_request", rr.id, event_desc)
    return {"success": True, "status": rr.status}


@router.post("/api/vendor/returns/{return_id}/notes")
async def vendor_return_add_note(return_id: str, request: Request, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return JSONResponse({"success": False}, status_code=401)

    rr = db.query(ReturnRequest).filter(
        ReturnRequest.id == return_id,
        ReturnRequest.retailer_id == admin.vendor_id,
    ).first()
    if not rr:
        return JSONResponse({"success": False, "detail": "Not found"}, status_code=404)

    data = await request.json()
    note = data.get("note", "").strip()
    if not note:
        return JSONResponse({"success": False, "detail": "Note required"}, status_code=400)

    event = ReturnEvent(
        return_id=rr.id,
        status=rr.status,
        description=f"Vendor note: {note}",
        created_by=admin.id,
    )
    db.add(event)
    db.commit()
    return {"success": True}


@router.get("/api/vendor/returns/stats")
def vendor_return_stats(request: Request, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return JSONResponse({"success": False}, status_code=401)

    base = db.query(ReturnRequest).filter(ReturnRequest.retailer_id == admin.vendor_id)
    return {
        "total": base.count(),
        "pending": base.filter(ReturnRequest.status == "PENDING").count(),
        "approved": base.filter(ReturnRequest.status == "APPROVED").count(),
        "in_transit": base.filter(ReturnRequest.status == "IN_TRANSIT").count(),
        "received": base.filter(ReturnRequest.status == "RECEIVED").count(),
        "rejected": base.filter(ReturnRequest.status == "REJECTED").count(),
        "refunded": base.filter(ReturnRequest.status == "REFUNDED").count(),
    }


@router.get("/api/vendor/returns/ai-analysis")
def vendor_returns_ai_analysis(request: Request, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return JSONResponse({"success": False}, status_code=401)

    returns = db.query(ReturnRequest).filter(ReturnRequest.retailer_id == admin.vendor_id).all()
    if not returns:
        return {"analysis": {"patterns": [], "fraud_risk": [], "recommendations": []}}

    # Rule-based analysis
    from collections import Counter
    reason_counts = Counter(r.reason for r in returns)
    status_counts = Counter(r.status for r in returns)

    patterns = []
    for reason, count in reason_counts.most_common(5):
        pct = round(count / len(returns) * 100)
        patterns.append({"reason": reason, "count": count, "percentage": pct})

    fraud_risk = []
    for r in returns:
        if r.status == "PENDING" and r.reason in ("Changed mind", "No longer needed"):
            fraud_risk.append({"return_id": r.id, "reason": r.reason, "risk": "medium"})
        if status_counts.get("REJECTED", 0) > len(returns) * 0.3:
            fraud_risk.append({"return_id": r.id, "reason": r.reason, "risk": "high"})

    recommendations = []
    top_reason = reason_counts.most_common(1)
    if top_reason:
        recommendations.append(f"Most common return reason: '{top_reason[0][0]}' ({top_reason[0][1]} returns). Consider improving product description for this issue.")

    # Try LLM analysis
    try:
        from app.services.ai_service import get_ai_client, get_active_model, _call_llm_sync
        client, model = get_ai_client()
        return_data = [{"reason": r.reason, "status": r.status, "amount": float(r.refund_amount or 0)} for r in returns[:30]]
        import json
        result = _call_llm_sync(client, model, f"Analyze these vendor returns for patterns, fraud risk, and recommendations:\n{json.dumps(return_data)}\nReturn JSON: {{\"patterns\": [...], \"fraud_risk\": [...], \"recommendations\": [...]}}", max_tokens=800)
        import re
        text = result.get("content", "")
        match = re.search(r'\{[\s\S]*\}', text)
        if match:
            ai_analysis = json.loads(match.group())
            return {"analysis": ai_analysis}
    except Exception:
        pass

    return {"analysis": {"patterns": patterns, "fraud_risk": fraud_risk[:5], "recommendations": recommendations}}


# ═══════════════════════════════════════════════════════════════════════════════
# VENDOR INVENTORY INTELLIGENCE
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/vendor/inventory", response_class=HTMLResponse)
def vendor_inventory_page(request: Request, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return redirect
    if _feature_disabled(db, "inventory_tracking_enabled"):
        return RedirectResponse(url="/vendor/products", status_code=302)
    return render_template("vendor/inventory.html", {
        "request": request,
        "admin": admin,
        "retailer": retailer,
        "has_permission": has_permission,
        "vendor_settings": _get_vendor_settings(db),
    })


@router.get("/api/vendor/inventory")
def vendor_inventory_list(
    request: Request,
    filter: str = "",
    sort: str = "urgency",
    page: int = 1,
    per_page: int = 20,
    db: Session = Depends(get_db),
):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return JSONResponse({"success": False}, status_code=401)
    if _feature_disabled(db, "inventory_tracking_enabled"):
        return JSONResponse({"success": False, "message": "Inventory tracking disabled"}, status_code=403)

    from app.services.vendor_analytics_service import VendorAnalyticsService
    service = VendorAnalyticsService(db)
    forecasts = service.get_inventory_forecast(admin.vendor_id)

    # Enrich with product data
    products_map = {p.id: p for p in db.query(Product).filter(Product.retailer_id == admin.vendor_id).all()}

    items = []
    for f in forecasts:
        p = products_map.get(f["product_id"])
        if not p:
            continue

        # Apply filter
        if filter == "out_of_stock" and f["current_inventory"] > 0:
            continue
        if filter == "low_stock" and (f["current_inventory"] == 0 or f["days_until_out"] > 14):
            continue
        if filter == "in_stock" and f["current_inventory"] == 0:
            continue

        # Compute urgency score (lower = more urgent)
        urgency = f["days_until_out"]
        if f["current_inventory"] == 0:
            urgency = -1  # out of stock is most urgent

        items.append({
            "id": p.id,
            "name": p.name,
            "image": p.images[0] if p.images else None,
            "price": p.price,
            "inventory": f["current_inventory"],
            "daily_rate": f["daily_sales_rate"],
            "days_until_out": f["days_until_out"],
            "restock_recommended": f["restock_recommended"],
            "urgency": urgency,
            "category": p.category.name if p.category else "—",
        })

    # Sort
    if sort == "urgency":
        items.sort(key=lambda x: x["urgency"])
    elif sort == "name":
        items.sort(key=lambda x: x["name"].lower())
    elif sort == "inventory":
        items.sort(key=lambda x: x["inventory"])
    elif sort == "daily_rate":
        items.sort(key=lambda x: -x["daily_rate"])

    total = len(items)
    start = (page - 1) * per_page
    items = items[start:start + per_page]

    return {
        "items": items,
        "total": total,
        "page": page,
        "pages": max(1, -(-total // per_page)),
        "summary": {
            "total_products": len(forecasts),
            "out_of_stock": sum(1 for f in forecasts if f["current_inventory"] == 0),
            "low_stock": sum(1 for f in forecasts if 0 < f["days_until_out"] <= 14),
            "in_stock": sum(1 for f in forecasts if f["current_inventory"] > 0 and f["days_until_out"] > 14),
        },
    }


@router.post("/api/vendor/inventory/bulk-update")
async def vendor_inventory_bulk_update(request: Request, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return JSONResponse({"success": False}, status_code=401)
    if _feature_disabled(db, "inventory_tracking_enabled"):
        return JSONResponse({"success": False, "message": "Inventory tracking disabled"}, status_code=403)

    data = await request.json()
    updates = data.get("updates", [])
    if not updates:
        return JSONResponse({"success": False, "detail": "No updates provided"}, status_code=400)

    updated = 0
    for u in updates:
        product_id = u.get("product_id")
        new_inventory = u.get("inventory")
        if product_id is None or new_inventory is None:
            continue
        product = db.query(Product).filter(
            Product.id == product_id,
            Product.retailer_id == admin.vendor_id,
        ).first()
        if product:
            product.inventory = int(new_inventory)
            updated += 1

    db.commit()
    log_admin_action(db, admin, "update", "inventory", None, f"Bulk updated {updated} products")
    return {"success": True, "updated": updated}


@router.post("/api/vendor/inventory/update")
async def vendor_inventory_single_update(request: Request, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return JSONResponse({"success": False}, status_code=401)
    if _feature_disabled(db, "inventory_tracking_enabled"):
        return JSONResponse({"success": False, "message": "Inventory tracking disabled"}, status_code=403)

    data = await request.json()
    product_id = data.get("product_id")
    new_inventory = data.get("inventory")

    if not product_id or new_inventory is None:
        return JSONResponse({"success": False, "detail": "product_id and inventory required"}, status_code=400)

    product = db.query(Product).filter(
        Product.id == product_id,
        Product.retailer_id == admin.vendor_id,
    ).first()
    if not product:
        return JSONResponse({"success": False, "detail": "Product not found"}, status_code=404)

    product.inventory = int(new_inventory)
    db.commit()
    return {"success": True, "inventory": product.inventory}


@router.get("/api/vendor/inventory/export")
def vendor_inventory_export(request: Request, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return JSONResponse({"success": False}, status_code=401)
    if _feature_disabled(db, "inventory_tracking_enabled"):
        return JSONResponse({"success": False, "message": "Inventory tracking disabled"}, status_code=403)

    from fastapi.responses import StreamingResponse
    import csv, io

    products = db.query(Product).filter(Product.retailer_id == admin.vendor_id).all()
    from app.services.vendor_analytics_service import VendorAnalyticsService
    vas = VendorAnalyticsService(db)
    forecast_list = vas.get_inventory_forecast(admin.vendor_id)
    forecast_map = {f["product_id"]: f for f in forecast_list}

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Product", "Category", "Price", "Inventory", "Sold", "Daily Rate", "Days Left", "Restock Recommended"])

    for p in products:
        fc = forecast_map.get(p.id, {})
        writer.writerow([
            p.name,
            p.category.name if p.category else "",
            float(p.price),
            p.inventory,
            p.sold_count,
            fc.get("daily_sales_rate", 0),
            fc.get("days_until_out", "N/A"),
            "Yes" if fc.get("restock_recommended") else "No",
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=inventory_{admin.vendor_id[:8]}.csv"},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# VENDOR REVIEW MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/vendor/reviews", response_class=HTMLResponse)
def vendor_reviews_page(request: Request, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return redirect
    return render_template("vendor/reviews.html", {
        "request": request,
        "admin": admin,
        "retailer": retailer,
        "has_permission": has_permission,
        "vendor_settings": _get_vendor_settings(db),
    })


@router.get("/api/vendor/reviews")
def vendor_reviews_list(
    request: Request,
    rating: str = "",
    page: int = 1,
    per_page: int = 15,
    db: Session = Depends(get_db),
):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return JSONResponse({"success": False}, status_code=401)

    from app.models import Review

    q = db.query(Review).join(Product, Review.product_id == Product.id).filter(
        Product.retailer_id == admin.vendor_id
    )
    if rating:
        try:
            r_val = int(rating)
            q = q.filter(Review.rating == r_val)
        except ValueError:
            pass

    total = q.count()
    reviews = q.order_by(desc(Review.created_at)).offset((page - 1) * per_page).limit(per_page).all()

    items = []
    for r in reviews:
        product = db.query(Product).filter(Product.id == r.product_id).first()
        items.append({
            "id": r.id,
            "product_name": product.name if product else "—",
            "product_image": product.images[0] if product and product.images else None,
            "author": r.author,
            "rating": r.rating,
            "title": r.title or "",
            "content": r.content or "",
            "helpful": r.helpful or 0,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })

    return {
        "reviews": items,
        "total": total,
        "page": page,
        "pages": max(1, -(-total // per_page)),
    }


@router.get("/api/vendor/reviews/stats")
def vendor_reviews_stats(request: Request, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return JSONResponse({"success": False}, status_code=401)

    from app.models import Review

    base = db.query(Review).join(Product, Review.product_id == Product.id).filter(
        Product.retailer_id == admin.vendor_id
    )
    total = base.count()
    avg = db.query(func.avg(Review.rating)).join(Product, Review.product_id == Product.id).filter(
        Product.retailer_id == admin.vendor_id
    ).scalar() or 0

    distribution = {}
    for i in range(1, 6):
        distribution[i] = base.filter(Review.rating == i).count()

    return {
        "total": total,
        "avg_rating": round(float(avg), 1),
        "distribution": distribution,
    }


@router.get("/api/vendor/reviews/ai-summary")
def vendor_reviews_ai_summary(request: Request, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return JSONResponse({"success": False}, status_code=401)

    from app.models import Review
    from app.services.ai_service import get_ai_client, get_active_model, _call_llm_sync

    reviews = db.query(Review).join(Product, Review.product_id == Product.id).filter(
        Product.retailer_id == admin.vendor_id
    ).order_by(desc(Review.created_at)).limit(50).all()

    if not reviews:
        return {"success": True, "summary": {"pros": [], "cons": [], "verdict": "No reviews yet."}}

    review_text = "\n".join([
        f"{'⭐' * r.rating} {r.title or ''}: {r.content[:200]}" for r in reviews[:30]
    ])

    prompt = f"""Summarize these product reviews into pros, cons, and a verdict:

{review_text}

Return JSON:
{{"pros": ["..."], "cons": ["..."], "verdict": "..."}}"""

    try:
        client, model = get_ai_client()
        result = _call_llm_sync(client, model, prompt, max_tokens=800)
        import json
        text = result.get("content", "")
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        summary = json.loads(text.strip())
        return {"success": True, "summary": summary}
    except Exception:
        # Fallback: rule-based
        positive = [r for r in reviews if r.rating >= 4]
        negative = [r for r in reviews if r.rating <= 2]
        return {"success": True, "summary": {
            "pros": [f"{len(positive)} positive reviews ({round(len(positive)/len(reviews)*100)}%)"],
            "cons": [f"{len(negative)} negative reviews ({round(len(negative)/len(reviews)*100)}%)"],
            "verdict": f"Average rating: {round(sum(r.rating for r in reviews)/len(reviews), 1)}/5 from {len(reviews)} reviews.",
        }}


@router.get("/api/vendor/reviews/sentiment")
def vendor_reviews_sentiment(request: Request, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return JSONResponse({"success": False}, status_code=401)

    from app.models import Review

    reviews = db.query(Review).join(Product, Review.product_id == Product.id).filter(
        Product.retailer_id == admin.vendor_id
    ).order_by(desc(Review.created_at)).limit(100).all()

    if not reviews:
        return {"data_points": [], "summary": {"positive": 0, "neutral": 0, "negative": 0}}

    # Group by date and sentiment
    from collections import defaultdict
    daily = defaultdict(lambda: {"positive": 0, "neutral": 0, "negative": 0})
    for r in reviews:
        date_key = r.created_at.strftime("%Y-%m-%d") if r.created_at else "unknown"
        if r.rating >= 4:
            daily[date_key]["positive"] += 1
        elif r.rating == 3:
            daily[date_key]["neutral"] += 1
        else:
            daily[date_key]["negative"] += 1

    data_points = [{"date": k, **v} for k, v in sorted(daily.items())]
    total_pos = sum(d["positive"] for d in data_points)
    total_neu = sum(d["neutral"] for d in data_points)
    total_neg = sum(d["negative"] for d in data_points)

    return {
        "data_points": data_points,
        "summary": {"positive": total_pos, "neutral": total_neu, "negative": total_neg},
    }


@router.post("/api/vendor/reviews/{review_id}/suggest-response")
async def vendor_review_suggest_response(review_id: str, request: Request, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return JSONResponse({"success": False}, status_code=401)

    from app.models import Review
    review = db.query(Review).join(Product, Review.product_id == Product.id).filter(
        Review.id == review_id, Product.retailer_id == admin.vendor_id
    ).first()
    if not review:
        return JSONResponse({"success": False}, status_code=404)

    prompt = f"""You are a helpful vendor responding to a customer review.
Review: {review.rating}/5 stars - "{review.title or ''}: {review.content[:500]}"
Write a professional, empathetic vendor response (2-3 sentences). Be grateful for positive reviews, address concerns in negative ones."""

    try:
        from app.services.ai_service import get_ai_client, get_active_model, _call_llm_sync
        client, model = get_ai_client()
        result = _call_llm_sync(client, model, prompt, max_tokens=300)
        return {"suggestion": result.get("content", "")}
    except Exception:
        if review.rating >= 4:
            return {"suggestion": "Thank you so much for your kind review! We're thrilled you love the product. Your support means the world to us!"}
        else:
            return {"suggestion": "We're sorry to hear about your experience. Your feedback is important to us — please reach out so we can make this right."}


# ═══════════════════════════════════════════════════════════════════════════════
# VENDOR MESSAGES (Product Q&A)
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/vendor/messages", response_class=HTMLResponse)
def vendor_messages_page(request: Request, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return redirect
    if _feature_disabled(db, "vendor_chat_enabled"):
        return RedirectResponse(url="/vendor/products", status_code=302)
    return render_template("vendor/messages.html", {
        "request": request,
        "admin": admin,
        "retailer": retailer,
        "has_permission": has_permission,
        "vendor_settings": _get_vendor_settings(db),
    })


@router.get("/api/vendor/messages/threads")
def vendor_message_threads(request: Request, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return JSONResponse({"success": False}, status_code=401)
    if _feature_disabled(db, "vendor_chat_enabled"):
        return JSONResponse({"success": False, "message": "Vendor chat disabled"}, status_code=403)

    # Get products for this vendor
    product_ids = [p.id for p in db.query(Product.id).filter(Product.retailer_id == admin.vendor_id).all()]
    if not product_ids:
        return {"threads": []}

    # Get latest message per product
    from sqlalchemy import func, distinct
    subq = db.query(
        ProductChatMessage.product_id,
        func.max(ProductChatMessage.created_at).label("last_at"),
    ).filter(
        ProductChatMessage.product_id.in_(product_ids),
    ).group_by(ProductChatMessage.product_id).subquery()

    threads = []
    for row in db.query(subq).all():
        msg = db.query(ProductChatMessage).filter(
            ProductChatMessage.product_id == row.product_id,
            ProductChatMessage.created_at == row.last_at,
        ).first()
        if not msg:
            continue
        product = db.query(Product).filter(Product.id == row.product_id).first()
        unread = db.query(ProductChatMessage).filter(
            ProductChatMessage.product_id == row.product_id,
            ProductChatMessage.is_admin == False,
            ProductChatMessage.is_flagged == False,
        ).count()
        threads.append({
            "product_id": row.product_id,
            "product_name": product.name if product else "—",
            "product_image": product.images[0] if product and product.images else None,
            "last_message": msg.content[:100] if msg.content else "",
            "last_author": msg.author_name,
            "last_at": msg.created_at.isoformat() if msg.created_at else None,
            "unread_count": unread,
        })

    threads.sort(key=lambda t: t["last_at"] or "", reverse=True)
    return {"threads": threads}


@router.get("/api/vendor/messages/{product_id}")
def vendor_message_thread(product_id: str, request: Request, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return JSONResponse({"success": False}, status_code=401)
    if _feature_disabled(db, "vendor_chat_enabled"):
        return JSONResponse({"success": False, "message": "Vendor chat disabled"}, status_code=403)

    product = db.query(Product).filter(Product.id == product_id, Product.retailer_id == admin.vendor_id).first()
    if not product:
        return JSONResponse({"success": False, "detail": "Not found"}, status_code=404)

    messages = db.query(ProductChatMessage).filter(
        ProductChatMessage.product_id == product_id,
    ).order_by(ProductChatMessage.created_at).all()

    return {
        "product": {
            "id": product.id,
            "name": product.name,
            "image": product.images[0] if product.images else None,
        },
        "messages": [{
            "id": m.id,
            "author": m.author_name,
            "content": m.content,
            "image_url": m.image_url,
            "is_admin": m.is_admin,
            "is_flagged": m.is_flagged,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        } for m in messages],
    }


@router.post("/api/vendor/messages/{product_id}/reply")
async def vendor_reply_message(product_id: str, request: Request, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return JSONResponse({"success": False}, status_code=401)
    if _feature_disabled(db, "vendor_chat_enabled"):
        return JSONResponse({"success": False, "message": "Vendor chat disabled"}, status_code=403)

    product = db.query(Product).filter(Product.id == product_id, Product.retailer_id == admin.vendor_id).first()
    if not product:
        return JSONResponse({"success": False, "detail": "Not found"}, status_code=404)

    data = await request.json()
    content = data.get("content", "").strip()
    if not content:
        return JSONResponse({"success": False, "detail": "Message required"}, status_code=400)

    msg = ProductChatMessage(
        product_id=product_id,
        user_id=None,
        author_name=admin.name or "Vendor",
        content=content,
        is_admin=True,
    )
    db.add(msg)
    db.commit()
    return {"success": True, "message_id": msg.id}


@router.post("/api/vendor/messages/{message_id}/flag")
async def vendor_flag_message(message_id: str, request: Request, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return JSONResponse({"success": False}, status_code=401)
    if _feature_disabled(db, "vendor_chat_enabled"):
        return JSONResponse({"success": False, "message": "Vendor chat disabled"}, status_code=403)

    msg = db.query(ProductChatMessage).filter(ProductChatMessage.id == message_id).first()
    if not msg:
        return JSONResponse({"success": False, "detail": "Not found"}, status_code=404)

    data = await request.json()
    msg.is_flagged = data.get("flagged", True)
    db.commit()
    return {"success": True}


@router.get("/api/vendor/messages/unread-count")
def vendor_messages_unread(request: Request, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return JSONResponse({"success": False}, status_code=401)
    if _feature_disabled(db, "vendor_chat_enabled"):
        return {"count": 0}

    product_ids = [p.id for p in db.query(Product.id).filter(Product.retailer_id == admin.vendor_id).all()]
    if not product_ids:
        return {"count": 0}

    count = db.query(ProductChatMessage).filter(
        ProductChatMessage.product_id.in_(product_ids),
        ProductChatMessage.is_admin == False,
        ProductChatMessage.is_flagged == False,
    ).count()
    return {"count": count}


@router.get("/api/vendor/messages/{product_id}/ai-suggest")
def vendor_message_ai_suggest(product_id: str, request: Request, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return JSONResponse({"success": False}, status_code=401)
    if _feature_disabled(db, "vendor_chat_enabled"):
        return JSONResponse({"success": False, "message": "Vendor chat disabled"}, status_code=403)

    product = db.query(Product).filter(Product.id == product_id, Product.retailer_id == admin.vendor_id).first()
    if not product:
        return JSONResponse({"success": False}, status_code=404)

    messages = db.query(ProductChatMessage).filter(
        ProductChatMessage.product_id == product_id,
    ).order_by(ProductChatMessage.created_at.desc()).limit(10).all()

    conversation = "\n".join([
        f"{'Customer' if not m.is_admin else 'Vendor'}: {m.content[:200]}" for m in reversed(messages)
    ])

    prompt = f"""You are a vendor assistant for "{product.name}". Based on this customer conversation, suggest 3 possible short replies the vendor could send. Be helpful and professional.

Conversation:
{conversation}

Return JSON array of 3 reply strings."""

    try:
        from app.services.ai_service import get_ai_client, get_active_model, _call_llm_sync
        client, model = get_ai_client()
        result = _call_llm_sync(client, model, prompt, max_tokens=500)
        import json, re
        text = result.get("content", "")
        match = re.search(r'\[[\s\S]*\]', text)
        if match:
            suggestions = json.loads(match.group())
            return {"suggestions": suggestions[:3]}
    except Exception:
        pass

    return {"suggestions": [
        "Thanks for your message! Let me look into this for you.",
        "Hi! I'd be happy to help with any questions about this product.",
        "Thank you for reaching out. Is there anything specific you'd like to know?",
    ]}


@router.get("/api/vendor/messages/{product_id}/categorize")
def vendor_message_categorize(product_id: str, request: Request, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return JSONResponse({"success": False}, status_code=401)
    if _feature_disabled(db, "vendor_chat_enabled"):
        return JSONResponse({"success": False, "message": "Vendor chat disabled"}, status_code=403)

    messages = db.query(ProductChatMessage).filter(
        ProductChatMessage.product_id == product_id,
    ).order_by(ProductChatMessage.created_at.desc()).limit(5).all()

    if not messages:
        return {"category": "general", "priority": "low"}

    last_msg = messages[0].content.lower() if messages[0].content else ""
    text = " ".join([m.content.lower() for m in messages if m.content])

    # Rule-based categorization
    category = "general"
    priority = "low"
    if any(w in text for w in ["return", "refund", "money back", "broken", "damaged"]):
        category = "return_request"
        priority = "high"
    elif any(w in text for w in ["shipping", "delivery", "track", "where is", "when will"]):
        category = "shipping_inquiry"
        priority = "medium"
    elif any(w in text for w in ["quality", "defect", "wrong", "not as described"]):
        category = "complaint"
        priority = "high"
    elif any(w in text for w in ["size", "fit", "color", "material", "spec"]):
        category = "product_question"
        priority = "low"
    elif any(w in text for w in ["discount", "coupon", "sale", "price"]):
        category = "pricing_inquiry"
        priority = "low"

    return {"category": category, "priority": priority}


@router.post("/api/vendor/messages/{product_id}/escalate")
async def vendor_message_escalate(product_id: str, request: Request, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return JSONResponse({"success": False}, status_code=401)
    if _feature_disabled(db, "vendor_chat_enabled"):
        return JSONResponse({"success": False, "message": "Vendor chat disabled"}, status_code=403)

    product = db.query(Product).filter(Product.id == product_id, Product.retailer_id == admin.vendor_id).first()
    if not product:
        return JSONResponse({"success": False}, status_code=404)

    data = await request.json()
    reason = data.get("reason", "Vendor escalation")

    # Create admin notification
    from app.models import AdminNotification
    notif = AdminNotification(
        title="Vendor Chat Escalation",
        message=f"Vendor {admin.name} escalated chat for product '{product.name}': {reason}",
        type="warning",
    )
    db.add(notif)
    db.commit()
    return {"success": True}


# ═══════════════════════════════════════════════════════════════════════════════
# VENDOR PROMOTIONS (AI Discount/Coupon Engine)
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/vendor/promotions", response_class=HTMLResponse)
def vendor_promotions_page(request: Request, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return redirect
    return render_template("vendor/promotions.html", {
        "request": request,
        "admin": admin,
        "retailer": retailer,
        "has_permission": has_permission,
        "vendor_settings": _get_vendor_settings(db),
    })


@router.get("/api/vendor/promotions")
def vendor_promotions_list(request: Request, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return JSONResponse({"success": False}, status_code=401)

    promos = db.query(VendorPromotion).filter(VendorPromotion.retailer_id == admin.vendor_id).order_by(VendorPromotion.created_at.desc()).all()
    return {"promotions": [{
        "id": p.id,
        "title": p.title,
        "description": p.description,
        "discount_type": p.discount_type,
        "discount_value": p.discount_value,
        "promo_code": p.promo_code,
        "min_purchase": p.min_purchase,
        "usage_limit": p.usage_limit,
        "usage_count": p.usage_count,
        "start_date": p.start_date.isoformat() if p.start_date else None,
        "end_date": p.end_date.isoformat() if p.end_date else None,
        "is_active": p.is_active,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    } for p in promos]}


@router.post("/api/vendor/promotions/create")
async def vendor_create_promotion(request: Request, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return JSONResponse({"success": False}, status_code=401)

    data = await request.json()
    title = data.get("title", "").strip()
    if not title:
        return JSONResponse({"success": False, "detail": "Title required"}, status_code=400)

    promo = VendorPromotion(
        retailer_id=admin.vendor_id,
        title=title,
        description=data.get("description", ""),
        discount_type=data.get("discount_type", "percentage"),
        discount_value=data.get("discount_value", 10),
        promo_code=data.get("promo_code", "").strip().upper() or None,
        min_purchase=data.get("min_purchase", 0),
        usage_limit=data.get("usage_limit", 0),
        start_date=datetime.strptime(data["start_date"], "%Y-%m-%d").date() if data.get("start_date") else None,
        end_date=datetime.strptime(data["end_date"], "%Y-%m-%d").date() if data.get("end_date") else None,
        is_active=True,
    )
    db.add(promo)
    db.commit()
    return {"success": True, "promo_id": promo.id}


@router.post("/api/vendor/promotions/{promo_id}/toggle")
async def vendor_toggle_promotion(promo_id: str, request: Request, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return JSONResponse({"success": False}, status_code=401)

    promo = db.query(VendorPromotion).filter(VendorPromotion.id == promo_id, VendorPromotion.retailer_id == admin.vendor_id).first()
    if not promo:
        return JSONResponse({"success": False}, status_code=404)

    data = await request.json()
    promo.is_active = data.get("is_active", not promo.is_active)
    db.commit()
    return {"success": True, "is_active": promo.is_active}


@router.delete("/api/vendor/promotions/{promo_id}")
async def vendor_delete_promotion(promo_id: str, request: Request, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return JSONResponse({"success": False}, status_code=401)

    promo = db.query(VendorPromotion).filter(VendorPromotion.id == promo_id, VendorPromotion.retailer_id == admin.vendor_id).first()
    if not promo:
        return JSONResponse({"success": False}, status_code=404)

    db.delete(promo)
    db.commit()
    return {"success": True}


@router.put("/api/vendor/promotions/{promo_id}")
async def vendor_update_promotion(promo_id: str, request: Request, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return JSONResponse({"success": False}, status_code=401)

    promo = db.query(VendorPromotion).filter(VendorPromotion.id == promo_id, VendorPromotion.retailer_id == admin.vendor_id).first()
    if not promo:
        return JSONResponse({"success": False}, status_code=404)

    data = await request.json()
    if "title" in data: promo.title = data["title"]
    if "description" in data: promo.description = data["description"]
    if "discount_type" in data: promo.discount_type = data["discount_type"]
    if "discount_value" in data: promo.discount_value = data["discount_value"]
    if "promo_code" in data: promo.promo_code = data["promo_code"].strip().upper() or None
    if "min_purchase" in data: promo.min_purchase = data["min_purchase"]
    if "usage_limit" in data: promo.usage_limit = data["usage_limit"]
    if "start_date" in data: promo.start_date = datetime.strptime(data["start_date"], "%Y-%m-%d").date() if data["start_date"] else None
    if "end_date" in data: promo.end_date = datetime.strptime(data["end_date"], "%Y-%m-%d").date() if data["end_date"] else None
    db.commit()
    return {"success": True}


@router.get("/api/vendor/promotions/ai-suggestions")
async def vendor_promotion_suggestions(request: Request, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return JSONResponse({"success": False}, status_code=401)

    products = db.query(Product).filter(Product.retailer_id == admin.vendor_id).all()
    if not products:
        return {"suggestions": []}

    # Rule-based suggestions
    suggestions = []
    for p in products[:10]:
        if p.inventory > 20 and p.discount_price:
            suggestions.append({
                "product_id": p.id,
                "product_name": p.name,
                "type": "clearance",
                "title": f"Clearance: 20% off {p.name}",
                "reason": f"High inventory ({p.sold_count} units sold, {p.inventory} in stock)",
                "suggested_discount": 20,
                "priority": "high",
            })
        elif p.sold_count > 10:
            suggestions.append({
                "product_id": p.id,
                "product_name": p.name,
                "type": "bundle",
                "title": f"Bundle deal for {p.name}",
                "reason": f"Popular product ({p.sold_count} units sold)",
                "suggested_discount": 10,
                "priority": "medium",
            })

    # Try LLM insights
    try:
        from app.services.ai_service import get_ai_client, get_active_model
        client = get_ai_client()
        model = get_active_model()
        if client and model:
            product_data = [{"name": p.name, "price": float(p.price), "discount_price": float(p.discount_price) if p.discount_price else None, "inventory": p.inventory, "sold": p.sold_count} for p in products[:10]]
            import asyncio
            response = asyncio.wait_for(asyncio.to_thread(
                lambda: client.chat.completions.create(
                    model=model, max_tokens=2000,
                    messages=[{"role": "system", "content": "You are a retail pricing strategist. Suggest 3-5 promotions with discount_type (percentage/fixed/bogo), discount_value, promo_code, and reason. Return JSON array."},
                    {"role": "user", "content": f"Vendor products: {json.dumps(product_data)}. Suggest promotions."}]
                )), timeout=25)
            ai_content = response.choices[0].message.content
            # Try to parse JSON from response
            import re
            json_match = re.search(r'\[[\s\S]*\]', ai_content)
            if json_match:
                ai_suggestions = json.loads(json_match.group())
                for s in ai_suggestions[:5]:
                    suggestions.append({
                        "product_id": None,
                        "product_name": s.get("product_name", "All products"),
                        "type": s.get("type", "percentage"),
                        "title": s.get("title", s.get("promo_name", "Promotion")),
                        "reason": s.get("reason", "AI recommended"),
                        "suggested_discount": s.get("discount_value", s.get("discount", 15)),
                        "priority": "high",
                        "ai_generated": True,
                        "promo_code": s.get("promo_code", ""),
                    })
    except Exception:
        pass

    return {"suggestions": suggestions}


# ═══════════════════════════════════════════════════════════════════════════════
# VENDOR PERFORMANCE SCORE DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/vendor/performance", response_class=HTMLResponse)
def vendor_performance_page(request: Request, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return redirect
    return render_template("vendor/performance.html", {
        "request": request,
        "admin": admin,
        "retailer": retailer,
        "has_permission": has_permission,
        "vendor_settings": _get_vendor_settings(db),
    })


@router.get("/api/vendor/performance")
def vendor_performance_data(request: Request, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return JSONResponse({"success": False}, status_code=401)

    vendor_id = admin.vendor_id
    products = db.query(Product).filter(Product.retailer_id == vendor_id).all()
    product_ids = [p.id for p in products]
    order_items = db.query(OrderItem).filter(OrderItem.product_id.in_(product_ids)).all() if product_ids else []
    order_ids = list(set(oi.order_id for oi in order_items))
    orders = db.query(Order).filter(Order.id.in_(order_ids)).all() if order_ids else []
    reviews = db.query(Review).join(Product).filter(Product.retailer_id == vendor_id).all()

    # Order metrics
    total_orders = len(orders)
    completed_orders = [o for o in orders if o.status.value in ("DELIVERED",)]
    completed_ids = [o.id for o in completed_orders]
    shipments = db.query(Shipment).filter(Shipment.order_id.in_(completed_ids)).all() if completed_ids else []
    delivery_map = {s.order_id: s.actual_delivery for s in shipments if s.actual_delivery}
    on_time = sum(1 for o in completed_orders if delivery_map.get(o.id) and o.created_at and (delivery_map[o.id] - o.created_at).days <= 7)
    on_time_rate = (on_time / len(completed_orders) * 100) if completed_orders else 0
    fulfillment_rate = (len(completed_orders) / total_orders * 100) if total_orders else 0

    # Review metrics
    avg_rating = round(sum(r.rating for r in reviews) / len(reviews), 2) if reviews else 0
    positive_reviews = sum(1 for r in reviews if r.rating >= 4)
    positive_rate = (positive_reviews / len(reviews) * 100) if reviews else 0

    # Inventory metrics
    total_products = len(products)
    in_stock = sum(1 for p in products if p.inventory > 0)
    stock_rate = (in_stock / total_products * 100) if total_products else 0

    # Revenue
    total_revenue = sum(float(o.total_amount or 0) for o in completed_orders)
    avg_order_value = total_revenue / len(completed_orders) if completed_orders else 0

    # Composite score: fulfillment (30%) + rating (30%) + on-time (20%) + stock (20%)
    score = round(
        fulfillment_rate * 0.3 +
        min(avg_rating / 5 * 100, 100) * 0.3 +
        on_time_rate * 0.2 +
        stock_rate * 0.2,
        1
    )

    return {
        "score": score,
        "fulfillment_rate": round(fulfillment_rate, 1),
        "on_time_rate": round(on_time_rate, 1),
        "avg_rating": avg_rating,
        "positive_rate": round(positive_rate, 1),
        "stock_rate": round(stock_rate, 1),
        "total_orders": total_orders,
        "completed_orders": len(completed_orders),
        "total_revenue": round(total_revenue, 2),
        "avg_order_value": round(avg_order_value, 2),
        "total_products": total_products,
        "in_stock": in_stock,
        "total_reviews": len(reviews),
        "benchmark": _compute_benchmark(db, fulfillment_rate, on_time_rate, avg_rating, stock_rate),
    }


def _compute_benchmark(db, fulfillment, on_time, rating, stock):
    """Compute platform averages for benchmarking."""
    try:
        vendor_ids = [v[0] for v in db.query(Product.retailer_id).distinct().all() if v[0]]
        if not vendor_ids:
            return {"platform_avg_score": 0, "vendor_count": 0, "percentile": 0}

        scores = []
        for vid in vendor_ids[:50]:
            vproducts = db.query(Product).filter(Product.retailer_id == vid).all()
            vpids = [p.id for p in vproducts]
            voi = db.query(OrderItem).filter(OrderItem.product_id.in_(vpids)).all() if vpids else []
            vo_ids = list(set(oi.order_id for oi in voi))
            vo = db.query(Order).filter(Order.id.in_(vo_ids)).all() if vo_ids else []
            vc = [o for o in vo if o.status.value in ("DELIVERED",)]
            vfr = (len(vc) / len(vo) * 100) if vo else 0
            vrevs = db.query(Review).join(Product).filter(Product.retailer_id == vid).all()
            vr = round(sum(r.rating for r in vrevs) / len(vrevs), 2) if vrevs else 0
            vs = round(vfr * 0.3 + min(vr / 5 * 100, 100) * 0.3 + 50 * 0.2 + 90 * 0.2, 1)
            scores.append(vs)

        scores.sort()
        my_score = fulfillment * 0.3 + min(rating / 5 * 100, 100) * 0.3 + on_time * 0.2 + stock * 0.2
        platform_avg = round(sum(scores) / len(scores), 1) if scores else 0
        percentile = round(sum(1 for s in scores if s < my_score) / len(scores) * 100) if scores else 0

        return {
            "platform_avg_score": platform_avg,
            "vendor_count": len(vendor_ids),
            "percentile": percentile,
            "my_score": round(my_score, 1),
        }
    except Exception:
        return {"platform_avg_score": 0, "vendor_count": 0, "percentile": 0}


@router.get("/api/vendor/performance/ai-recommendations")
async def vendor_performance_recommendations(request: Request, db: Session = Depends(get_db)):
    admin, retailer, redirect = _require_retailer(request, db)
    if redirect:
        return JSONResponse({"success": False}, status_code=401)

    # Get performance data
    perf_resp = vendor_performance_data(request, db)
    perf = perf_resp

    # Rule-based recommendations
    recs = []
    if perf["fulfillment_rate"] < 80:
        recs.append({"area": "Fulfillment", "priority": "high", "text": f"Your fulfillment rate is {perf['fulfillment_rate']}%. Process orders faster and communicate delays proactively.", "action": "Improve fulfillment workflow"})
    if perf["on_time_rate"] < 70:
        recs.append({"area": "Delivery", "priority": "high", "text": f"On-time delivery is {perf['on_time_rate']}%. Optimize shipping routes or adjust estimated delivery times.", "action": "Review shipping process"})
    if perf["avg_rating"] < 4.0:
        recs.append({"area": "Quality", "priority": "medium", "text": f"Average rating is {perf['avg_rating']}/5. Review negative feedback and improve product quality.", "action": "Analyze negative reviews"})
    if perf["stock_rate"] < 90:
        recs.append({"area": "Inventory", "priority": "medium", "text": f"Stock rate is {perf['stock_rate']}%. Restock popular items to avoid lost sales.", "action": "Review inventory levels"})
    if perf["total_orders"] < 10:
        recs.append({"area": "Growth", "priority": "low", "text": "Low order volume. Consider promotions, ads, or social media marketing to attract more customers.", "action": "Launch marketing campaign"})

    # Try LLM recommendations
    try:
        from app.services.ai_service import get_ai_client, get_active_model
        client = get_ai_client()
        model = get_active_model()
        if client and model:
            import asyncio
            response = asyncio.wait_for(asyncio.to_thread(
                lambda: client.chat.completions.create(
                    model=model, max_tokens=2000,
                    messages=[{"role": "system", "content": "You are a vendor performance advisor. Given metrics, give 3-5 specific actionable recommendations. Return JSON array with 'area', 'priority' (high/medium/low), 'text', 'action'."},
                    {"role": "user", "content": json.dumps(perf)}]
                )), timeout=25)
            ai_content = response.choices[0].message.content
            import re
            json_match = re.search(r'\[[\s\S]*\]', ai_content)
            if json_match:
                ai_recs = json.loads(json_match.group())
                for r in ai_recs[:5]:
                    recs.append({
                        "area": r.get("area", "General"),
                        "priority": r.get("priority", "medium"),
                        "text": r.get("text", ""),
                        "action": r.get("action", ""),
                        "ai_generated": True,
                    })
    except Exception:
        pass

    return {"recommendations": recs}
