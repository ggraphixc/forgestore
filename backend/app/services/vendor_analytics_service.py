"""Advanced Vendor Dashboard — System 2"""
import logging
from datetime import datetime
from datetime import timedelta
from app.utils import utcnow
from app.utils import utcnow
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, extract

from app.models import (
    Retailer, Product, Order, OrderItem, User,
    VendorAnalytics, VendorPayout, VendorActivityLog, VendorPerformanceCache,
)

logger = logging.getLogger("forgestore.vendor")


class VendorAnalyticsService:
    """Vendor analytics and metrics computation."""

    def __init__(self, db: Session):
        self.db = db

    def get_dashboard_data(self, retailer_id: str, days: int = 30) -> dict:
        """Get comprehensive dashboard data for a vendor."""
        now = utcnow()
        period_start = now - timedelta(days=days)

        # Revenue metrics
        revenue_data = self._compute_revenue(retailer_id, period_start)
        product_data = self._compute_product_performance(retailer_id, period_start)
        customer_data = self._compute_customer_metrics(retailer_id, period_start)
        conversion_data = self._compute_conversion_metrics(retailer_id, period_start)

        return {
            "revenue": revenue_data,
            "products": product_data,
            "customers": customer_data,
            "conversions": conversion_data,
            "period": {"start": period_start.isoformat(), "end": now.isoformat(), "days": days},
        }

    def _compute_revenue(self, retailer_id: str, period_start: datetime) -> dict:
        """Compute revenue metrics."""
        items = self.db.query(OrderItem).join(Product).filter(
            Product.retailer_id == retailer_id,
            OrderItem.created_at >= period_start,
        ).all()

        total_revenue = sum(i.price * i.quantity for i in items)
        total_orders = len(set(i.order_id for i in items))
        total_items = sum(i.quantity for i in items)
        avg_order_value = round(total_revenue / total_orders, 2) if total_orders else 0

        # Get previous period for comparison
        prev_start = period_start - timedelta(days=(utcnow() - period_start).days)
        prev_items = self.db.query(OrderItem).join(Product).filter(
            Product.retailer_id == retailer_id,
            OrderItem.created_at >= prev_start,
            OrderItem.created_at < period_start,
        ).all()
        prev_revenue = sum(i.price * i.quantity for i in prev_items)

        revenue_change = 0
        if prev_revenue > 0:
            revenue_change = round(((total_revenue - prev_revenue) / prev_revenue) * 100, 1)

        # Daily revenue breakdown
        daily = {}
        for item in items:
            day = item.created_at.strftime("%Y-%m-%d")
            daily[day] = daily.get(day, 0) + item.price * item.quantity

        return {
            "total_revenue": round(total_revenue, 2),
            "total_orders": total_orders,
            "total_items_sold": total_items,
            "avg_order_value": avg_order_value,
            "revenue_change_percent": revenue_change,
            "daily_revenue": [{"date": d, "amount": round(a, 2)} for d, a in sorted(daily.items())],
        }

    def _compute_product_performance(self, retailer_id: str, period_start: datetime) -> dict:
        """Compute product performance metrics."""
        products = self.db.query(Product).filter(
            Product.retailer_id == retailer_id,
        ).all()

        product_stats = []
        for product in products:
            items = self.db.query(OrderItem).filter(
                OrderItem.product_id == product.id,
                OrderItem.created_at >= period_start,
            ).all()
            sold = sum(i.quantity for i in items)
            revenue = sum(i.price * i.quantity for i in items)

            product_stats.append({
                "id": product.id,
                "name": product.name,
                "slug": product.slug,
                "price": product.price,
                "inventory": product.inventory,
                "units_sold": sold,
                "revenue": round(revenue, 2),
                "rating": product.rating,
                "review_count": product.review_count,
                "conversion_rate": round((sold / max(product.inventory + sold, 1)) * 100, 1),
            })

        product_stats.sort(key=lambda x: x["revenue"], reverse=True)

        return {
            "total_products": len(products),
            "active_products": sum(1 for p in products if p.inventory > 0),
            "out_of_stock": sum(1 for p in products if p.inventory == 0),
            "top_performers": product_stats[:5],
            "low_performers": product_stats[-5:] if len(product_stats) >= 5 else [],
        }

    def _compute_customer_metrics(self, retailer_id: str, period_start: datetime) -> dict:
        """Compute customer analytics."""
        items = self.db.query(OrderItem).join(Product).filter(
            Product.retailer_id == retailer_id,
            OrderItem.created_at >= period_start,
        ).all()

        # Get unique customers from orders
        order_ids = list(set(i.order_id for i in items))
        orders = self.db.query(Order).filter(Order.id.in_(order_ids)).all()
        customer_ids = list(set(o.customer_id for o in orders))
        total_customers = len(customer_ids)

        # Repeat customers
        customer_order_counts = {}
        for o in orders:
            customer_order_counts[o.customer_id] = customer_order_counts.get(o.customer_id, 0) + 1
        repeat_customers = sum(1 for c in customer_order_counts.values() if c > 1)

        return {
            "total_customers": total_customers,
            "new_customers": total_customers,
            "repeat_customers": repeat_customers,
            "repeat_rate": round((repeat_customers / max(total_customers, 1)) * 100, 1),
        }

    def _compute_conversion_metrics(self, retailer_id: str, period_start: datetime) -> dict:
        """Compute conversion and operational metrics."""
        # Views from vendor analytics if available
        vendor_analytics = self.db.query(VendorAnalytics).filter(
            VendorAnalytics.retailer_id == retailer_id,
            VendorAnalytics.period_start >= period_start,
        ).all()

        total_views = sum(v.page_views for v in vendor_analytics)
        total_orders = sum(v.total_orders for v in vendor_analytics)
        total_revenue = sum(v.total_revenue for v in vendor_analytics)

        conversion_rate = round((total_orders / max(total_views, 1)) * 100, 2) if total_views else 0

        return {
            "total_page_views": total_views,
            "total_orders": total_orders,
            "conversion_rate": conversion_rate,
            "revenue_per_visit": round(total_revenue / max(total_views, 1), 2) if total_views else 0,
        }

    def get_inventory_forecast(self, retailer_id: str) -> list[dict]:
        """Simple inventory forecasting based on sales velocity."""
        products = self.db.query(Product).filter(
            Product.retailer_id == retailer_id,
        ).all()

        forecasts = []
        for product in products:
            # Calculate sales velocity (7-day average)
            week_ago = utcnow() - timedelta(days=7)
            recent_sales = self.db.query(func.sum(OrderItem.quantity)).filter(
                OrderItem.product_id == product.id,
                OrderItem.created_at >= week_ago,
            ).scalar() or 0

            daily_rate = recent_sales / 7
            days_until_out = int(product.inventory / max(daily_rate, 0.01)) if daily_rate > 0 else 999

            forecasts.append({
                "product_id": product.id,
                "product_name": product.name,
                "current_inventory": max(0, product.inventory),
                "daily_sales_rate": round(daily_rate, 2),
                "days_until_out": days_until_out,
                "restock_recommended": days_until_out <= 14,
                "rating": product.rating,
            })

        forecasts.sort(key=lambda x: x["days_until_out"])
        return forecasts


