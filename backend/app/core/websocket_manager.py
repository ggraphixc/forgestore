"""
WebSocket Manager — handles real-time connections for live order tracking,
notification streaming, and admin dashboard updates.

Uses in-memory connection tracking with optional Redis pub/sub for
multi-worker scaling.
"""
import json
import logging
from typing import Set, Dict, Any, Optional
from fastapi import WebSocket

logger = logging.getLogger("forgestore.websocket")


class WebSocketManager:
    """
    Manages all active WebSocket connections grouped by channel.
    
    Channels:
        - admin: Admin dashboard notifications
        - order:{order_id}: Order tracking updates
        - vendor:{vendor_id}: Vendor dashboard data
        - cart:{cart_token}: Real-time cart updates
        - global: System-wide announcements
    """

    def __init__(self):
        self._channels: Dict[str, Set[WebSocket]] = {}
        self._connection_info: Dict[id, dict] = {}  # websocket_id -> metadata

    # ── Connection Management ───────────────────────────────────────

    async def connect(self, websocket: WebSocket, channel: str = "global"):
        """Accept a WebSocket and subscribe it to a channel."""
        await websocket.accept()
        if channel not in self._channels:
            self._channels[channel] = set()
        self._channels[channel].add(websocket)
        self._connection_info[id(websocket)] = {"channel": channel}
        logger.debug("WebSocket connected to channel '%s' — total: %d", channel, self.count(channel))

    async def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket from all channels."""
        info = self._connection_info.pop(id(websocket), {})
        channel = info.get("channel", "global")
        if channel in self._channels:
            self._channels[channel].discard(websocket)
            if not self._channels[channel]:
                del self._channels[channel]
        logger.debug("WebSocket disconnected from channel '%s'", channel)

    def count(self, channel: str = None) -> int:
        """Count connections in a channel (or total across all)."""
        if channel:
            return len(self._channels.get(channel, set()))
        return sum(len(conns) for conns in self._channels.values())

    # ── Broadcasting ────────────────────────────────────────────────

    async def broadcast(self, channel: str, data: dict):
        """Send a JSON event to all connections on a channel.
        *data* should already contain a ``type`` key.
        """
        payload = json.dumps(data)
        disconnected = set()
        for ws in self._channels.get(channel, set()):
            try:
                await ws.send_text(payload)
            except Exception:
                disconnected.add(ws)
        # Clean up disconnected clients
        for ws in disconnected:
            await self.disconnect(ws)

    async def broadcast_to_many(self, channels: list, data: dict):
        """Broadcast the same event to multiple channels."""
        for channel in channels:
            await self.broadcast(channel, data)

    async def send_personal(self, websocket: WebSocket, data: dict):
        """Send a JSON event to a single connection."""
        try:
            await websocket.send_text(json.dumps(data))
        except Exception:
            await self.disconnect(websocket)

    async def send_to_user(self, user_id: str, data: dict):
        """Send a JSON event to all connections belonging to a user channel."""
        await self.broadcast(f"user:{user_id}", data)

    # ── Convenience: Order Tracking ─────────────────────────────────

    async def broadcast_order_update(self, order_id: str, data: dict):
        """Broadcast an update to everyone tracking a specific order."""
        await self.broadcast(f"order:{order_id}", data)
        # Also notify admin channel
        await self.broadcast("admin", {"type": "order_update", "order_id": order_id, **data})

    # ── Check health ────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Get connection statistics."""
        return {
            "total_connections": self.count(),
            "channels": {
                ch: len(conns) for ch, conns in self._channels.items()
            },
        }


# ─── Singleton ──────────────────────────────────────────────────────

_manager: Optional[WebSocketManager] = None


def get_ws_manager() -> WebSocketManager:
    """Get the singleton WebSocket manager instance."""
    global _manager
    if _manager is None:
        _manager = WebSocketManager()
    return _manager


# Module-level convenience reference for easy imports
ws_manager = get_ws_manager()
