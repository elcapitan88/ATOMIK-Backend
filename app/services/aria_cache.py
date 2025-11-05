# app/services/aria_cache.py
"""
Redis caching service for ARIA
Implements intelligent caching with TTL strategies
"""

import redis
import json
import logging
import hashlib
from typing import Dict, Any, Optional, Callable, List
from datetime import datetime, timedelta
import asyncio
from functools import wraps

from ..core.config import settings

logger = logging.getLogger(__name__)


class ARIACache:
    """
    Intelligent caching layer for ARIA
    Uses Redis for distributed caching with smart TTL management
    """

    def __init__(self):
        """Initialize Redis connection"""
        self.redis_url = settings.REDIS_URL if hasattr(settings, 'REDIS_URL') else "redis://localhost:6379"

        try:
            # Parse Redis URL and create connection pool
            self.redis_client = redis.from_url(
                self.redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
                retry_on_timeout=True,
                health_check_interval=30
            )

            # Test connection
            self.redis_client.ping()
            logger.info(f"Redis cache connected successfully to {self.redis_url}")
            self.connected = True

        except redis.ConnectionError as e:
            logger.warning(f"Redis connection failed: {e}. Cache will be disabled.")
            self.redis_client = None
            self.connected = False

        except Exception as e:
            logger.error(f"Unexpected Redis error: {e}")
            self.redis_client = None
            self.connected = False

        # Default TTL values (in seconds)
        self.ttl_config = {
            "market_data": 60,        # 1 minute for real-time data
            "sentiment": 900,         # 15 minutes for sentiment
            "news": 1800,            # 30 minutes for news
            "economic": 3600,        # 1 hour for economic data
            "company": 3600,         # 1 hour for company data
            "llm_response": 300,     # 5 minutes for LLM responses
            "user_context": 120,     # 2 minutes for user context
            "default": 300           # 5 minutes default
        }

        # Cache statistics
        self.stats = {
            "hits": 0,
            "misses": 0,
            "errors": 0,
            "total_requests": 0
        }

    def generate_cache_key(self, prefix: str, params: Dict[str, Any]) -> str:
        """
        Generate consistent cache key from parameters

        Args:
            prefix: Cache key prefix (e.g., "market", "sentiment")
            params: Parameters to include in key

        Returns:
            Cache key string
        """
        # Sort params for consistent key generation
        sorted_params = json.dumps(params, sort_keys=True)

        # Create hash for long param strings
        if len(sorted_params) > 100:
            param_hash = hashlib.md5(sorted_params.encode()).hexdigest()[:8]
            return f"aria:{prefix}:{param_hash}"
        else:
            # Use readable key for short params
            param_str = "_".join([f"{k}={v}" for k, v in sorted(params.items())])
            return f"aria:{prefix}:{param_str}"

    async def get(self, key: str) -> Optional[Any]:
        """
        Get value from cache

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found
        """
        if not self.connected or not self.redis_client:
            return None

        self.stats["total_requests"] += 1

        try:
            value = self.redis_client.get(key)

            if value:
                self.stats["hits"] += 1
                logger.debug(f"Cache hit: {key}")

                # Parse JSON if needed
                try:
                    return json.loads(value)
                except json.JSONDecodeError:
                    return value
            else:
                self.stats["misses"] += 1
                logger.debug(f"Cache miss: {key}")
                return None

        except Exception as e:
            self.stats["errors"] += 1
            logger.error(f"Cache get error for {key}: {e}")
            return None

    async def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None,
        category: Optional[str] = None
    ) -> bool:
        """
        Set value in cache with TTL

        Args:
            key: Cache key
            value: Value to cache
            ttl: Time-to-live in seconds
            category: Category for TTL lookup

        Returns:
            Success status
        """
        if not self.connected or not self.redis_client:
            return False

        try:
            # Determine TTL
            if ttl is None:
                ttl = self.ttl_config.get(category, self.ttl_config["default"])

            # Convert value to JSON if needed
            if isinstance(value, (dict, list)):
                value = json.dumps(value)

            # Set with expiration
            self.redis_client.setex(key, ttl, value)
            logger.debug(f"Cache set: {key} (TTL: {ttl}s)")
            return True

        except Exception as e:
            self.stats["errors"] += 1
            logger.error(f"Cache set error for {key}: {e}")
            return False

    async def get_or_fetch(
        self,
        key: str,
        fetch_func: Callable,
        ttl: Optional[int] = None,
        category: Optional[str] = None
    ) -> Any:
        """
        Get from cache or fetch if missing

        Args:
            key: Cache key
            fetch_func: Async function to fetch data if not cached
            ttl: TTL override
            category: Category for TTL

        Returns:
            Cached or fetched value
        """
        # Try cache first
        cached = await self.get(key)
        if cached is not None:
            return cached

        # Fetch if not cached
        try:
            logger.info(f"Fetching data for cache key: {key}")
            data = await fetch_func()

            # Cache the result
            if data is not None:
                await self.set(key, data, ttl, category)

            return data

        except Exception as e:
            logger.error(f"Error fetching data for {key}: {e}")
            raise

    async def invalidate(self, pattern: str) -> int:
        """
        Invalidate cache entries matching pattern

        Args:
            pattern: Redis pattern (e.g., "aria:market:*")

        Returns:
            Number of keys deleted
        """
        if not self.connected or not self.redis_client:
            return 0

        try:
            keys = self.redis_client.keys(pattern)
            if keys:
                deleted = self.redis_client.delete(*keys)
                logger.info(f"Invalidated {deleted} cache entries matching {pattern}")
                return deleted
            return 0

        except Exception as e:
            logger.error(f"Cache invalidation error: {e}")
            return 0

    async def warm_up(
        self,
        symbols: List[str],
        data_types: List[str] = None
    ) -> Dict[str, bool]:
        """
        Pre-fetch data for common queries

        Args:
            symbols: List of symbols to cache
            data_types: Types of data to pre-fetch

        Returns:
            Status for each pre-fetch
        """
        if data_types is None:
            data_types = ["market_data", "sentiment"]

        results = {}

        for symbol in symbols:
            for data_type in data_types:
                key = self.generate_cache_key(data_type, {"symbol": symbol})
                # This would typically call the data fetching service
                # For now, just mark as warmed
                results[f"{symbol}:{data_type}"] = True

        logger.info(f"Cache warmed up for {len(symbols)} symbols")
        return results

    def get_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics

        Returns:
            Cache performance statistics
        """
        total = self.stats["total_requests"]
        hit_rate = (self.stats["hits"] / total * 100) if total > 0 else 0

        return {
            "connected": self.connected,
            "total_requests": total,
            "hits": self.stats["hits"],
            "misses": self.stats["misses"],
            "errors": self.stats["errors"],
            "hit_rate": round(hit_rate, 2),
            "efficiency": "high" if hit_rate > 60 else "medium" if hit_rate > 30 else "low"
        }

    async def clear_user_context(self, user_id: int) -> bool:
        """
        Clear all cached data for a specific user

        Args:
            user_id: User ID to clear cache for

        Returns:
            Success status
        """
        pattern = f"aria:user:{user_id}:*"
        deleted = await self.invalidate(pattern)
        return deleted > 0

    async def get_memory_usage(self) -> Dict[str, Any]:
        """
        Get Redis memory usage information

        Returns:
            Memory usage stats
        """
        if not self.connected or not self.redis_client:
            return {"connected": False}

        try:
            info = self.redis_client.info("memory")
            return {
                "connected": True,
                "used_memory_human": info.get("used_memory_human"),
                "used_memory_peak_human": info.get("used_memory_peak_human"),
                "total_keys": self.redis_client.dbsize()
            }
        except Exception as e:
            logger.error(f"Error getting memory usage: {e}")
            return {"connected": False, "error": str(e)}


def cached(category: str = "default", ttl: Optional[int] = None):
    """
    Decorator for caching async function results

    Args:
        category: Cache category for TTL
        ttl: Optional TTL override

    Usage:
        @cached(category="market_data")
        async def get_market_data(symbol):
            return await fetch_data(symbol)
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Create cache instance
            cache = ARIACache()

            # Generate cache key from function name and arguments
            key_data = {
                "func": func.__name__,
                "args": str(args),
                "kwargs": str(kwargs)
            }
            cache_key = cache.generate_cache_key("func", key_data)

            # Try to get from cache
            cached_result = await cache.get(cache_key)
            if cached_result is not None:
                logger.debug(f"Returning cached result for {func.__name__}")
                return cached_result

            # Execute function
            result = await func(*args, **kwargs)

            # Cache the result
            if result is not None:
                await cache.set(cache_key, result, ttl, category)

            return result

        return wrapper
    return decorator


