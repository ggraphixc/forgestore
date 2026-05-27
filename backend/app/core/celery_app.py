"""
Celery worker configuration for async task processing.
Handles broadcast sending, analytics aggregation, and background jobs.
"""
import logging
from celery import Celery, Task
from functools import lru_cache

logger = logging.getLogger("forgestore.celery")


def make_celery() -> Celery:
    """Create and configure the Celery app instance."""
    from app.config import get_settings
    settings = get_settings()

    broker_url = getattr(settings, "redis_url", None) or "redis://localhost:6379/0"
    backend_url = getattr(settings, "redis_url", None) or "redis://localhost:6379/0"

    app = Celery(
        "forgestore",
        broker=broker_url,
        backend=backend_url,
        include=[
            "app.tasks.broadcast_tasks",
            "app.tasks.analytics_tasks",
            "app.tasks.notification_tasks",
            "app.tasks.cart_tasks",
            "app.tasks.email_tasks",
        ],
    )

    app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
        task_track_started=True,
        task_time_limit=300,  # 5 minutes max per task
        task_soft_time_limit=240,
        worker_max_tasks_per_child=200,
        worker_prefetch_multiplier=1,
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        result_expires=3600 * 24,  # Results expire after 24h
        beat_schedule={
            "cleanup-expired-carts": {
                "task": "app.tasks.cart_tasks.cleanup_expired_carts",
                "schedule": 3600,  # Every hour
            },
            "run-predictive-analytics": {
                "task": "app.tasks.analytics_tasks.run_predictive_analytics",
                "schedule": 86400,  # Every 24 hours
            },
            "aggregate-daily-analytics": {
                "task": "app.tasks.analytics_tasks.aggregate_daily_analytics",
                "schedule": 3600 * 6,  # Every 6 hours
            },
            "process-abandoned-carts": {
                "task": "app.tasks.cart_tasks.process_abandoned_carts",
                "schedule": 1800,  # Every 30 minutes
            },
            "cleanup-expired-notifications": {
                "task": "app.tasks.notification_tasks.cleanup_expired_notifications",
                "schedule": 86400,  # Every 24 hours
            },
        },
    )

    logger.info(
        "Celery app created — broker: %s, backend: %s",
        broker_url.replace("redis://", "redis://***@") if "redis://" in broker_url else broker_url,
        backend_url.replace("redis://", "redis://***@") if "redis://" in backend_url else backend_url,
    )

    return app


@lru_cache()
def get_celery() -> Celery:
    """Get the singleton Celery app instance."""
    return make_celery()


# ─── Base Task Class ────────────────────────────────────────────────

class DatabaseTask(Task):
    """Celery task that provides a database session."""
    _db = None

    def before_start(self, task_id, args, kwargs):
        """Override: called before the task runs."""
        pass

    def after_return(self, status, retval, task_id, args, kwargs, einfo):
        """Clean up DB session after task completes."""
        if self._db is not None:
            try:
                self._db.close()
            except Exception:
                pass
            self._db = None

    def get_db(self):
        """Get a fresh database session for this task."""
        if self._db is None:
            from app.database import get_session_local
            self._db = get_session_local()()
        return self._db
