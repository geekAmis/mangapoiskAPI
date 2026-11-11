from __future__ import annotations

import asyncio
import hashlib
import json
import mimetypes
import os
from dataclasses import dataclass
from pathlib import Path

from manga_common.config import Settings
from manga_common.errors import UpstreamError
from manga_common.http import AsyncRateLimiter, build_client, request_with_retry

_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/avif": ".avif",
}

_MAX_BYTES = 40 * 1024 * 1024


@dataclass(slots=True)
class MediaFile:
    path: Path
    content_type: str
    size: int
    etag: str


class MediaCache:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.root = Path(settings.media_cache_dir).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.client = build_client(settings)
        self.limiter = AsyncRateLimiter(max(30, settings.scraper_requests_per_minute * 2), burst=10)
        self._locks: dict[str, asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()
        self._allowed_hosts = {
            host.strip().lower()
            for host in (os.getenv("MEDIA_ALLOWED_HOSTS") or "").split(",")
            if host.strip()
        }

    def _validate_url(self, url: str) -> None:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise UpstreamError("Invalid image URL")
        host = parsed.hostname.lower()
        if host in {"localhost", "127.0.0.1", "0.0.0.0", "::1"} or host.endswith(".local"):
            raise UpstreamError("Private image host is not allowed")
        if self._allowed_hosts and host not in self._allowed_hosts and not any(
            host.endswith(f".{allowed}") for allowed in self._allowed_hosts
        ):
            raise UpstreamError("Image host is not in MEDIA_ALLOWED_HOSTS")

    def _base(self, url: str) -> tuple[Path, Path, str]:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        shard = self.root / digest[:2]
        shard.mkdir(parents=True, exist_ok=True)
        return shard / digest, shard / f"{digest}.json", digest

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

    async def _lock_for(self, key: str) -> asyncio.Lock:
        async with self._locks_guard:
            return self._locks.setdefault(key, asyncio.Lock())

    async def get(self, url: str, *, referer: str | None = None) -> MediaFile:
        self._validate_url(url)
        if referer is None:
            from urllib.parse import urlparse

            host = (urlparse(url).hostname or "").lower()
            if host.endswith("cdnlibs.org") or host.endswith("imglib.info"):
                referer = "https://mangalib.me/"
        base, meta_path, digest = self._base(url)
        cached = self._from_disk(base, meta_path, digest)
        if cached:
            return cached
        lock = await self._lock_for(digest)
        async with lock:
            cached = self._from_disk(base, meta_path, digest)
            if cached:
                return cached
            headers: dict[str, str] = {"Accept": "image/avif,image/webp,image/png,image/jpeg,*/*"}
            if referer:
                headers["Referer"] = referer
            response = await request_with_retry(
                self.client,
                "GET",
                url,
                settings=self.settings,
                limiter=self.limiter,
                headers=headers,
            )
            content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
            if content_type and not content_type.startswith("image/"):
                raise UpstreamError(
                    "Upstream did not return an image", details={"content_type": content_type}
                )
            content = response.content
            if len(content) > _MAX_BYTES:
                raise UpstreamError("Image is too large")
            extension = (
                _EXTENSIONS.get(content_type)
                or mimetypes.guess_extension(content_type)
                or ".img"
            )
            final_path = base.with_suffix(extension)
            temp_path = final_path.with_suffix(final_path.suffix + ".tmp")
            temp_path.write_bytes(content)
            os.replace(temp_path, final_path)
            meta = {
                "content_type": content_type or "application/octet-stream",
                "url": url,
                "filename": final_path.name,
                "size": len(content),
            }
            meta_path.write_text(json.dumps(meta), encoding="utf-8")
            return MediaFile(
                path=final_path, content_type=meta["content_type"], size=len(content), etag=digest
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

    async def close(self) -> None:
        await self.client.aclose()
