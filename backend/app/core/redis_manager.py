"""
Redis Connection Manager — singleton connection pool for the entire app.
Provides both sync and async access, with automatic reconnection.
"""
import json
import logging
from typing import Optional, Any, Dict, List
from functools import lru_cache

logger = logging.getLogger("forgestore.redis")

_redis_client = None
_redis_async_client = None


class RedisManager:
    """Manages Redis connections for caching, pub/sub, session storage, and cart sync."""

    def __init__(self, url: str = None, decode_responses: bool = True):
        self.url = url or "redis://localhost:6379/0"
        self.decode = decode_responses
        self._sync_client = None
        self._async_client = None

    # ── Sync Client ──────────────────────────────────────────────────

    def get_sync(self):
        """Get or create the synchronous Redis client."""
        if self._sync_client is None:
            import redis
            try:
                self._sync_client = redis.Redis.from_url(
                    self.url,
                    decode_responses=self.decode,
                    socket_connect_timeout=3,
                    socket_timeout=5,
                    retry_on_timeout=True,
                    health_check_interval=30,
                )
                self._sync_client.ping()
                logger.info("Connected to Redis (sync)")
            except Exception as e:
                logger.warning("Redis sync connection failed: %s — running without Redis", e)
                self._sync_client = _NullRedis()
        return self._sync_client

    # ── Async Client ─────────────────────────────────────────────────

    async def get_async(self):
        """Get or create the async Redis client."""
        if self._async_client is None:
            try:
                import redis.asyncio as aioredis
                self._async_client = aioredis.from_url(
                    self.url,
                    decode_responses=self.decode,
                    socket_connect_timeout=3,
                    socket_timeout=5,
                    retry_on_timeout=True,
                    health_check_interval=30,
                )
                await self._async_client.ping()
                logger.info("Connected to Redis (async)")
            except Exception as e:
                logger.warning("Redis async connection failed: %s — running without Redis", e)
                self._async_client = _NullRedisAsync()
        return self._async_client

    # ── Convenience Methods (Sync) ───────────────────────────────────

    def get(self, key: str) -> Optional[str]:
        return self.get_sync().get(key)

    def set(self, key: str, value: str, ex: int = None) -> bool:
        return bool(self.get_sync().set(key, value, ex=ex))

    def delete(self, key: str) -> bool:
        return bool(self.get_sync().delete(key))

    def exists(self, key: str) -> bool:
        return bool(self.get_sync().exists(key))

    def expire(self, key: str, seconds: int) -> bool:
        return bool(self.get_sync().expire(key, seconds))

    def hset(self, name: str, key: str, value: Any):
        if not isinstance(value, str):
            value = json.dumps(value)
        self.get_sync().hset(name, key, value)

    def hget(self, name: str, key: str) -> Optional[str]:
        return self.get_sync().hget(name, key)

    def hgetall(self, name: str) -> Dict[str, str]:
        return self.get_sync().hgetall(name) or {}

    def hdel(self, name: str, key: str) -> bool:
        return bool(self.get_sync().hdel(name, key))

    def smembers(self, name: str) -> set:
        return self.get_sync().smembers(name) or set()

    def sadd(self, name: str, value: str) -> bool:
        return bool(self.get_sync().sadd(name, value))

    def srem(self, name: str, value: str) -> bool:
        return bool(self.get_sync().srem(name, value))

    def publish(self, channel: str, message: Any):
        if not isinstance(message, str):
            message = json.dumps(message)
        self.get_sync().publish(channel, message)

    # ── Convenience Methods (Async) ──────────────────────────────────

    async def aget(self, key: str) -> Optional[str]:
        c = await self.get_async()
        return await c.get(key)

    async def aset(self, key: str, value: str, ex: int = None) -> bool:
        c = await self.get_async()
        return bool(await c.set(key, value, ex=ex))

    async def adelete(self, key: str) -> bool:
        c = await self.get_async()
        return bool(await c.delete(key))

    async def apublish(self, channel: str, message: Any):
        if not isinstance(message, str):
            message = json.dumps(message)
        c = await self.get_async()
        await c.publish(channel, message)

    # ─── Cart-specific helpers ──────────────────────────────────────

    def get_cart(self, cart_token: str) -> List[Dict]:
        """Get cart items from Redis hash."""
        raw = self.hgetall(f"cart:{cart_token}")
        if not raw:
            return []
        items = []
        for pid, qty in raw.items():
            items.append({"product_id": pid, "quantity": int(qty)})
        return items

    def set_cart_item(self, cart_token: str, product_id: str, quantity: int, ttl: int = 86400 * 7):
        """Set a cart item and ensure TTL is set on the cart."""
        self.hset(f"cart:{cart_token}", product_id, str(quantity))
        self.expire(f"cart:{cart_token}", ttl)

    def remove_cart_item(self, cart_token: str, product_id: str):
        self.hdel(f"cart:{cart_token}", product_id)

    def clear_cart(self, cart_token: str):
        self.delete(f"cart:{cart_token}")


class _NullRedis:
    """Fake Redis client that silently ignores all operations (for when Redis is unavailable)."""
    def __getattr__(self, name):
        def _noop(*args, **kwargs):
            return None if name in ("get", "hget", "hgetall") else 0 if "del" in name else False
        return _noop

    def ping(self):
        return False

    def get(self, key):
        return None

    def hgetall(self, name):
        return {}

    def smembers(self, name):
        return set()

    def hget(self, name, key):
        return None

    def exists(self, key):
        return False

    def expire(self, key, seconds):
        return False

    def publish(self, channel, message):
        return 0


class _NullRedisAsync:
    """Fake async Redis client."""
    async def ping(self):
        return False

    async def get(self, key):
        return None

    async def set(self, key, value, ex=None):
        return False

    async def hgetall(self, name):
        return {}

    async def smembers(self, name):
        return set()

    def __getattr__(self, name):
        async def _noop(*args, **kwargs):
            return None
        return _noop


# ─── Singleton ──────────────────────────────────────────────────────

import os

# Read the Render private network string, falling back to local machine loop only in development
try:
    from app.config import get_settings
    redis_url = get_settings().redis_url or os.getenv("REDIS_URL", "redis://localhost:6379")
except Exception:
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")


@lru_cache()
def get_redis() -> RedisManager:
    """Get the singleton Redis manager instance."""
    return RedisManager(url=redis_url)


# Module-level convenience reference for easy imports
redis_client = get_redis()