class VendorPayoutService:
    """Manages vendor payouts and commission tracking."""

    def __init__(self, db: Session):
        self.db = db

    def calculate_payout(self, retailer_id: str, period_start: datetime, period_end: datetime) -> dict:
        """Calculate payout for a vendor for a given period."""
        items = self.db.query(OrderItem).join(Product).filter(
            Product.retailer_id == retailer_id,
            OrderItem.created_at >= period_start,
            OrderItem.created_at <= period_end,
        ).all()

        gross_revenue = sum(i.price * i.quantity for i in items)
        platform_fee = round(gross_revenue * 0.05, 2)  # 5% platform fee
        net_amount = round(gross_revenue - platform_fee, 2)

        return {
            "retailer_id": retailer_id,
            "period_start": period_start,
            "period_end": period_end,
            "gross_revenue": round(gross_revenue, 2),
            "platform_fee": platform_fee,
            "net_amount": net_amount,
        }

    def create_payout(self, retailer_id: str, amount: float, platform_fee: float,
                      period_start: Optional[datetime] = None,
                      period_end: Optional[datetime] = None) -> VendorPayout:
        """Create a payout for a vendor."""
        payout = VendorPayout(
            retailer_id=retailer_id,
            amount=amount,
            fee=platform_fee,
            net_amount=amount - platform_fee,
            status="PENDING",
            period_start=period_start,
            period_end=period_end,
        )
        self.db.add(payout)
        self.db.commit()
        self.db.refresh(payout)
        return payout

    def process_payout(self, payout_id: str, payment_method: str, payment_reference: str) -> VendorPayout:
        """Process a payout."""
        payout = self.db.query(VendorPayout).filter(VendorPayout.id == payout_id).first()
        if not payout:
            raise ValueError("Payout not found")

        payout.status = "COMPLETED"
        payout.payment_method = payment_method
        payout.payment_reference = payment_reference
        payout.processed_at = utcnow()
        self.db.commit()
        self.db.refresh(payout)
        return payout

    def get_payout_history(self, retailer_id: str, limit: int = 20) -> list[VendorPayout]:
        """Get payout history for a vendor."""
        return self.db.query(VendorPayout).filter(
            VendorPayout.retailer_id == retailer_id
        ).order_by(VendorPayout.created_at.desc()).limit(limit).all()

    def get_pending_payouts(self) -> list[VendorPayout]:
        """Get all pending payouts."""
        return self.db.query(VendorPayout).filter(
            VendorPayout.status == "PENDING"
        ).order_by(VendorPayout.created_at.asc()).all()


