"""Media storage gauges for ``/metrics`` (archive and image-cache usage)."""

from __future__ import annotations

import logging
import time

from manga_common.metrics import metrics

logger = logging.getLogger(__name__)


class MediaMetricsCollector:
    def __init__(self, cache, archives, *, cache_seconds: float = 10.0) -> None:  # type: ignore[no-untyped-def]
        self.cache = cache
        self.archives = archives
        self.cache_seconds = cache_seconds
        self._last_refresh = 0.0

    async def collect(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_refresh < self.cache_seconds:
            return
        self._last_refresh = now
        try:
            image = await self.cache.stats()
            archive = await self.archives.stats()
        except Exception as exc:
            logger.warning("media metrics refresh failed: %s", exc)
            metrics.inc("mangapoisk_metrics_collector_errors_total")
            return
        metrics.set("mangapoisk_media_cache_bytes", int(image.used_bytes))
        metrics.set("mangapoisk_media_cache_cap_bytes", int(image.cap_bytes))
        metrics.set("mangapoisk_media_cache_files", int(image.files))
        metrics.set("mangapoisk_media_cache_evictions_total", int(image.evictions))
        metrics.set(
            "mangapoisk_media_cache_usage_ratio",
            round(image.usage_percent / 100, 4),
        )
        metrics.set("mangapoisk_media_archive_total", int(archive.total))
        metrics.set("mangapoisk_media_archive_done", int(archive.done))
        metrics.set("mangapoisk_media_archive_failed", int(archive.failed))
        metrics.set("mangapoisk_media_archive_pending", int(archive.pending))
        metrics.set("mangapoisk_media_archive_bytes", int(archive.done_bytes))
        metrics.set("mangapoisk_media_archive_cap_bytes", int(self.archives.max_bytes))
        metrics.set("mangapoisk_media_archive_evictions_total", int(archive.evictions))
        if self.archives.max_bytes:
            metrics.set(
                "mangapoisk_media_archive_usage_ratio",
                round(archive.done_bytes / self.archives.max_bytes, 4),
            )
