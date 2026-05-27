"""Real-time Notification Infrastructure — System 9"""
import logging
from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session

from app.models import NotificationQueue, PushSubscription, UserNotificationPreferences, NotificationDeliveryLog
from app.core.websocket_manager import ws_manager
from app.core.event_bus import event_bus

logger = logging.getLogger("forgestore.notification")


class NotificationService:
    """Handles queuing and dispatching notifications across all channels."""

    def __init__(self, db: Session):
        self.db = db

    def send_notification(
        self,
        recipient_type: str,
        recipient_id: Optional[str],
        notification_type: str,
        title: str,
        message: Optional[str] = None,
        data: Optional[dict] = None,
        priority: int = 0,
        channels: Optional[list[str]] = None,
    ) -> NotificationQueue:
        """Queue a notification for delivery."""
        notification = NotificationQueue(
            recipient_type=recipient_type,
            recipient_id=recipient_id,
            notification_type=notification_type,
            title=title,
            message=message,
            data=data or {},
            priority=priority,
            status="PENDING",
        )
        self.db.add(notification)
        self.db.commit()
        self.db.refresh(notification)

        # Dispatch via configured channels
        if channels is None:
            channels = ["in_app", "email"]

        for channel in channels:
            self._dispatch_channel(notification, channel)

        return notification

    def _dispatch_channel(self, notification: NotificationQueue, channel: str):
        """Dispatch notification to a specific channel."""
        delivery_log = NotificationDeliveryLog(
            notification_id=notification.id,
            channel=channel,
            status="sent",
        )
        try:
            if channel == "in_app" and notification.recipient_id:
                ws_manager.send_to_user(
                    notification.recipient_id,
                    {
                        "type": "notification",
                        "id": notification.id,
                        "notification_type": notification.notification_type,
                        "title": notification.title,
                        "message": notification.message,
                        "data": notification.data,
                        "priority": notification.priority,
                        "created_at": notification.created_at.isoformat(),
                    },
                )
            elif channel == "email" and notification.recipient_id:
                # Queue email via Celery
                from app.tasks.notification_tasks import send_email_notification
                send_email_notification.delay(
                    notification.id,
                    notification.recipient_id,
                    notification.title,
                    notification.message,
                )

            delivery_log.status = "delivered"
        except Exception as e:
            logger.error(f"Failed to dispatch notification {notification.id} via {channel}: {e}")
            delivery_log.status = "failed"
            delivery_log.error_message = str(e)

        delivery_log.delivered_at = datetime.utcnow()
        self.db.add(delivery_log)
        self.db.commit()

    def mark_read(self, notification_id: str) -> bool:
        """Mark a notification as read."""
        notification = self.db.query(NotificationQueue).filter(NotificationQueue.id == notification_id).first()
        if not notification:
            return False
        notification.read_at = datetime.utcnow()
        self.db.commit()
        return True

    def get_user_notifications(
        self,
        recipient_id: str,
        recipient_type: str = "customer",
        limit: int = 50,
        unread_only: bool = False,
    ) -> list[NotificationQueue]:
        """Get notifications for a user."""
        query = self.db.query(NotificationQueue).filter(
            NotificationQueue.recipient_id == recipient_id,
            NotificationQueue.recipient_type == recipient_type,
        )
        if unread_only:
            query = query.filter(NotificationQueue.read_at.is_(None))
        return query.order_by(NotificationQueue.priority.desc(), NotificationQueue.created_at.desc()).limit(limit).all()

    def get_preferences(self, user_id: str) -> Optional[UserNotificationPreferences]:
        """Get notification preferences for a user."""
        prefs = self.db.query(UserNotificationPreferences).filter(
            UserNotificationPreferences.user_id == user_id
        ).first()
        if not prefs:
            prefs = UserNotificationPreferences(user_id=user_id)
            self.db.add(prefs)
            self.db.commit()
            self.db.refresh(prefs)
        return prefs

    def update_preferences(self, user_id: str, updates: dict) -> UserNotificationPreferences:
        """Update notification preferences for a user."""
        prefs = self.get_preferences(user_id)
        for key, value in updates.items():
            if hasattr(prefs, key):
                setattr(prefs, key, value)
        self.db.commit()
        self.db.refresh(prefs)
        return prefs


class PushService:
    """Manages browser push notification subscriptions."""

    def __init__(self, db: Session):
        self.db = db

    def register_subscription(self, user_id: str, endpoint: str, keys: dict) -> PushSubscription:
        """Register a push subscription."""
        sub = PushSubscription(
            user_id=user_id,
            endpoint=endpoint,
            keys=keys,
        )
        self.db.add(sub)
        self.db.commit()
        self.db.refresh(sub)
        return sub

    def unregister_subscription(self, endpoint: str) -> bool:
        """Remove a push subscription."""
        sub = self.db.query(PushSubscription).filter(PushSubscription.endpoint == endpoint).first()
        if sub:
            sub.is_active = False
            self.db.commit()
            return True
        return False

    def get_user_subscriptions(self, user_id: str) -> list[PushSubscription]:
        """Get all active subscriptions for a user."""
        return self.db.query(PushSubscription).filter(
            PushSubscription.user_id == user_id,
            PushSubscription.is_active == True,
        ).all()


class RealtimeEventService:
    """Manages real-time event broadcasting via WebSockets."""

    @staticmethod
    async def broadcast_order_update(order_id: str, status: str, data: Optional[dict] = None):
        """Broadcast order status updates to all interested parties."""
        event = {
            "type": "order_update",
            "order_id": order_id,
            "status": status,
            "data": data or {},
            "timestamp": datetime.utcnow().isoformat(),
        }
        await ws_manager.broadcast(f"order:{order_id}", event)
        await ws_manager.broadcast("admin:orders", event)

    @staticmethod
    async def broadcast_shipment_update(shipment_id: str, tracking_number: str, status: str, data: Optional[dict] = None):
        """Broadcast shipment tracking updates."""
        event = {
            "type": "shipment_update",
            "shipment_id": shipment_id,
            "tracking_number": tracking_number,
            "status": status,
            "data": data or {},
            "timestamp": datetime.utcnow().isoformat(),
        }
        await ws_manager.broadcast(f"shipment:{shipment_id}", event)
        await ws_manager.broadcast("admin:shipments", event)

    @staticmethod
    async def broadcast_admin_alert(alert_type: str, title: str, message: str, data: Optional[dict] = None):
        """Broadcast real-time admin alerts."""
        event = {
            "type": "admin_alert",
            "alert_type": alert_type,
            "title": title,
            "message": message,
            "data": data or {},
            "timestamp": datetime.utcnow().isoformat(),
        }
        await ws_manager.broadcast("admin:alerts", event)
