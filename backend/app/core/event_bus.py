"""
Event Bus — pub/sub system for cross-service communication.
Bridges sync code, async code, Redis pub/sub, and WebSocket broadcasting.
"""
import json
import logging
from typing import Callable, Dict, List, Any, Optional
from datetime import datetime

logger = logging.getLogger("forgestore.events")


class EventBus:
    """
    In-process event bus with optional Redis pub/sub backing.
    
    Services publish events (e.g., "order.placed", "payment.confirmed")
    and any number of subscribers receive them. Events are also forwarded
    to Redis pub/sub for cross-worker broadcasting and to the WebSocket
    manager for real-time client delivery.
    """

    def __init__(self):
        self._subscribers: Dict[str, List[Callable]] = {}
        self._history: List[dict] = []
        self._max_history = 200

    # ── Subscribe / Unsubscribe ─────────────────────────────────────

    def subscribe(self, event_type: str, callback: Callable):
        """Subscribe a callback to an event type. Supports glob patterns."""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(callback)
        logger.debug("Subscribed to '%s' (total: %d)", event_type, len(self._subscribers[event_type]))

    def unsubscribe(self, event_type: str, callback: Callable):
        """Remove a callback subscription."""
        if event_type in self._subscribers:
            self._subscribers[event_type] = [
                cb for cb in self._subscribers[event_type] if cb is not callback
            ]
            if not self._subscribers[event_type]:
                del self._subscribers[event_type]

    # ── Publishing ──────────────────────────────────────────────────

    async def publish(self, event_type: str, data: dict = None, source: str = "app"):
        """
        Publish an event to all subscribers + Redis + WebSocket.
        
        Args:
            event_type: Dot-notation type (e.g., "order.placed", "payment.confirmed")
            data: Event payload
            source: Origin of the event (for debugging)
        """
        if data is None:
            data = {}

        event = {
            "id": f"{datetime.utcnow().timestamp()}-{hash(event_type) & 0xFFFF}",
            "type": event_type,
            "data": data,
            "source": source,
            "timestamp": datetime.utcnow().isoformat(),
        }

        # Store in history (ring buffer)
        self._history.append(event)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        # Notify in-process subscribers
        await self._notify_subscribers(event_type, event)

        # Forward to Redis pub/sub (for multi-worker setups)
        await self._forward_to_redis(event)

        # Forward to WebSocket manager
        await self._forward_to_websocket(event)

        logger.debug("Event published: %s", event_type)

    async def publish_sync(self, event_type: str, data: dict = None, source: str = "app"):
        """Synchronous wrapper for publish — runs in event loop."""
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.publish(event_type, data, source))
        except RuntimeError:
            # No running loop — create one
            asyncio.run(self.publish(event_type, data, source))

    # ── Internal Notification ───────────────────────────────────────

    async def _notify_subscribers(self, event_type: str, event: dict):
        """Call all subscribers that match the event type."""
        # Exact match
        callbacks = self._subscribers.get(event_type, [])[:]
        # Wildcard match (e.g., "order.*" matches "order.placed")
        for pattern, cbs in self._subscribers.items():
            if pattern.endswith("*") and event_type.startswith(pattern[:-1]):
                callbacks.extend(cbs)

        for cb in callbacks:
            try:
                if hasattr(cb, "__call__"):
                    result = cb(event)
                    if hasattr(result, "__await__"):
                        await result
            except Exception as e:
                logger.error("Event subscriber error for '%s': %s", event_type, e)

    # ── Redis Forwarding ────────────────────────────────────────────

    async def _forward_to_redis(self, event: dict):
        """Forward event to Redis pub/sub for cross-worker distribution."""
        try:
            from app.core.redis_manager import get_redis
            r = get_redis()
            channel = f"events:{event['type']}"
            await r.apublish(channel, event)
        except Exception:
            pass  # Redis is optional

    # ── WebSocket Forwarding ────────────────────────────────────────

    async def _forward_to_websocket(self, event: dict):
        """Forward event to WebSocket manager for real-time client delivery."""
        try:
            from app.core.websocket_manager import get_ws_manager
            ws = get_ws_manager()

            event_type = event["type"]
            data = event["data"]

            # Map event types to WebSocket channels
            payload = {"type": event_type, "data": data}
            if event_type.startswith("order."):
                order_id = data.get("order_id", "unknown")
                await ws.broadcast(f"order:{order_id}", payload)
                await ws.broadcast("admin", payload)
            elif event_type.startswith("vendor."):
                vendor_id = data.get("vendor_id", "unknown")
                await ws.broadcast(f"vendor:{vendor_id}", payload)
            elif event_type.startswith("notification."):
                await ws.broadcast("admin", payload)
                await ws.broadcast("global", payload)
            elif event_type.startswith("cart."):
                cart_token = data.get("cart_token", "unknown")
                await ws.broadcast(f"cart:{cart_token}", payload)
            else:
                await ws.broadcast("admin", payload)
                await ws.broadcast("global", payload)
        except Exception:
            pass

    # ── Query History ───────────────────────────────────────────────

    def get_history(self, event_type: str = None, limit: int = 50) -> List[dict]:
        """Get recent events, optionally filtered by type."""
        if event_type:
            return [e for e in self._history if e["type"] == event_type][-limit:]
        return self._history[-limit:]

    def clear_history(self):
        """Clear the event history."""
        self._history = []


# ─── Singleton ──────────────────────────────────────────────────────

_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    """Get the singleton event bus instance."""
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus


# Module-level convenience reference for easy imports
event_bus = get_event_bus()
