"""Enterprise Commerce Intelligence Dashboard — System 10"""
import logging
import json
from datetime import datetime
from datetime import timedelta
from app.utils import utcnow
from app.utils import utcnow
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, extract

from app.models import (
    Order, OrderItem, Product, User, Retailer, Category,
    AnalyticsSnapshot, CustomerLifetimeValue, FraudDetectionEvent, PredictiveForecast,
)

logger = logging.getLogger("forgestore.analytics")


class AnalyticsService:
    """Core analytics aggregation and reporting."""

    def __init__(self, db: Session):
        self.db = db

    def compute_snapshot(self, snapshot_type: str = "daily") -> AnalyticsSnapshot:
        """Compute and store an analytics snapshot."""
        now = utcnow()
        if snapshot_type == "daily":
            period_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            period_end = period_start + timedelta(days=1)
        elif snapshot_type == "weekly":
            period_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
            period_end = period_start + timedelta(days=7)
        elif snapshot_type == "monthly":
            period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            if period_start.month == 12:
                period_end = period_start.replace(year=period_start.year + 1, month=1)
            else:
                period_end = period_start.replace(month=period_start.month + 1)
        else:
            raise ValueError(f"Invalid snapshot type: {snapshot_type}")

        # Compute metrics
        orders = self.db.query(Order).filter(
            Order.created_at >= period_start,
            Order.created_at < period_end,
        ).all()

        total_revenue = sum(o.total_amount for o in orders)
        total_orders = len(orders)
        total_customers = len(set(o.customer_id for o in orders))
        avg_order_value = round(total_revenue / max(total_orders, 1), 2)

        # Product metrics
        items = self.db.query(OrderItem).filter(
            OrderItem.created_at >= period_start,
            OrderItem.created_at < period_end,
        ).all()
        total_products_sold = sum(i.quantity for i in items)

        # New customers
        new_customers = self.db.query(User).filter(
            User.created_at >= period_start,
            User.created_at < period_end,
        ).count()

        data = {
            "revenue": {
                "total": round(total_revenue, 2),
                "avg_order_value": avg_order_value,
                "orders": total_orders,
            },
            "customers": {
                "total_active": total_customers,
                "new": new_customers,
                "products_sold": total_products_sold,
            },
            "timestamp": now.isoformat(),
        }

        snapshot = AnalyticsSnapshot(
            snapshot_type=snapshot_type,
            period_start=period_start,
            period_end=period_end,
            data=data,
        )
        self.db.add(snapshot)
        self.db.commit()
        self.db.refresh(snapshot)
        return snapshot

    def get_revenue_metrics(self, days: int = 30) -> dict:
        """Get revenue metrics for the specified period."""
        now = utcnow()
        start = now - timedelta(days=days)

        orders = self.db.query(Order).filter(
            Order.created_at >= start,
        ).all()

        # Daily revenue breakdown
        daily = {}
        status_counts = {}
        for o in orders:
            day = o.created_at.strftime("%Y-%m-%d")
            daily[day] = daily.get(day, 0) + o.total_amount
            status_counts[o.status.value] = status_counts.get(o.status.value, 0) + 1

        return {
            "total_revenue": round(sum(o.total_amount for o in orders), 2),
            "total_orders": len(orders),
            "avg_order_value": round(sum(o.total_amount for o in orders) / max(len(orders), 1), 2),
            "daily_revenue": [{"date": d, "amount": round(a, 2)} for d, a in sorted(daily.items())],
            "orders_by_status": [{"status": k, "count": v} for k, v in status_counts.items()],
        }

    def get_customer_metrics(self) -> dict:
        """Get customer-related metrics."""
        total_customers = self.db.query(User).count()
        orders = self.db.query(Order).all()

        customer_order_counts = {}
        for o in orders:
            customer_order_counts[o.customer_id] = customer_order_counts.get(o.customer_id, 0) + 1

        repeat_customers = sum(1 for c in customer_order_counts.values() if c > 1)

        return {
            "total_customers": total_customers,
            "repeat_customers": repeat_customers,
            "repeat_rate": round((repeat_customers / max(total_customers, 1)) * 100, 1),
            "total_orders": len(orders),
        }


class ForecastService:
    """Predictive forecasting engine for revenue, orders, and customers."""

    def __init__(self, db: Session):
        self.db = db

    def forecast_revenue(self, days_ahead: int = 30) -> list[dict]:
        """Generate revenue forecast using historical data and simple projection."""
        now = utcnow()
        historical_days = max(days_ahead * 3, 90)
        start = now - timedelta(days=historical_days)

        # Get historical daily revenue
        orders = self.db.query(Order).filter(
            Order.created_at >= start,
        ).all()

        daily_revenue = {}
        for o in orders:
            day = o.created_at.strftime("%Y-%m-%d")
            daily_revenue[day] = daily_revenue.get(day, 0) + o.total_amount

        if not daily_revenue:
            return []

        # Calculate average daily revenue and trend
        values = list(daily_revenue.values())
        avg_daily = sum(values) / max(len(values), 1)
        recent_avg = sum(values[-7:]) / max(min(len(values), 7), 1)
        trend_factor = recent_avg / max(avg_daily, 0.01)

        forecasts = []
        for i in range(1, days_ahead + 1):
            forecast_date = now + timedelta(days=i)
            predicted = recent_avg * (1 + (trend_factor - 1) * (i / days_ahead))
            # Add confidence decay over time
            confidence = max(0.3, 0.95 - (i * 0.02))

            forecast = PredictiveForecast(
                forecast_type="revenue",
                period="daily",
                forecast_date=forecast_date,
                predicted_value=round(predicted, 2),
                lower_bound=round(predicted * 0.8, 2),
                upper_bound=round(predicted * 1.2, 2),
                confidence=round(confidence, 2),
                model="trend_projection_v1",
            )
            self.db.add(forecast)
            forecasts.append({
                "date": forecast_date.isoformat(),
                "predicted": round(predicted, 2),
                "lower_bound": round(predicted * 0.8, 2),
                "upper_bound": round(predicted * 1.2, 2),
                "confidence": round(confidence, 2),
            })

        self.db.commit()
        return forecasts


