from __future__ import annotations

import time

from manga_common.cache import MemoryCache
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Small per-IP limiter.

    Redis-backed limiting is deliberately out of scope for the first release:
    the gateway is the only public entry point and a single process is enough
    for the expected traffic.  The interface is intentionally simple so it can
    be replaced by a Redis sliding window later.
    """

    def __init__(
        self,
        app,  # type: ignore[no-untyped-def]
        *,
        default_limit: int = 240,
        search_limit: int = 60,
        import_limit: int = 10,
    ) -> None:
        super().__init__(app)
        self.default_limit = default_limit
        self.search_limit = search_limit
        self.import_limit = import_limit
        self.cache = MemoryCache(max_items=20_000)

    def _limit_for(self, path: str) -> int:
        if path.endswith("/manga/import"):
            return self.import_limit
        if path.endswith("/manga/search"):
            return self.search_limit
        # A single chapter can contain 60+ pages.  Image reads are cheap for us
        # because media caches them; do not rate-limit the reader into failure.
        if "/images/" in path:
            return max(self.default_limit * 5, 1200)
        return self.default_limit

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        if request.method == "OPTIONS" or not request.url.path.startswith("/api/"):
            return await call_next(request)
        real_ip = request.headers.get("X-Real-IP", "").strip()
        ip = real_ip or (request.client.host if request.client else "unknown")
        window = int(time.time() // 60)
        key = f"rl:{ip}:{window}"
        used = await self.cache.get_json(key) or 0
        limit = self._limit_for(request.url.path)
        if used >= limit:
            return JSONResponse(
                {
                    "error": {
                        "code": "rate_limited",
                        "message": "Слишком много запросов. Попробуйте через минуту.",
                        "details": {"limit": limit},
                    }
                },
                status_code=429,
                headers={"Retry-After": "60"},
            )
        await self.cache.set_json(key, used + 1, ttl=70)
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(max(0, limit - used - 1))
        return response
