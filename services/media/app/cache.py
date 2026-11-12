from __future__ import annotations

import asyncio
import hashlib
import io
import ipaddress
import json
import logging
import mimetypes
import os
import socket
import time
import uuid
from dataclasses import dataclass
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
    bytes: int
    files: int


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
        self._stats_cache: MediaCacheStats | None = None
        self._stats_cached_at = 0.0

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
        """Return the on-disk image cache footprint.

        The directory can contain hundreds of thousands of files, so the scan is
        cached for a minute and runs in a worker thread.  It is read-only and
        never changes eviction behaviour.
        """

        now = time.monotonic()
        if self._stats_cache is not None and now - self._stats_cached_at < 60:
            return self._stats_cache
        result = await asyncio.to_thread(self._scan_stats)
        self._stats_cache = result
        self._stats_cached_at = now
        return result

    def _scan_stats(self) -> MediaCacheStats:
        total_bytes = 0
        files = 0
        for root, _dirs, names in os.walk(self.root):
            for name in names:
                try:
                    total_bytes += (Path(root) / name).stat().st_size
                    files += 1
                except OSError:
                    continue
        return MediaCacheStats(bytes=total_bytes, files=files)

    async def close(self) -> None:
        await self.client.aclose()
