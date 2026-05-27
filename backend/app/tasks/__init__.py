from app.core.celery_app import celery_app

# Import all task modules so tasks are registered
from app.tasks import notification_tasks, analytics_tasks, cart_tasks  # noqa: F401
