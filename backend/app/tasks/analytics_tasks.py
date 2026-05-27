"""Celery tasks for analytics, forecasting, and insight generation."""
import logging
from datetime import datetime
from datetime import timedelta
from app.utils import utcnow
from app.utils import utcnow

from app.core.celery_app import celery_app
from app.database import SessionLocal

logger = logging.getLogger("forgestore.tasks.analytics")


@celery_app.task
def compute_daily_snapshot():
    """Compute and store the daily analytics snapshot."""
    try:
        from app.services.analytics_service import AnalyticsService
        db = SessionLocal()
        try:
            analytics = AnalyticsService(db)
            snapshot = analytics.compute_snapshot("daily")
            logger.info(f"Computed daily analytics snapshot {snapshot.id}")
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Failed to compute daily snapshot: {e}")


@celery_app.task
def compute_weekly_snapshot():
    """Compute and store the weekly analytics snapshot."""
    try:
        from app.services.analytics_service import AnalyticsService
        db = SessionLocal()
        try:
            analytics = AnalyticsService(db)
            snapshot = analytics.compute_snapshot("weekly")
            logger.info(f"Computed weekly analytics snapshot {snapshot.id}")
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Failed to compute weekly snapshot: {e}")


@celery_app.task
def compute_monthly_snapshot():
    """Compute and store the monthly analytics snapshot."""
    try:
        from app.services.analytics_service import AnalyticsService
        db = SessionLocal()
        try:
            analytics = AnalyticsService(db)
            snapshot = analytics.compute_snapshot("monthly")
            logger.info(f"Computed monthly analytics snapshot {snapshot.id}")
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Failed to compute monthly snapshot: {e}")


@celery_app.task
def generate_revenue_forecast():
    """Generate the 30-day revenue forecast."""
    try:
        from app.services.analytics_service import ForecastService
        db = SessionLocal()
        try:
            forecast = ForecastService(db)
            results = forecast.forecast_revenue(days_ahead=30)
            logger.info(f"Generated {len(results)} daily revenue forecasts")
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Failed to generate revenue forecast: {e}")


@celery_app.task
def generate_insights():
    """Generate business insights from analytics data."""
    try:
        from app.services.analytics_service import InsightGenerationService
        db = SessionLocal()
        try:
            insights = InsightGenerationService(db)
            results = insights.generate_insights()
            logger.info(f"Generated {len(results)} business insights")
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Failed to generate insights: {e}")


@celery_app.task
def process_vendor_analytics(retailer_id: str):
    """Process and cache vendor analytics."""
    try:
        from app.services.vendor_analytics_service import (
            VendorAnalyticsService, VendorMetricsService,
        )
        db = SessionLocal()
        try:
            analytics = VendorAnalyticsService(db)
            metrics = VendorMetricsService(db)

            # Compute and cache dashboard data
            dashboard_data = analytics.get_dashboard_data(retailer_id)
            metrics.cache_performance(retailer_id, "dashboard", dashboard_data)

            logger.info(f"Processed vendor analytics for retailer {retailer_id}")
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Failed to process vendor analytics: {e}")


@celery_app.task
def detect_fraud_events():
    """Process recent orders for potential fraud."""
    try:
        from app.services.analytics_service import FraudDetectionService
        from app.models import Order
        db = SessionLocal()
        try:
            fraud = FraudDetectionService(db)

            # Check orders from the last 24 hours
            cutoff = utcnow() - timedelta(hours=24)
            recent_orders = db.query(Order).filter(
                Order.created_at >= cutoff,
            ).all()

            for order in recent_orders:
                event = fraud.analyze_order(order.id)
                if event:
                    logger.warning(f"Fraud detected on order {order.id}: score {event.score}")

            logger.info(f"Checked {len(recent_orders)} orders for fraud")
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Failed to detect fraud events: {e}")


@celery_app.task
def update_product_embeddings():
    """Update product embeddings for semantic search."""
    try:
        from app.models import Product, SearchEmbedding
        from app.services.search_service import SemanticSearchService
        from app.services.ai_chat_service import VectorSearchService
        from app.config import get_settings

        db = SessionLocal()
        try:
            settings = get_settings()
            api_key = settings.get("AI_API_KEY", "")

            products = db.query(Product).all()
            count = 0
            for product in products:
                # Check if embedding exists and is recent
                existing = db.query(SearchEmbedding).filter(
                    SearchEmbedding.product_id == product.id,
                ).first()

                if existing:
                    continue

                # Generate embedding
                text = VectorSearchService.prepare_product_text(product)
                embedding = VectorSearchService.embed_text(text, api_key)

                # Store embedding
                embedding_record = SearchEmbedding(
                    product_id=product.id,
                    embedding=str(embedding),
                    model="text-embedding-3-small",
                    chunk_text=text[:500],
                )
                db.add(embedding_record)
                count += 1

            db.commit()
            logger.info(f"Updated embeddings for {count} products")
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Failed to update product embeddings: {e}")

from sqlalchemy import func
