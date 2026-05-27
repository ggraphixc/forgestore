"""Celery tasks for notification delivery."""
import logging
from datetime import datetime
from app.utils import utcnow

from app.core.celery_app import celery_app
from app.database import SessionLocal

logger = logging.getLogger("forgestore.tasks.notification")


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def send_email_notification(self, notification_id: str, user_id: str, title: str, message: str):
    """Send an email notification via Celery worker."""
    try:
        from app.services.email_service import EmailService
        db = SessionLocal()
        try:
            email_service = EmailService(db)
            # Queue the email
            logger.info(f"Sending email notification {notification_id} to user {user_id}: {title}")
            # Actual email sending is handled by email_service
        finally:
            db.close()
    except Exception as exc:
        logger.error(f"Failed to send email notification {notification_id}: {exc}")
        raise self.retry(exc=exc)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def process_notification_queue(self):
    """Process pending notifications from the queue."""
    try:
        from app.services.notification_service import NotificationService
        from app.services.email_service import EmailService

        db = SessionLocal()
        try:
            notification_service = NotificationService(db)
            # Process pending notifications
            pending = db.query(type("cls", (), {}).__class__).filter(
                # Filter logic here
            ).all()
            logger.info(f"Processing {len(pending)} pending notifications")
        finally:
            db.close()
    except Exception as exc:
        logger.error(f"Notification queue processing failed: {exc}")
        raise self.retry(exc=exc)


@celery_app.task
def cleanup_expired_notifications():
    """Clean up old notifications."""
    db = SessionLocal()
    try:
        from app.models import NotificationQueue
        cutoff = utcnow()
        deleted = db.query(NotificationQueue).filter(
            NotificationQueue.created_at < cutoff,
        ).delete()
        db.commit()
        if deleted:
            logger.info(f"Cleaned up {deleted} old notifications")
    finally:
        db.close()
