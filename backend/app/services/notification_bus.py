"""
In-memory notification event bus for real-time push to admin UI.
Thread-safe for cross-boundary use (sync → async).
Persists notifications to the AdminNotification DB table when a db session is provided.
"""

import json
import threading
from typing import List, Dict, Any, Optional

_notifications: List[Dict[str, Any]] = []
_last_id = 0
_lock = threading.Lock()


def push(type_: str, title: str, message: str, link: str = "", db=None) -> dict:
    """
    Push a notification event to the bus. Thread-safe, callable from sync code.
    
    If a `db` (SQLAlchemy session) is provided, also persists the notification
    to the AdminNotification table for durable storage.
    """
    global _last_id
    notif = {}
    with _lock:
        _last_id += 1
        notif = {
            "id": str(_last_id),
            "type": type_,
            "title": title,
            "message": message,
            "link": link,
        }
        _notifications.append(notif)
        # Keep only last 500 to avoid unbounded growth
        if len(_notifications) > 500:
            _notifications[:100] = []

    # Persist to DB if a session is available (outside lock to avoid blocking)
    if db is not None:
        try:
            from app.models import AdminNotification
            db_notif = AdminNotification(
                type=type_,
                title=title,
                message=message,
                link=link,
            )
            db.add(db_notif)
            db.commit()
        except Exception:
            db.rollback()

    return notif


def poll(since_id: int = 0) -> List[Dict[str, Any]]:
    """Return all events newer than `since_id`. Thread-safe."""
    with _lock:
        return [n for n in _notifications if int(n["id"]) > since_id]
