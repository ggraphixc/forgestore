"""
Daily Analytics Materialization — compile pre-computed marketplace + vendor snapshots.

Usage:
    python -m app.scripts.compile_daily_analytics

Creates DailyMarketplaceSnapshot and DailyVendorSnapshot rows for the prior 24 hours.
These flat summary tables power dashboard reads without expensive real-time aggregation.
"""
import sys
import os
from datetime import timedelta, datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.database import SessionLocal, get_engine, Base
from app.models import (
    DailyMarketplaceSnapshot, DailyVendorSnapshot, Order, OrderItem, OrderStatus,
    Retailer, VendorSettlement, OrderDispute, User, Product,
)
from app.services.ai_service import SETTINGS_DEFINITIONS
from app.models import Settings
from app.utils import utcnow


def compile_daily_analytics():
    """Compute and insert analytics snapshots for the prior day."""
    db = SessionLocal()

    print("=" * 60)
    print("  DAILY ANALYTICS COMPILATION")
    print("=" * 60)

    now = utcnow()
    # Prior day window
    day_start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)

    # Check if already compiled
    existing = db.query(DailyMarketplaceSnapshot).filter(
        DailyMarketplaceSnapshot.date == day_start
    ).first()
    if existing:
        print(f"  Snapshot for {day_start.date()} already exists — skipping")
        db.close()
        return

    # ── Marketplace-wide metrics ──
    print(f"\n  Computing marketplace metrics for {day_start.date()}...")

    orders = db.query(Order).filter(
        Order.created_at >= day_start,
        Order.created_at < day_end,
    ).all()

    total_revenue = sum(o.total_amount for o in orders)
    total_orders = len(orders)

    # Commission from settlements
    settlements = db.query(VendorSettlement).filter(
        VendorSettlement.created_at >= day_start,
        VendorSettlement.created_at < day_end,
    ).all()
    total_commissions = sum(s.platform_commission_fee for s in settlements)

    # Active vendors (had at least one order)
    active_vendor_ids = set()
    for o in orders:
        items = db.query(OrderItem).filter(OrderItem.order_id == o.id).all()
        for item in items:
            product = db.query(Product).filter(Product.id == item.product_id).first()
            if product and product.retailer_id:
                active_vendor_ids.add(product.retailer_id)

    # Disputes
    disputes = db.query(OrderDispute).filter(
        OrderDispute.created_at >= day_start,
        OrderDispute.created_at < day_end,
    ).count()

    # New customers
    new_customers = db.query(User).filter(
        User.created_at >= day_start,
        User.created_at < day_end,
    ).count()

    # Products sold
    products_sold = sum(item.quantity for o in orders for item in
                        db.query(OrderItem).filter(OrderItem.order_id == o.id).all())

    avg_order_value = total_revenue / total_orders if total_orders > 0 else 0

    marketplace_snapshot = DailyMarketplaceSnapshot(
        date=day_start,
        total_revenue=round(total_revenue, 2),
        total_orders=total_orders,
        total_commissions_earned=round(total_commissions, 2),
        total_active_vendors=len(active_vendor_ids),
        total_dispute_count=disputes,
        total_new_customers=new_customers,
        total_products_sold=products_sold,
        avg_order_value=round(avg_order_value, 2),
    )
    db.add(marketplace_snapshot)

    # ── Per-vendor metrics ──
    print(f"  Computing per-vendor metrics...")

    vendor_revenue = {}
    vendor_orders = {}
    vendor_products_sold = {}
    vendor_commissions = {}

    for o in orders:
        items = db.query(OrderItem).filter(OrderItem.order_id == o.id).all()
        for item in items:
            product = db.query(Product).filter(Product.id == item.product_id).first()
            if product and product.retailer_id:
                rid = product.retailer_id
                vendor_revenue[rid] = vendor_revenue.get(rid, 0) + (item.price * item.quantity)
                vendor_orders[rid] = vendor_orders.get(rid, 0) + 1
                vendor_products_sold[rid] = vendor_products_sold.get(rid, 0) + item.quantity

    for s in settlements:
        rid = s.retailer_id
        vendor_commissions[rid] = vendor_commissions.get(rid, 0) + s.platform_commission_fee

    # Disputes per vendor
    vendor_disputes = {}
    for d in db.query(OrderDispute).filter(
        OrderDispute.created_at >= day_start,
        OrderDispute.created_at < day_end,
        OrderDispute.retailer_id.isnot(None),
    ).all():
        rid = d.retailer_id
        vendor_disputes[rid] = vendor_disputes.get(rid, 0) + 1

    for rid in set(list(vendor_revenue.keys()) + list(vendor_commissions.keys())):
        rev = vendor_revenue.get(rid, 0)
        comm = vendor_commissions.get(rid, 0)
        vendor_snapshot = DailyVendorSnapshot(
            date=day_start,
            retailer_id=rid,
            revenue=round(rev, 2),
            orders_count=vendor_orders.get(rid, 0),
            products_sold=vendor_products_sold.get(rid, 0),
            commission_paid=round(comm, 2),
            net_earnings=round(rev - comm, 2),
            dispute_count=vendor_disputes.get(rid, 0),
        )
        db.add(vendor_snapshot)

    db.commit()

    print(f"  Marketplace snapshot: ₦{total_revenue:,.2f} revenue, {total_orders} orders")
    print(f"  Vendor snapshots: {len(set(list(vendor_revenue.keys()) + list(vendor_commissions.keys())))} vendors")
    print(f"  Commissions: ₦{total_commissions:,.2f}")
    print(f"  Disputes: {disputes}")
    print(f"  New customers: {new_customers}")
    print("=" * 60)

    db.close()


if __name__ == "__main__":
    compile_daily_analytics()
