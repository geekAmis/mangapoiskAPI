from __future__ import annotations

import asyncio
import json
import time
from collections import OrderedDict
from typing import Any, Protocol


class Cache(Protocol):
    async def get_json(self, key: str) -> Any | None: ...

    async def set_json(self, key: str, value: Any, ttl: int | None = None) -> None: ...

    async def delete(self, key: str) -> None: ...

    async def ping(self) -> bool: ...

    async def close(self) -> None: ...


class MemoryCache:
    """Small LRU cache used in tests and single-process development."""

    def __init__(self, max_items: int = 2048) -> None:
        self._data: OrderedDict[str, tuple[float | None, Any]] = OrderedDict()
        self._max_items = max_items
        self._lock = asyncio.Lock()

    def _purge(self) -> None:
        now = time.monotonic()
        expired = [key for key, (expires, _) in self._data.items() if expires and expires <= now]
        for key in expired:
            self._data.pop(key, None)
        while len(self._data) > self._max_items:
            self._data.popitem(last=False)

    async def get_json(self, key: str) -> Any | None:
        async with self._lock:
            self._purge()
            item = self._data.get(key)
            if not item:
                return None
            expires, value = item
            if expires and expires <= time.monotonic():
                self._data.pop(key, None)
                return None
            self._data.move_to_end(key)
            return value

    async def set_json(self, key: str, value: Any, ttl: int | None = None) -> None:
        async with self._lock:
            expires = time.monotonic() + ttl if ttl else None
            self._data[key] = (expires, value)
            self._data.move_to_end(key)
            self._purge()

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._data.pop(key, None)

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        self._data.clear()


class RedisCache:
    def __init__(self, url: str) -> None:
        from redis.asyncio import Redis

        self._redis = Redis.from_url(url, encoding="utf-8", decode_responses=True)

    async def get_json(self, key: str) -> Any | None:
        raw = await self._redis.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    async def set_json(self, key: str, value: Any, ttl: int | None = None) -> None:
        await self._redis.set(key, json.dumps(value, ensure_ascii=False), ex=ttl)

    async def delete(self, key: str) -> None:
        await self._redis.delete(key)

    async def ping(self) -> bool:
        try:
            return bool(await self._redis.ping())
        except Exception:
            return False

    async def close(self) -> None:
        await self._redis.aclose()


def create_cache(redis_url: str | None) -> Cache:
    if redis_url:
        return RedisCache(redis_url)
    return MemoryCache()


def cache_key(*parts: object) -> str:
    return ":".join(str(part).strip().lower() for part in parts if part is not None)
