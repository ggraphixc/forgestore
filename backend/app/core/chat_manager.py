"""
WebSocket ConnectionManager — multi-tenant real-time chat between customers and vendors.

Manages authenticated user-to-user WebSocket connections with automatic
message persistence for offline recipients.
"""
import json
import logging
from typing import Dict, Set, Optional
from fastapi import WebSocket

logger = logging.getLogger("forgestore.websocket.chat")


class ChatConnectionManager:
    """Tracks active user WebSocket connections for direct messaging."""

    def __init__(self):
        self._user_connections: Dict[str, Set[WebSocket]] = {}
        self._ws_user_map: Dict[int, str] = {}

    async def connect(self, websocket: WebSocket, user_id: str):
        await websocket.accept()
        if user_id not in self._user_connections:
            self._user_connections[user_id] = set()
        self._user_connections[user_id].add(websocket)
        self._ws_user_map[id(websocket)] = user_id
        logger.info("Chat connected: user=%s", user_id)

    async def disconnect(self, websocket: WebSocket):
        user_id = self._ws_user_map.pop(id(websocket), None)
        if user_id and user_id in self._user_connections:
            self._user_connections[user_id].discard(websocket)
            if not self._user_connections[user_id]:
                del self._user_connections[user_id]
        logger.debug("Chat disconnected: user=%s", user_id)

    def is_online(self, user_id: str) -> bool:
        return bool(self._user_connections.get(user_id))

    async def send_to_user(self, user_id: str, data: dict):
        conns = self._user_connections.get(user_id, set())
        payload = json.dumps(data)
        disconnected = set()
        for ws in conns:
            try:
                await ws.send_text(payload)
            except Exception:
                disconnected.add(ws)
        for ws in disconnected:
            await self.disconnect(ws)

    def get_online_users(self) -> list:
        return list(self._user_connections.keys())

    def stats(self) -> dict:
        return {
            "online_users": len(self._user_connections),
            "total_connections": sum(len(c) for c in self._user_connections.values()),
        }


chat_manager = ChatConnectionManager()
