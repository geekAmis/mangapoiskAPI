from __future__ import annotations

import asyncio
import hashlib
import io
import ipaddress
import json
import logging
import mimetypes
import os
import re
import socket
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

from manga_common.config import Settings
from manga_common.errors import UpstreamError
from manga_common.http import AsyncRateLimiter, build_client, request_with_retry
from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/avif": ".avif",
}
_ALLOWED_TYPES = frozenset(_EXTENSIONS)
_MAX_REDIRECTS = 5

_MAX_BYTES = 40 * 1024 * 1024

# Reader image variants.  Originals are always cached untouched and remain the
# only source for archives and exports; variants are an additional cache entry.
ALLOWED_WIDTHS: tuple[int, ...] = (480, 720, 1080, 1280, 1600)
_VARIANT_SOURCE_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
_VARIANT_CONTENT_TYPE = "image/webp"
_WEBP_QUALITY = 82
_WEBP_METHOD = 4

# Only files produced by this cache are eviction candidates.  This deliberately
# excludes archive ZIPs, SQLite files and any unrelated metadata that may share
# the volume.  Sidecar JSON is removed only together with its image.
_ORIGINAL_NAME = re.compile(r"^[0-9a-f]{64}\.(?:jpe?g|png|webp|gif|avif)$")
_VARIANT_NAME = re.compile(r"^[0-9a-f]{64}-w\d+\.webp$")
_SIDECAR_SUFFIX = ".json"
_TOUCH_INTERVAL_SECONDS = 60.0
_STATS_TTL_SECONDS = 30.0
_USAGE_WARNING_PERCENT = 80.0
_USAGE_CRITICAL_PERCENT = 90.0


def usage_level(used_bytes: int, cap_bytes: int) -> str:
    """Classify cache usage for stats and admin warnings."""

    if cap_bytes <= 0:
        return "unbounded"
    percent = used_bytes / cap_bytes * 100
    if percent >= _USAGE_CRITICAL_PERCENT:
        return "critical"
    if percent >= _USAGE_WARNING_PERCENT:
        return "warning"
    return "ok"


def usage_percent(used_bytes: int, cap_bytes: int) -> float:
    if cap_bytes <= 0:
        return 0.0
    return round(used_bytes / cap_bytes * 100, 1)


def resolve_width(width: int | None) -> int | None:
    """Return the supported variant width nearest to ``width``."""
    if width is None or width <= 0:
        return None
    return min(ALLOWED_WIDTHS, key=lambda allowed: (abs(allowed - width), -allowed))


@dataclass(slots=True)
class MediaFile:
    path: Path
    content_type: str
    size: int
    etag: str


@dataclass(slots=True)
class MediaCacheStats:
    used_bytes: int
    cap_bytes: int
    files: int
    evictions: int
    last_pruned_at: datetime | None

    @property
    def usage_percent(self) -> float:
        return usage_percent(self.used_bytes, self.cap_bytes)

    @property
    def level(self) -> str:
        return usage_level(self.used_bytes, self.cap_bytes)


@dataclass(slots=True)
class CachePruneResult:
    removed: int
    freed_bytes: int
    used_bytes: int
    cap_bytes: int
    dry_run: bool


@dataclass(slots=True)
class _CacheEntry:
    path: Path
    meta_path: Path | None
    size: int
    mtime: float


