"""Catalog-specific gauges for ``/metrics``.

Crawler backlog and ETA live in SQLite, so they are collected on demand with a
small cache.  A scrape every 15 seconds therefore costs one read per cache TTL,
not one read per scrape.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from manga_common.metrics import metrics

logger = logging.getLogger(__name__)


class CatalogMetricsCollector:
    def __init__(self, service, *, cache_seconds: float = 10.0) -> None:  # type: ignore[no-untyped-def]
        self.service = service
        self.cache_seconds = cache_seconds
        self._last_refresh = 0.0

    async def collect(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_refresh < self.cache_seconds:
            return
        self._last_refresh = now
        try:
            stats = await self.service.catalog_stats()
            states = await self.service.crawl_states()
        except Exception as exc:
            logger.warning("catalog metrics refresh failed: %s", exc)
            metrics.inc("mangapoisk_metrics_collector_errors_total")
            return
        await self._publish(stats, states)

    async def _publish(self, stats: Any, states: list[Any]) -> None:
        metrics.set("mangapoisk_catalog_manga", int(getattr(stats, "manga", 0) or 0))
        metrics.set("mangapoisk_catalog_chapters", int(getattr(stats, "chapters", 0) or 0))
        metrics.set(
            "mangapoisk_catalog_enrichment_backlog",
            int(
                getattr(stats, "pending_enrichment", 0)
                or getattr(stats, "pending", 0)
                or 0
            ),
        )
        metrics.set(
            "mangapoisk_catalog_enrichment_retrying",
            int(getattr(stats, "retrying_enrichment", 0) or 0),
        )
        for source in getattr(stats, "sources", []) or []:
            code = str(getattr(source, "source", "") or "")
            if code:
                metrics.set(
                    "mangapoisk_crawler_backlog_source",
                    int(getattr(source, "pending", 0) or 0),
                    source=code,
                )
        backlog = getattr(stats, "search_backfill", None)
        if backlog is not None:
            metrics.set(
                "mangapoisk_search_backfill_remaining",
                int(getattr(backlog, "remaining", 0) or 0),
            )
            metrics.set(
                "mangapoisk_search_backfill_progress_ratio",
                round(float(getattr(backlog, "progress_percent", 0.0) or 0.0) / 100, 4),
            )
            metrics.set(
                "mangapoisk_search_backfill_failed",
                1 if getattr(backlog, "status", "") == "failed" else 0,
            )
        for state in states:
            source = str(getattr(state, "source", "") or "")
            mode = str(getattr(state, "mode", "") or "")
            if not source or mode not in {"full", "incremental"}:
                continue
            status = str(getattr(state, "status", "") or "pending")
            metrics.set(
                "mangapoisk_crawler_state",
                1,
                source=source,
                mode=mode,
                status=status,
            )
            page = int(getattr(state, "page", 0) or 0)
            total = getattr(state, "total_pages", None)
            if total:
                metrics.set(
                    "mangapoisk_crawler_progress_ratio",
                    round(min(1.0, page / int(total)), 4),
                    source=source,
                    mode=mode,
                )
            eta = getattr(state, "eta_seconds", None)
            if eta is not None:
                metrics.set(
                    "mangapoisk_crawler_eta_seconds",
                    float(eta),
                    source=source,
                    mode=mode,
                )