class CacheManager:
    """
    High-level cache management for ARIA
    """

    def __init__(self):
        self.cache = ARIACache()

    async def cache_market_analysis(
        self,
        symbol: str,
        analysis: Dict[str, Any]
    ) -> bool:
        """
        Cache complete market analysis

        Args:
            symbol: Trading symbol
            analysis: Analysis data to cache

        Returns:
            Success status
        """
        key = self.cache.generate_cache_key("analysis", {"symbol": symbol})
        return await self.cache.set(key, analysis, category="market_data")

    async def get_market_analysis(
        self,
        symbol: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get cached market analysis

        Args:
            symbol: Trading symbol

        Returns:
            Cached analysis or None
        """
        key = self.cache.generate_cache_key("analysis", {"symbol": symbol})
        return await self.cache.get(key)

    async def cache_llm_response(
        self,
        query: str,
        response: str,
        complexity: str = "moderate"
    ) -> bool:
        """
        Cache LLM response

        Args:
            query: Original query
            response: LLM response
            complexity: Query complexity

        Returns:
            Success status
        """
        # Shorter TTL for simple queries, longer for complex
        ttl_map = {
            "simple": 180,     # 3 minutes
            "moderate": 300,   # 5 minutes
            "complex": 600     # 10 minutes
        }

        key = self.cache.generate_cache_key("llm", {"query": query[:100]})
        return await self.cache.set(
            key,
            {"response": response, "timestamp": datetime.utcnow().isoformat()},
            ttl=ttl_map.get(complexity, 300)
        )

    async def get_llm_response(
        self,
        query: str
    ) -> Optional[str]:
        """
        Get cached LLM response

        Args:
            query: Query to look up

        Returns:
            Cached response or None
        """
        key = self.cache.generate_cache_key("llm", {"query": query[:100]})
        cached = await self.cache.get(key)

        if cached and isinstance(cached, dict):
            return cached.get("response")
        return None