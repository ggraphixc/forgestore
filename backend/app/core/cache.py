"""Redis caching layer with in-memory fallback.

Usage:
    from app.core.cache import cache_get, cache_set, cache_invalidate

    cache_set("products:page:1", data, ttl=300)
    data = cache_get("products:page:1")
    cache_invalidate("products:*")
"""
import json
import logging
import re
import threading
import time
from typing import Any, Optional

logger = logging.getLogger("forgestore.cache")

# ─── Redis Connection ──────────────────────────────────────────────

_redis_client = None
_redis_available = False
_lock = threading.Lock()


def _get_redis():
    """Lazy-init Redis connection."""
    global _redis_client, _redis_available
    if _redis_available and _redis_client:
        return _redis_client
    with _lock:
        if _redis_client is not None:
            return _redis_client if _redis_available else None
        try:
            from app.config import get_settings
            settings = get_settings()
            if not settings.redis_url:
                logger.debug("REDIS_URL not set — using in-memory cache")
                return None
            import redis as redis_lib
            _redis_client = redis_lib.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_connect_timeout=3,
                socket_timeout=3,
                retry_on_timeout=True,
            )
            _redis_client.ping()
            _redis_available = True
            logger.info("Redis connected: %s", settings.redis_url.split("@")[-1])
            return _redis_client
        except Exception as e:
            logger.warning("Redis unavailable (%s) — falling back to in-memory cache", e)
            _redis_client = None
            _redis_available = False
            return None


# ─── In-Memory Fallback ───────────────────────────────────────────

_memory_cache: dict[str, tuple[Any, float]] = {}
_memory_lock = threading.Lock()


def _memory_cleanup():
    """Remove expired entries from in-memory cache."""
    now = time.time()
    with _memory_lock:
        expired = [k for k, (_, exp) in _memory_cache.items() if exp <= now]
        for k in expired:
            del _memory_cache[k]


# ─── Public API ────────────────────────────────────────────────────

def cache_get(key: str) -> Optional[Any]:
    """Get value from cache. Returns None on miss."""
    r = _get_redis()
    if r:
        try:
            raw = r.get(f"fs:{key}")
            if raw is None:
                return None
            return json.loads(raw)
        except Exception as e:
            logger.warning("Redis GET error: %s", e)
            return None
    # In-memory fallback
    with _memory_lock:
        entry = _memory_cache.get(key)
        if entry is None:
            return None
        value, expires = entry
        if expires <= time.time():
            del _memory_cache[key]
            return None
        return value


def cache_set(key: str, value: Any, ttl: int = 300) -> bool:
    """Set value in cache with TTL in seconds. Returns True on success."""
    r = _get_redis()
    if r:
        try:
            r.setex(f"fs:{key}", ttl, json.dumps(value, default=str))
            return True
        except Exception as e:
            logger.warning("Redis SET error: %s", e)
            return False
    # In-memory fallback
    with _memory_lock:
        _memory_cache[key] = (value, time.time() + ttl)
    return True


def cache_delete(key: str) -> bool:
    """Delete a single key from cache."""
    r = _get_redis()
    if r:
        try:
            r.delete(f"fs:{key}")
            return True
        except Exception:
            return False
    with _memory_lock:
        _memory_cache.pop(key, None)
    return True


def cache_invalidate(pattern: str) -> int:
    """Invalidate keys matching a glob pattern (e.g. 'products:*').
    Returns number of keys deleted.
    """
    r = _get_redis()
    if r:
        try:
            full_pattern = f"fs:{pattern}"
            cursor = 0
            deleted = 0
            while True:
                cursor, keys = r.scan(cursor=cursor, match=full_pattern, count=100)
                if keys:
                    deleted += r.delete(*keys)
                if cursor == 0:
                    break
            return deleted
        except Exception as e:
            logger.warning("Redis INVALIDATE error: %s", e)
            return 0
    # In-memory: pattern match
    regex = re.compile("^" + pattern.replace("*", ".*").replace("?", ".") + "$")
    with _memory_lock:
        to_delete = [k for k in _memory_cache if regex.match(k)]
        for k in to_delete:
            del _memory_cache[k]
        return len(to_delete)


def cache_clear_all() -> bool:
    """Flush all ForgeStore cache keys."""
    r = _get_redis()
    if r:
        try:
            cursor = 0
            while True:
                cursor, keys = r.scan(cursor=cursor, match="fs:*", count=200)
                if keys:
                    r.delete(*keys)
                if cursor == 0:
                    break
            return True
        except Exception:
            return False
    with _memory_lock:
        _memory_cache.clear()
    return True


def cache_stats() -> dict:
    """Return cache stats for monitoring."""
    r = _get_redis()
    if r:
        try:
            info = r.info("stats")
            memory = r.info("memory")
            return {
                "backend": "redis",
                "connected": True,
                "hits": info.get("keyspace_hits", 0),
                "misses": info.get("keyspace_misses", 0),
                "hit_rate": round(
                    info.get("keyspace_hits", 0)
                    / max(info.get("keyspace_hits", 0) + info.get("keyspace_misses", 0), 1)
                    * 100,
                    1,
                ),
                "memory_used": memory.get("used_memory_human", "N/A"),
            }
        except Exception:
            return {"backend": "redis", "connected": False}
    with _memory_lock:
        _memory_cleanup()
        return {
            "backend": "in-memory",
            "connected": True,
            "keys": len(_memory_cache),
        }


def get_or_set(key: str, factory_fn, ttl: int = 300) -> Any:
    """Get from cache, or call factory_fn(), cache result, and return it."""
    cached = cache_get(key)
    if cached is not None:
        return cached
    value = factory_fn()
    cache_set(key, value, ttl=ttl)
    return value