class FraudDetectionService:
    """Fraud detection engine using rule-based and behavioral analysis."""

    def __init__(self, db: Session):
        self.db = db

    def analyze_order(self, order_id: str) -> Optional[FraudDetectionEvent]:
        """Analyze an order for potential fraud indicators."""
        order = self.db.query(Order).filter(Order.id == order_id).first()
        if not order:
            return None

        indicators = []
        risk_score = 0.0

        # Check 1: Rapid orders from same customer
        recent_orders = self.db.query(Order).filter(
            Order.customer_id == order.customer_id,
            Order.id != order_id,
            Order.created_at >= utcnow() - timedelta(hours=1),
        ).count()
        if recent_orders >= 3:
            indicators.append({
                "type": "rapid_orders",
                "detail": f"{recent_orders} orders in the last hour",
                "weight": 0.3,
            })
            risk_score += 0.3

        # Check 2: High-value order
        if order.total_amount > 100000:
            indicators.append({
                "type": "high_value",
                "detail": f"Order value: ₦{order.total_amount:,.2f}",
                "weight": 0.2,
            })
            risk_score += 0.2

        # Check 3: New customer with large order
        customer = self.db.query(User).filter(User.id == order.customer_id).first()
        if customer:
            days_since_signup = (utcnow() - customer.created_at).days
            if days_since_signup <= 1 and order.total_amount > 50000:
                indicators.append({
                    "type": "new_account_large_order",
                    "detail": f"Account age: {days_since_signup} days, Order: ₦{order.total_amount:,.2f}",
                    "weight": 0.4,
                })
                risk_score += 0.4

        if risk_score < 0.3:
            return None

        event = FraudDetectionEvent(
            event_type="order_review",
            order_id=order_id,
            user_id=order.customer_id,
            score=min(1.0, risk_score),
            indicators=indicators,
            action_taken="flagged" if risk_score > 0.5 else "reviewed",
        )
        self.db.add(event)
        self.db.commit()
        self.db.refresh(event)
        return event


class InsightGenerationService:
    """AI-powered business insight generation."""

    def __init__(self, db: Session):
        self.db = db

    def generate_insights(self) -> list[dict]:
        """Generate AI insights from current analytics data."""
        now = utcnow()
        insights = []

        # Insight 1: Revenue trend
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday_start = today_start - timedelta(days=1)

        today_revenue = self.db.query(func.sum(Order.total_amount)).filter(
            Order.created_at >= today_start,
        ).scalar() or 0
        yesterday_revenue = self.db.query(func.sum(Order.total_amount)).filter(
            Order.created_at >= yesterday_start,
            Order.created_at < today_start,
        ).scalar() or 0

        if yesterday_revenue > 0:
            change = ((today_revenue - yesterday_revenue) / yesterday_revenue) * 100
            insights.append({
                "type": "revenue_trend",
                "title": "Revenue Trend",
                "message": f"Revenue is {'up' if change > 0 else 'down'} {abs(change):.1f}% compared to yesterday.",
                "severity": "positive" if change > 0 else "negative",
                "value": round(change, 1),
                "generated_at": now.isoformat(),
            })

        # Insight 2: Top category performance
        top_category = self.db.query(
            Category.name,
            func.sum(OrderItem.quantity).label("total_sold"),
        ).join(Product, Product.category_id == Category.id
        ).join(OrderItem, OrderItem.product_id == Product.id
        ).filter(
            OrderItem.created_at >= today_start - timedelta(days=7),
        ).group_by(Category.name).order_by(
            desc("total_sold")
        ).first()

        if top_category:
            insights.append({
                "type": "top_category",
                "title": "Top Performing Category",
                "message": f"'{top_category[0]}' is the best-selling category this week with {top_category[1]} units sold.",
                "severity": "positive",
                "value": top_category[1],
                "generated_at": now.isoformat(),
            })

        # Insight 3: Customer growth
        week_ago = now - timedelta(days=7)
        new_customers = self.db.query(User).filter(
            User.created_at >= week_ago,
        ).count()

        insights.append({
            "type": "customer_growth",
            "title": "Customer Growth",
            "message": f"{new_customers} new customers joined in the last 7 days.",
            "severity": "positive" if new_customers > 0 else "neutral",
            "value": new_customers,
            "generated_at": now.isoformat(),
        })

        # Insight 4: Low stock alert
        low_stock = self.db.query(Product).filter(
            Product.inventory > 0,
            Product.inventory <= 5,
        ).count()
        if low_stock > 0:
            insights.append({
                "type": "low_stock_alert",
                "title": "Low Stock Alert",
                "message": f"{low_stock} products are running low on stock (≤5 units remaining).",
                "severity": "warning",
                "value": low_stock,
                "generated_at": now.isoformat(),
            })

        # Insight 5: Pending orders
        pending_orders = self.db.query(Order).filter(
            Order.status == "PENDING",
        ).count()
        if pending_orders > 0:
            insights.append({
                "type": "pending_orders",
                "title": "Pending Orders",
                "message": f"There are {pending_orders} orders awaiting processing.",
                "severity": "info",
                "value": pending_orders,
                "generated_at": now.isoformat(),
            })

        return insights
