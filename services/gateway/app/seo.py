from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, datetime
from typing import Any
from xml.sax.saxutils import escape

from fastapi import APIRouter, Request
from fastapi.responses import Response

logger = logging.getLogger(__name__)

# A single sitemap is capped by the sitemaps protocol at 50 MB / 50 000 URLs.
# The catalogue is an order of magnitude smaller today; if it ever exceeds the
# cap, split this route into a sitemap index before raising the limit.
SITEMAP_MAX_URLS = 50_000
SITEMAP_PAGE_SIZE = 100
SITEMAP_CACHE_TTL_SECONDS = 1_800.0

router = APIRouter()

_cache: tuple[float, str] | None = None
_cache_lock = asyncio.Lock()


def reset_sitemap_cache() -> None:
    """Clear the in-process cache (used by tests and after a URL change)."""
    global _cache
    _cache = None


def _xml(value: str) -> str:
    return escape(value, {'"': '&quot;', "'": '&apos;'})


def _lastmod(value: Any) -> str | None:
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, str):
        try:
            moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    # Source sites occasionally return future publication dates.  A lastmod in
    # the future looks untrustworthy to crawlers, so omit it instead of
    # pretending the page changed today.
    if moment.date() > date.today():
        return None
    return moment.date().isoformat()


def build_sitemap_xml(entries: list[tuple[str, str | None]]) -> str:
    """Render (loc, lastmod) pairs as a sitemaps.org urlset."""
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    seen: set[str] = set()
    written = 0
    for loc, lastmod in entries:
        if written >= SITEMAP_MAX_URLS:
            break
        if loc in seen:
            continue
        seen.add(loc)
        written += 1
        lines.append("  <url>")
        lines.append(f"    <loc>{_xml(loc)}</loc>")
        if lastmod:
            lines.append(f"    <lastmod>{_xml(lastmod)}</lastmod>")
        lines.append("  </url>")
    lines.append("</urlset>")
    return "\n".join(lines) + "\n"


async def _collect_entries(request: Request) -> list[tuple[str, str | None]]:
    """Static pages first, then every catalogue title that has chapters."""
    catalog = request.app.state.catalog
    base = str(request.app.state.settings.public_web_url).rstrip("/")
    entries: list[tuple[str, str | None]] = [
        (f"{base}/", None),
        (f"{base}/catalogue", None),
        (f"{base}/sources", None),
    ]

    page = 1
    while len(entries) < SITEMAP_MAX_URLS:
        response = await catalog.manga_list(
            {"sort": "updated", "page": page, "limit": SITEMAP_PAGE_SIZE}
        )
        items = list(response.items)
        if not items:
            break

        for manga in items:
            if len(entries) >= SITEMAP_MAX_URLS:
                break
            # Empty title pages are thin pages; they stay out until chapters
            # exist.  The API can legitimately return zero before an import.
            if (getattr(manga, "chapters_count", 0) or 0) <= 0:
                continue
            lastmod = _lastmod(
                getattr(manga, "last_chapter_at", None)
            ) or _lastmod(getattr(manga, "updated_at", None))
            entries.append((f"{base}/manga/{manga.id}", lastmod))

        if not getattr(response, "has_next", False):
            break
        page += 1

    return entries


async def _sitemap_response(request: Request) -> Response:
    global _cache

    now = time.monotonic()
    async with _cache_lock:
        if _cache is not None and now - _cache[0] < SITEMAP_CACHE_TTL_SECONDS:
            xml = _cache[1]
        else:
            try:
                entries = await _collect_entries(request)
            except Exception:
                if _cache is not None:
                    # A stale but complete sitemap is safer than a partial one.
                    logger.exception("sitemap refresh failed; serving stale copy")
                    xml = _cache[1]
                else:
                    raise
            else:
                xml = build_sitemap_xml(entries)
                _cache = (now, xml)

    return Response(
        content=xml,
        media_type="application/xml",
        headers={
            "Cache-Control": "public, max-age=900, stale-while-revalidate=3600",
        },
    )


# The documented URL is /sitemap.xml (nginx needs a one-line proxy location).
# The /api/v1 alias works with the existing gateway proxy and lets the lead
# validate the route before touching nginx.
@router.get("/sitemap.xml", include_in_schema=False)
@router.get("/api/v1/sitemap.xml", include_in_schema=False)
async def sitemap(request: Request) -> Response:
    return await _sitemap_response(request)