class MediaCache:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.root = Path(settings.media_cache_dir).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.client = build_client(settings)
        # Redirects are followed manually so every hop is re-validated.
        self.client.follow_redirects = False
        self.limiter = AsyncRateLimiter(max(30, settings.scraper_requests_per_minute * 2), burst=10)
        self._locks: dict[str, asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()
        self._allowed_hosts = {
            host.strip().lower()
            for host in (os.getenv("MEDIA_ALLOWED_HOSTS") or "").split(",")
            if host.strip()
        }
        self.max_bytes = max(0, int(getattr(settings, "media_cache_max_bytes", 0)))
        self.prune_interval_seconds = max(
            0, int(getattr(settings, "media_cache_prune_interval_seconds", 60 * 60))
        )
        self.prune_min_age_seconds = max(
            0, int(getattr(settings, "media_cache_prune_min_age_seconds", 5 * 60))
        )
        self._prune_guard = asyncio.Lock()
        self._prune_task: asyncio.Task[None] | None = None
        self._evictions = 0
        self._last_pruned_at: datetime | None = None
        self._stats_cache: MediaCacheStats | None = None
        self._stats_cached_at = 0.0
        self._touched_at: dict[str, float] = {}

    def _invalidate_stats(self) -> None:
        self._stats_cache = None
        self._stats_cached_at = 0.0

    def _touch(self, path: Path) -> None:
        """Refresh the LRU timestamp without writing it on every request."""

        key = str(path)
        now = time.monotonic()
        if now - self._touched_at.get(key, 0.0) < _TOUCH_INTERVAL_SECONDS:
            return
        self._touched_at[key] = now
        try:
            os.utime(path, None)
        except OSError:
            logger.debug("could not refresh media cache timestamp", extra={"path": key})

    async def _validate_url(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise UpstreamError("Invalid image URL")
        host = parsed.hostname.lower()
        if host in {"localhost", "localhost.localdomain", "0.0.0.0", "::1"} or host.endswith(".local"):
            raise UpstreamError("Private image host is not allowed")
        if self._allowed_hosts and host not in self._allowed_hosts and not any(
            host.endswith(f".{allowed}") for allowed in self._allowed_hosts
        ):
            raise UpstreamError("Image host is not in MEDIA_ALLOWED_HOSTS")
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(host, None)
        except socket.gaierror as exc:
            raise UpstreamError("Image host cannot be resolved") from exc
        for info in infos:
            raw = str(info[4][0]).split("%", 1)[0]
            try:
                address = ipaddress.ip_address(raw)
            except ValueError as exc:
                raise UpstreamError("Invalid image host address") from exc
            if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
                address = address.ipv4_mapped
            if (
                address.is_private
                or address.is_loopback
                or address.is_link_local
                or address.is_reserved
                or address.is_multicast
                or address.is_unspecified
            ):
                raise UpstreamError("Private image host is not allowed")

    def _base(self, url: str) -> tuple[Path, Path, str]:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        shard = self.root / digest[:2]
        shard.mkdir(parents=True, exist_ok=True)
        return shard / digest, shard / f"{digest}.json", digest

    def _variant_paths(self, key_digest: str, width: int) -> tuple[Path, Path, str]:
        shard = self.root / key_digest[:2]
        shard.mkdir(parents=True, exist_ok=True)
        key = f"{key_digest}-w{width}"
        return shard / f"{key}.webp", shard / f"{key}.json", key

    def _from_disk(self, base: Path, meta_path: Path, digest: str) -> MediaFile | None:
        if not meta_path.exists():
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            path = base.parent / meta["filename"]
            if not path.exists():
                return None
            self._touch(path)
            return MediaFile(
                path=path,
                content_type=meta.get("content_type", "application/octet-stream"),
                size=path.stat().st_size,
                etag=digest,
            )
        except (OSError, ValueError, KeyError):
            return None

    def _variant_from_disk(self, path: Path, meta_path: Path, key: str) -> MediaFile | None:
        if not path.exists() or not meta_path.exists():
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("content_type") != _VARIANT_CONTENT_TYPE:
                return None
            self._touch(path)
            return MediaFile(
                path=path,
                content_type=_VARIANT_CONTENT_TYPE,
                size=path.stat().st_size,
                etag=key,
            )
        except (OSError, ValueError):
            return None

    @staticmethod
    def _render_variant(image: Image.Image, destination: Path, width: int) -> int | None:
        """Write a WebP variant to ``destination``; return its width if written."""
        if getattr(image, "is_animated", False):
            return None
        has_alpha = image.mode in {"RGBA", "LA", "PA"} or (
            image.mode == "P" and "transparency" in image.info
        )
        image = ImageOps.exif_transpose(image) or image
        # Never upscale: cap the target at the source width.  Re-encoding at the
        # source size still helps because WebP q82 is smaller than JPEG/PNG.
        target_width = min(width, image.width)
        height = max(1, round(image.height * target_width / image.width))
        converted = image.convert("RGBA" if has_alpha else "RGB")
        resized = converted.resize((target_width, height), Image.Resampling.LANCZOS)
        # A unique temp name keeps simultaneous workers from truncating each
        # other's file before the atomic os.replace.
        temp_path = destination.with_name(f"{destination.name}.{uuid.uuid4().hex}.tmp")
        try:
            # Pillow does not copy EXIF/ICC metadata unless explicitly asked, so
            # the variant is stripped by construction.
            resized.save(temp_path, format="WEBP", quality=_WEBP_QUALITY, method=_WEBP_METHOD)
            os.replace(temp_path, destination)
        finally:
            temp_path.unlink(missing_ok=True)
        return target_width

    def _render_variant_path(self, source: Path, destination: Path, width: int) -> int | None:
        with Image.open(source) as image:
            return self._render_variant(image, destination, width)

    def _render_variant_bytes(self, data: bytes, destination: Path, width: int) -> int | None:
        with Image.open(io.BytesIO(data)) as image:
            return self._render_variant(image, destination, width)

    def _write_variant_meta(
        self, meta_path: Path, *, url: str, filename: str, width: int, size: int
    ) -> None:
        meta = {
            "content_type": _VARIANT_CONTENT_TYPE,
            "url": url,
            "filename": filename,
            "width": width,
            "size": size,
        }
        temp_meta = meta_path.with_name(f"{meta_path.name}.{uuid.uuid4().hex}.tmp")
        temp_meta.write_text(json.dumps(meta), encoding="utf-8")
        os.replace(temp_meta, meta_path)
        self._invalidate_stats()

    async def _variant(self, original: MediaFile, url: str, width: int) -> MediaFile:
        if original.content_type not in _VARIANT_SOURCE_TYPES:
            return original
        _, _, digest = self._base(url)
        path, meta_path, key = self._variant_paths(digest, width)
        cached = self._variant_from_disk(path, meta_path, key)
        if cached is not None:
            return cached
        lock = await self._lock_for(key)
        async with lock:
            cached = self._variant_from_disk(path, meta_path, key)
            if cached is not None:
                return cached
            try:
                created = await asyncio.to_thread(
                    self._render_variant_path, original.path, path, width
                )
            except Exception:
                logger.warning(
                    "could not build image variant; serving original",
                    exc_info=True,
                    extra={"url": url, "width": width},
                )
                return original
            if created is None:
                return original
            size = path.stat().st_size
            self._write_variant_meta(
                meta_path, url=url, filename=path.name, width=created, size=size
            )
            return MediaFile(
                path=path, content_type=_VARIANT_CONTENT_TYPE, size=size, etag=key
            )

    async def variant_from_bytes(
        self, data: bytes, content_type: str, width: int | None
    ) -> MediaFile | None:
        """Create a cached variant for bytes that are not addressed by URL.

        Used by the archive page endpoint.  Returns ``None`` when the original
        bytes should be served instead (unsupported type or a decode failure).
        """
        normalized = resolve_width(width)
        if (
            normalized is None
            or content_type.split(";")[0].strip().lower() not in _VARIANT_SOURCE_TYPES
            or len(data) > _MAX_BYTES
        ):
            return None
        key_digest = hashlib.sha256(data).hexdigest()
        path, meta_path, key = self._variant_paths(key_digest, normalized)
        cached = self._variant_from_disk(path, meta_path, key)
        if cached is not None:
            return cached
        lock = await self._lock_for(key)
        async with lock:
            cached = self._variant_from_disk(path, meta_path, key)
            if cached is not None:
                return cached
            try:
                created = await asyncio.to_thread(
                    self._render_variant_bytes, data, path, normalized
                )
            except Exception:
                logger.warning(
                    "could not build archived image variant; serving original",
                    exc_info=True,
                    extra={"width": normalized},
                )
                return None
            if created is None:
                return None
            size = path.stat().st_size
            self._write_variant_meta(
                meta_path,
                url="",
                filename=path.name,
                width=created,
                size=size,
            )
            return MediaFile(
                path=path, content_type=_VARIANT_CONTENT_TYPE, size=size, etag=key
            )

    async def _lock_for(self, key: str) -> asyncio.Lock:
        async with self._locks_guard:
            return self._locks.setdefault(key, asyncio.Lock())

    async def get(
        self, url: str, referer: str | None = None, width: int | None = None
    ) -> MediaFile:
        original = await self._get_original(url, referer)
        normalized = resolve_width(width)
        if normalized is None:
            return original
        return await self._variant(original, url, normalized)

    async def _get_original(self, url: str, referer: str | None) -> MediaFile:
        if referer is None:
            host = (urlparse(url).hostname or "").lower()
            if host.endswith("cdnlibs.org") or host.endswith("imglib.info"):
                referer = "https://mangalib.me/"
            elif host.endswith("remanga.org") or host.endswith("reimg2.org"):
                referer = "https://remanga.org/"
        base, meta_path, digest = self._base(url)
        cached = self._from_disk(base, meta_path, digest)
        if cached and cached.content_type in _ALLOWED_TYPES:
            return cached
        lock = await self._lock_for(digest)
        async with lock:
            cached = self._from_disk(base, meta_path, digest)
            if cached and cached.content_type in _ALLOWED_TYPES:
                return cached
            headers: dict[str, str] = {"Accept": "image/avif,image/webp,image/png,image/jpeg,*/*"}
            if referer:
                headers["Referer"] = referer
            current = url
            response = None
            for _ in range(_MAX_REDIRECTS + 1):
                await self._validate_url(current)
                response = await request_with_retry(
                    self.client,
                    "GET",
                    current,
                    settings=self.settings,
                    limiter=self.limiter,
                    headers=headers,
                )
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("Location")
                    if not location:
                        raise UpstreamError("Image redirect without Location")
                    current = urljoin(current, location)
                    continue
                break
            else:
                raise UpstreamError("Too many image redirects")
            if response is None:
                raise UpstreamError("Image request failed")
            content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
            if content_type not in _ALLOWED_TYPES:
                raise UpstreamError(
                    "Upstream returned an unsupported image type",
                    details={"content_type": content_type or "missing"},
                )
            content = response.content
            if len(content) > _MAX_BYTES:
                raise UpstreamError("Image is too large")
            extension = _EXTENSIONS.get(content_type) or mimetypes.guess_extension(content_type) or ".img"
            final_path = base.with_suffix(extension)
            temp_path = final_path.with_suffix(final_path.suffix + ".tmp")
            temp_path.write_bytes(content)
            os.replace(temp_path, final_path)
            meta = {
                "content_type": content_type,
                "url": url,
                "filename": final_path.name,
                "size": len(content),
            }
            meta_path.write_text(json.dumps(meta), encoding="utf-8")
            self._invalidate_stats()
            return MediaFile(
                path=final_path, content_type=content_type, size=len(content), etag=digest
            )

    async def download_to(
        self, url: str, destination: Path, *, referer: str | None = None
    ) -> MediaFile:
        media = await self.get(url, referer=referer)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists() or destination.stat().st_size != media.size:
            temp = destination.with_suffix(destination.suffix + ".tmp")
            temp.write_bytes(media.path.read_bytes())
            os.replace(temp, destination)
        return MediaFile(
            path=destination, content_type=media.content_type, size=media.size, etag=media.etag
        )

    async def stats(self) -> MediaCacheStats:
        """Return on-disk image cache usage and eviction counters.

        The directory may contain hundreds of thousands of files, so the scan
        is cached for a few seconds and runs in a worker thread.  It never
        touches archive files or catalogue metadata.
        """

        now = time.monotonic()
        cached = self._stats_cache
        if cached is not None and now - self._stats_cached_at < _STATS_TTL_SECONDS:
            return MediaCacheStats(
                used_bytes=cached.used_bytes,
                cap_bytes=self.max_bytes,
                files=cached.files,
                evictions=self._evictions,
                last_pruned_at=self._last_pruned_at,
            )
        used_bytes, files = await asyncio.to_thread(self._scan_usage)
        result = MediaCacheStats(
            used_bytes=used_bytes,
            cap_bytes=self.max_bytes,
            files=files,
            evictions=self._evictions,
            last_pruned_at=self._last_pruned_at,
        )
        self._stats_cache = result
        self._stats_cached_at = now
        return result

    def _scan_usage(self) -> tuple[int, int]:
        entries = self._scan_entries()
        return sum(entry.size for entry in entries), len(entries)

    def _scan_entries(self) -> list[_CacheEntry]:
        entries: list[_CacheEntry] = []
        for root, dirs, names in os.walk(self.root):
            # Temporary downloads are never valid eviction candidates.
            dirs[:] = [name for name in dirs if name != ".tmp"]
            root_path = Path(root)
            for name in names:
                if not (_ORIGINAL_NAME.match(name) or _VARIANT_NAME.match(name)):
                    continue
                path = root_path / name
                try:
                    stat = path.stat()
                except OSError:
                    continue
                meta_path: Path | None = path.with_name(f"{name}{_SIDECAR_SUFFIX}")
                size = stat.st_size
                try:
                    size += meta_path.stat().st_size
                except OSError:
                    meta_path = None
                entries.append(
                    _CacheEntry(
                        path=path,
                        meta_path=meta_path,
                        size=size,
                        mtime=stat.st_mtime,
                    )
                )
        return entries

    async def prune(self, *, dry_run: bool = False) -> CachePruneResult:
        """Evict least-recently-used image entries until the cap is met.

        Only files created by :class:`MediaCache` are considered.  SQLite
        archives, catalogue metadata and exports are never opened or removed.
        """

        if self.max_bytes <= 0:
            stats = await self.stats()
            return CachePruneResult(
                removed=0,
                freed_bytes=0,
                used_bytes=stats.used_bytes,
                cap_bytes=0,
                dry_run=dry_run,
            )
        async with self._prune_guard:
            result = await asyncio.to_thread(self._prune_sync, dry_run)
        if not dry_run:
            if result.removed:
                self._evictions += result.removed
                logger.info(
                    "media image cache LRU evicted %s file(s), %s bytes; cap=%s bytes",
                    result.removed,
                    result.freed_bytes,
                    self.max_bytes,
                )
            self._last_pruned_at = datetime.now(UTC)
            self._invalidate_stats()
        self._log_usage(result.used_bytes)
        return result

    def _prune_sync(self, dry_run: bool) -> CachePruneResult:
        entries = self._scan_entries()
        used_bytes = sum(entry.size for entry in entries)
        if used_bytes <= self.max_bytes:
            return CachePruneResult(
                removed=0,
                freed_bytes=0,
                used_bytes=used_bytes,
                cap_bytes=self.max_bytes,
                dry_run=dry_run,
            )
        now = time.time()
        removed = 0
        freed_bytes = 0
        for entry in sorted(entries, key=lambda item: (item.mtime, str(item.path))):
            if used_bytes <= self.max_bytes:
                break
            if (
                self.prune_min_age_seconds
                and now - entry.mtime < self.prune_min_age_seconds
            ):
                # Entries are ordered oldest-first, so everything after this is
                # even newer and must be kept for the current request cycle.
                break
            if dry_run:
                used_bytes -= entry.size
                removed += 1
                freed_bytes += entry.size
                continue
            if self._unlink_entry(entry):
                used_bytes -= entry.size
                removed += 1
                freed_bytes += entry.size
        return CachePruneResult(
            removed=removed,
            freed_bytes=freed_bytes,
            used_bytes=max(0, used_bytes),
            cap_bytes=self.max_bytes,
            dry_run=dry_run,
        )

    @staticmethod
    def _unlink_entry(entry: _CacheEntry) -> bool:
        try:
            entry.path.unlink(missing_ok=True)
        except OSError:
            logger.warning(
                "could not evict image cache file; will retry next cycle",
                extra={"path": str(entry.path)},
            )
            return False
        if entry.meta_path is not None:
            try:
                entry.meta_path.unlink(missing_ok=True)
            except OSError:
                logger.warning(
                    "could not evict image cache sidecar",
                    extra={"path": str(entry.meta_path)},
                )
        return True

    def _log_usage(self, used_bytes: int) -> None:
        level = usage_level(used_bytes, self.max_bytes)
        if level == "critical":
            logger.error(
                "media image cache is above 90%% of its cap: %s/%s bytes",
                used_bytes,
                self.max_bytes,
            )
        elif level == "warning":
            logger.warning(
                "media image cache is above 80%% of its cap: %s/%s bytes",
                used_bytes,
                self.max_bytes,
            )

    def start_periodic_prune(
        self, interval_seconds: float | None = None
    ) -> asyncio.Task[None] | None:
        """Start the hourly LRU sweep; returns ``None`` for an unbounded cache."""

        if self.max_bytes <= 0:
            return None
        interval = (
            self.prune_interval_seconds
            if interval_seconds is None
            else float(interval_seconds)
        )
        if interval <= 0:
            return None
        if self._prune_task is not None and not self._prune_task.done():
            return self._prune_task
        self._prune_task = asyncio.create_task(
            self._prune_loop(interval), name="media-cache-prune"
        )
        return self._prune_task

    async def _prune_loop(self, interval: float) -> None:
        while True:
            await asyncio.sleep(interval)
            try:
                await self.prune()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("periodic media cache prune failed")

    async def close(self) -> None:
        task = self._prune_task
        self._prune_task = None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await self.client.aclose()
