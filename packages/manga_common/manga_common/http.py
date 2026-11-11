from __future__ import annotations

import asyncio
import contextlib
import random
import time
from typing import Any

import httpx

from .config import Settings
from .errors import RateLimitError, TimeoutError, UpstreamError
from .logging import request_id_ctx


class AsyncRateLimiter:
    """Simple async token bucket.  One instance per upstream host."""

    def __init__(self, per_minute: int, burst: int | None = None) -> None:
        self.per_minute = max(1, per_minute)
        self.capacity = max(1, burst or self.per_minute)
        self.tokens = float(self.capacity)
        self.updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                refill = (now - self.updated) * (self.per_minute / 60.0)
                if refill > 0:
                    self.tokens = min(self.capacity, self.tokens + refill)
                    self.updated = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                wait = (1 - self.tokens) / (self.per_minute / 60.0)
                await asyncio.sleep(min(max(wait, 0.05), 5.0))


def build_client(settings: Settings, *, base_url: str = "") -> httpx.AsyncClient:
    headers = {
        "User-Agent": settings.http_user_agent,
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    }
    limits = httpx.Limits(
        max_connections=settings.http_max_connections,
        max_keepalive_connections=max(5, settings.http_max_connections // 2),
    )
    return httpx.AsyncClient(
        base_url=base_url,
        headers=headers,
        timeout=httpx.Timeout(settings.http_timeout_seconds),
        limits=limits,
        follow_redirects=True,
    )


async def request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    settings: Settings,
    limiter: AsyncRateLimiter | None = None,
    retries: int | None = None,
    **kwargs: Any,
) -> httpx.Response:
    attempts = retries if retries is not None else settings.scraper_max_retries
    last_error: Exception | None = None
    for attempt in range(attempts + 1):
        if limiter:
            await limiter.acquire()
        headers = dict(kwargs.pop("headers", {}) or {})
        headers.setdefault("X-Request-ID", request_id_ctx.get())
        try:
            response = await client.request(method, url, headers=headers, **kwargs)
        except httpx.TimeoutException as exc:
            last_error = exc
            if attempt >= attempts:
                raise TimeoutError(f"Upstream timed out: {url}") from exc
        except httpx.HTTPError as exc:
            last_error = exc
            if attempt >= attempts:
                raise UpstreamError(f"Upstream request failed: {url}", details=str(exc)) from exc
        else:
            if response.status_code in {429, 500, 502, 503, 504} and attempt < attempts:
                retry_after = response.headers.get("Retry-After")
                delay = settings.scraper_backoff_seconds * (2**attempt)
                if retry_after:
                    with contextlib.suppress(ValueError):
                        delay = max(delay, float(retry_after))
                await asyncio.sleep(min(delay + random.random() * 0.4, 30))
                continue
            if response.status_code == 429:
                raise RateLimitError("Upstream rate limit reached", details=url)
            if response.status_code >= 400:
                raise UpstreamError(
                    f"Upstream returned HTTP {response.status_code}",
                    details={"url": url, "status_code": response.status_code},
                )
            return response
        await asyncio.sleep(min(settings.scraper_backoff_seconds * (2**attempt) + random.random(), 30))
    raise UpstreamError(f"Upstream request failed: {url}", details=str(last_error))


async def get_text(
    client: httpx.AsyncClient,
    url: str,
    *,
    settings: Settings,
    limiter: AsyncRateLimiter | None = None,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
) -> str:
    response = await request_with_retry(
        client, "GET", url, settings=settings, limiter=limiter, headers=headers, params=params
    )
    return response.text


async def get_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    settings: Settings,
    limiter: AsyncRateLimiter | None = None,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
) -> Any:
    response = await request_with_retry(
        client, "GET", url, settings=settings, limiter=limiter, headers=headers, params=params
    )
    try:
        return response.json()
    except ValueError as exc:
        raise UpstreamError(
            f"Upstream returned invalid JSON: {url}", details=response.text[:300]
        ) from exc
