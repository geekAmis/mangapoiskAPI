from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, datetime
from typing import Any
from xml.sax.saxutils import escape

from fastapi import APIRouter, Request
from fastapi.responses import Response
from manga_common.text import build_url_slug

logger = logging.getLogger(__name__)

# A single sitemap is capped by the sitemaps protocol at 50 MB / 50 000 URLs.
# The catalogue is an order of magnitude smaller today; if it ever exceeds the
# cap, split this route into a sitemap index before raising the limit.
SITEMAP_MAX_URLS = 50_000
SITEMAP_PAGE_SIZE = 100
SITEMAP_CACHE_TTL_SECONDS = 1_800.0

# Public legal pages.  /age is intentionally indexable: it is a substantive
# policy page with a visible 18+ warning, not a duplicate or a gated doorway.
# The date must be bumped together with LEGAL_UPDATED in apps/web/src/lib/legal.ts.
LEGAL_SITEMAP_PAGES: tuple[tuple[str, str], ...] = (
    ("/terms", "2026-11-13"),
    ("/privacy", "2026-11-13"),
    ("/dmca", "2026-11-13"),
    ("/contacts", "2026-11-13"),
    ("/age", "2026-11-13"),
)

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
    return await _collect_entries_for_app(request.app)


async def _collect_entries_for_app(app) -> list[tuple[str, str | None]]:  # type: ignore[no-untyped-def]
    catalog = app.state.catalog
    base = str(app.state.settings.public_web_url).rstrip("/")
    entries: list[tuple[str, str | None]] = [
        (f"{base}/", None),
        (f"{base}/catalogue", None),
        (f"{base}/sources", None),
        *((f"{base}{path}", lastmod) for path, lastmod in LEGAL_SITEMAP_PAGES),
    ]

    # Preferred path: one dedicated catalogue query for all canonical titles.
    # The old paginated path made ~65 HTTP round trips for a few thousand
    # titles and took 79 s cold in production.
    sitemap_getter = getattr(catalog, "sitemap_entries", None)
    if callable(sitemap_getter):
        try:
            rows = await sitemap_getter()
        except Exception:
            logger.warning("catalog sitemap endpoint failed; falling back to pages", exc_info=True)
        else:
            for row in rows:
                if len(entries) >= SITEMAP_MAX_URLS:
                    break
                lastmod = _lastmod(getattr(row, "last_chapter_at", None)) or _lastmod(
                    getattr(row, "updated_at", None)
                )
                # The sitemap must only advertise the canonical slug URL.
                # Legacy rows still missing a stored slug get the same
                # deterministic transliteration the catalog read path uses.
                slug = getattr(row, "url_slug", None) or build_url_slug(
                    getattr(row, "title", None)
                )
                entries.append((f"{base}/manga/{row.id}-{slug}", lastmod))
            return entries

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
            # 18+ titles are deliberately excluded from the sitemap.
            if getattr(manga, "adult", False):
                continue
            lastmod = _lastmod(
                getattr(manga, "last_chapter_at", None)
            ) or _lastmod(getattr(manga, "updated_at", None))
            slug = getattr(manga, "url_slug", None) or build_url_slug(
                getattr(manga, "title", None)
            )
            entries.append((f"{base}/manga/{manga.id}-{slug}", lastmod))

        if not getattr(response, "has_next", False):
            break
        page += 1

    return entries


async def warm_sitemap_cache(app, *, attempts: int = 6) -> None:  # type: ignore[no-untyped-def]
    """Populate the in-process cache after startup, without blocking health."""

    global _cache
    for attempt in range(1, attempts + 1):
        started = time.monotonic()
        try:
            entries = await _collect_entries_for_app(app)
        except asyncio.CancelledError:
            raise
        except Exception:
            if attempt >= attempts:
                logger.warning("sitemap cache warmup failed", exc_info=True)
                return
            await asyncio.sleep(min(10.0, 2.0 * attempt))
            continue
        xml = build_sitemap_xml(entries)
        _cache = (time.monotonic(), xml)
        logger.info(
            "sitemap cache warmed: %s urls in %.2fs",
            len(entries),
            time.monotonic() - started,
        )
        return


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