class VendorMetricsService:
    """Vendor performance tracking and caching."""

    def __init__(self, db: Session):
        self.db = db

    def log_activity(self, retailer_id: str, action: str,
                     resource_type: Optional[str] = None,
                     resource_id: Optional[str] = None,
                     details: Optional[dict] = None):
        """Log vendor activity."""
        log = VendorActivityLog(
            retailer_id=retailer_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details or {},
        )
        self.db.add(log)
        self.db.commit()

    def get_activity_feed(self, retailer_id: str, limit: int = 20) -> list[VendorActivityLog]:
        """Get recent activity for a vendor."""
        return self.db.query(VendorActivityLog).filter(
            VendorActivityLog.retailer_id == retailer_id
        ).order_by(VendorActivityLog.created_at.desc()).limit(limit).all()

    def cache_performance(self, retailer_id: str, cache_key: str, data: dict, ttl_hours: int = 1):
        """Cache performance data with TTL."""
        expires_at = utcnow() + timedelta(hours=ttl_hours)

        cached = self.db.query(VendorPerformanceCache).filter(
            VendorPerformanceCache.retailer_id == retailer_id,
            VendorPerformanceCache.cache_key == cache_key,
        ).first()

        if cached:
            cached.cache_data = data
            cached.expires_at = expires_at
        else:
            cached = VendorPerformanceCache(
                retailer_id=retailer_id,
                cache_key=cache_key,
                cache_data=data,
                expires_at=expires_at,
            )
            self.db.add(cached)

        self.db.commit()

    def get_performance_cache(self, retailer_id: str, cache_key: str) -> Optional[dict]:
        """Get cached performance data if not expired."""
        cached = self.db.query(VendorPerformanceCache).filter(
            VendorPerformanceCache.retailer_id == retailer_id,
            VendorPerformanceCache.cache_key == cache_key,
        ).first()

        if cached and cached.expires_at and cached.expires_at > utcnow():
            return cached.cache_data
        return None
