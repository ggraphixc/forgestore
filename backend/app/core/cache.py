"""
Redis Catalog Cache Layer — async cache-aside pattern for public marketplace paths.

Provides:
  - Cache-aside decorator for product list, detail, and category queries
  - Automatic TTL-based expiry (3600s default)
  - Invalidation hooks for vendor product mutations
"""
import json
import logging
from typing import Optional, Callable, Any
from functools import wraps

logger = logging.getLogger("forgestore.cache")

DEFAULT_TTL = 3600  # 1 hour


def _get_redis():
    """Get async Redis client (returns None if unavailable)."""
    try:
        from app.core.redis_manager import get_redis
        return get_redis()
    except Exception:
        return None


async def cache_get(key: str) -> Optional[Any]:
    """Retrieve a cached value by key."""
    r = _get_redis()
    if not r:
        return None
    try:
        client = await r.get_async()
        raw = await client.get(key)
        if raw:
            return json.loads(raw)
    except Exception as exc:
        logger.debug("Cache GET failed for %s: %s", key, exc)
    return None


async def cache_set(key: str, value: Any, ttl: int = DEFAULT_TTL):
    """Store a value in cache with TTL."""
    r = _get_redis()
    if not r:
        return
    try:
        client = await r.get_async()
        await client.set(key, json.dumps(value, default=str), ex=ttl)
    except Exception as exc:
        logger.debug("Cache SET failed for %s: %s", key, exc)


async def cache_delete(key: str):
    """Delete a single cache key."""
    r = _get_redis()
    if not r:
        return
    try:
        client = await r.get_async()
        await client.delete(key)
    except Exception as exc:
        logger.debug("Cache DELETE failed for %s: %s", key, exc)


async def cache_delete_pattern(pattern: str):
    """Delete all keys matching a glob pattern."""
    r = _get_redis()
    if not r:
        return
    try:
        client = await r.get_async()
        cursor = 0
        while True:
            cursor, keys = await client.scan(cursor=cursor, match=pattern, count=100)
            if keys:
                await client.delete(*keys)
            if cursor == 0:
                break
    except Exception as exc:
        logger.debug("Cache DELETE pattern failed for %s: %s", pattern, exc)


def cached_endpoint(key_prefix: str, ttl: int = DEFAULT_TTL):
    """Decorator for FastAPI endpoint caching. Reads/writes JSON to Redis."""
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Build cache key from function args
            cache_key = key_prefix
            for k, v in kwargs.items():
                if k != "db" and k != "request":
                    cache_key += f":{k}:{v}"

            # Try cache
            cached = await cache_get(cache_key)
            if cached is not None:
                return cached

            # Execute function
            result = await func(*args, **kwargs)

            # Cache result
            if result is not None:
                await cache_set(cache_key, result, ttl=ttl)

            return result
        return wrapper
    return decorator


# ── Invalidation Hooks ──────────────────────────────────────────────

async def invalidate_product_cache(product_id: str = None, retailer_id: str = None):
    """Purge product cache keys when a vendor updates their catalog."""
    await cache_delete("cache:products:all")
    await cache_delete_pattern("cache:products:*")
    await cache_delete_pattern("cache:categories:*")
    if product_id:
        await cache_delete(f"cache:product:{product_id}")
    if retailer_id:
        await cache_delete_pattern(f"cache:vendor:{retailer_id}:*")
    logger.info("Cache invalidated: product=%s retailer=%s", product_id, retailer_id)


async def invalidate_category_cache():
    """Purge category cache keys."""
    await cache_delete_pattern("cache:categories:*")
    await cache_delete("cache:products:all")
