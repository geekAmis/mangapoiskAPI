from __future__ import annotations

import hashlib
import time
import uuid
from collections import OrderedDict
from typing import Any

RECOMMENDATION_CACHE_TTL_SECONDS = 120.0
RECOMMENDATION_CACHE_MAX_ITEMS = 512


class TTLCache:
    def __init__(self, *, ttl: float, max_items: int) -> None:
        self.ttl = ttl
        self.max_items = max_items
        self._items: OrderedDict[str, tuple[float, Any]] = OrderedDict()

    def get(self, key: str) -> Any | None:
        item = self._items.get(key)
        if item is None:
            return None
        expires_at, value = item
        if expires_at <= time.monotonic():
            self._items.pop(key, None)
            return None
        self._items.move_to_end(key)
        return value

    def set(self, key: str, value: Any) -> None:
        self._items[key] = (time.monotonic() + self.ttl, value)
        self._items.move_to_end(key)
        while len(self._items) > self.max_items:
            self._items.popitem(last=False)

    def clear(self) -> None:
        self._items.clear()


recommendation_cache = TTLCache(
    ttl=RECOMMENDATION_CACHE_TTL_SECONDS,
    max_items=RECOMMENDATION_CACHE_MAX_ITEMS,
)


def recommendation_cache_key(
    *,
    seed_manga_id: uuid.UUID | None,
    history_ids: list[uuid.UUID],
    bookmark_ids: list[uuid.UUID],
    exclude_ids: list[uuid.UUID],
    limit: int,
) -> str:
    raw = "|".join(
        [
            str(seed_manga_id or ""),
            ",".join(str(item) for item in sorted(history_ids)),
            ",".join(str(item) for item in sorted(bookmark_ids)),
            ",".join(str(item) for item in sorted(exclude_ids)),
            str(limit),
        ]
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def clear_recommendation_cache() -> None:
    recommendation_cache.clear()
