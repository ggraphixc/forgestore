"""Celery tasks for cart recovery and abandoned cart processing."""
import logging
from datetime import datetime, timedelta

from app.core.celery_app import celery_app
from app.database import SessionLocal

logger = logging.getLogger("forgestore.tasks.cart")


@celery_app.task(bind=True, max_retries=3, default_retry_delay=300)
def send_cart_recovery_email(self, abandoned_cart_id: str):
    """Send a cart recovery email to the customer."""
    try:
        from app.models import AbandonedCart
        from app.services.email_service import EmailService

        db = SessionLocal()
        try:
            cart = db.query(AbandonedCart).filter(AbandonedCart.id == abandoned_cart_id).first()
            if not cart or not cart.email:
                logger.warning(f"Abandoned cart {abandoned_cart_id} has no email")
                return

            email_service = EmailService(db)
            # Send recovery email with cart contents
            logger.info(f"Sending cart recovery email for cart {abandoned_cart_id} to {cart.email}")

            # Log the reminder
            cart.reminder_sent = True
            cart.reminder_count = (cart.reminder_count or 0) + 1
            cart.last_reminder_at = datetime.utcnow()
            db.commit()
        finally:
            db.close()
    except Exception as exc:
        logger.error(f"Failed to send cart recovery email for {abandoned_cart_id}: {exc}")
        raise self.retry(exc=exc)


@celery_app.task
def detect_abandoned_carts():
    """Detect and mark carts that have been abandoned."""
    db = SessionLocal()
    try:
        from app.models import CartActivity, AbandonedCart
        from app.services.cart_sync_service import CartRecoveryService

        recovery_service = CartRecoveryService(db)
        cutoff = datetime.utcnow() - timedelta(hours=6)

        # Find carts with no activity for 6+ hours
        stale_carts = db.query(
            CartActivity.cart_token,
            func.max(CartActivity.created_at).label("last_activity"),
        ).group_by(CartActivity.cart_token).having(
            func.max(CartActivity.created_at) < cutoff
        ).limit(100).all()

        for row in stale_carts:
            # Check if already recorded as abandoned
            existing = db.query(AbandonedCart).filter(
                AbandonedCart.cart_token == row.cart_token,
                AbandonedCart.recovered == False,
            ).first()
            if not existing:
                recovery_service.detect_abandoned(row.cart_token)

        logger.info(f"Checked {len(stale_carts)} carts for abandonment")
    finally:
        db.close()


@celery_app.task
def cleanup_old_carts():
    """Clean up cart data older than 30 days."""
    db = SessionLocal()
    try:
        from app.models import CartActivity, AbandonedCart
        from datetime import timedelta

        cutoff = datetime.utcnow() - timedelta(days=30)

        # Clean old activities
        deleted_activities = db.query(CartActivity).filter(
            CartActivity.created_at < cutoff
        ).delete()
        db.commit()

        # Clean unrecovered abandoned carts older than 60 days
        old_abandoned_cutoff = datetime.utcnow() - timedelta(days=60)
        deleted_abandoned = db.query(AbandonedCart).filter(
            AbandonedCart.abandoned_at < old_abandoned_cutoff,
            AbandonedCart.recovered == False,
        ).delete()
        db.commit()

        logger.info(f"Cleaned up {deleted_activities} activities, {deleted_abandoned} abandoned carts")
    finally:
        db.close()
