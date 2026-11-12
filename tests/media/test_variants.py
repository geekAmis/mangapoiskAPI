from __future__ import annotations

import asyncio
import io
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from manga_common.config import Settings, get_settings
from PIL import Image
from services.media.app import cache as cache_module
from services.media.app.api import router
from services.media.app.cache import MediaCache, MediaFile, resolve_width

ORIGINAL_WIDTH = 1438
ORIGINAL_HEIGHT = 2100


def _jpeg_bytes() -> bytes:
    # Noise is a worst case for both JPEG and WebP, so the smaller variant
    # assertion is meaningful rather than an artifact of a flat colour.
    image = Image.effect_noise((ORIGINAL_WIDTH, ORIGINAL_HEIGHT), 48).convert("RGB")
    exif = Image.Exif()
    exif[0x010E] = "variant-secret"
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=92, exif=exif)
    return buffer.getvalue()


class _FakeResponse:
    def __init__(self, content: bytes, content_type: str) -> None:
        self.status_code = 200
        self.headers = {"Content-Type": content_type}
        self.content = content


def _mock_download(
    monkeypatch: pytest.MonkeyPatch, content: bytes, content_type: str
) -> Callable[[], int]:
    calls = 0

    async def fake_request(*args: object, **kwargs: object) -> _FakeResponse:
        nonlocal calls
        calls += 1
        return _FakeResponse(content, content_type)

    async def fake_validate(self: MediaCache, url: str) -> None:
        return None

    monkeypatch.setattr(cache_module, "request_with_retry", fake_request)
    monkeypatch.setattr(MediaCache, "_validate_url", fake_validate)
    return lambda: calls


def _cache(tmp_path: Path) -> MediaCache:
    return MediaCache(Settings(media_cache_dir=str(tmp_path / "media-cache")))


@pytest.mark.asyncio
async def test_width_creates_cached_smaller_webp_variant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    jpeg = _jpeg_bytes()
    downloads = _mock_download(monkeypatch, jpeg, "image/jpeg")
    cache = _cache(tmp_path)
    url = "https://example.com/chapter/page-01.jpg"
    try:
        original = await cache.get(url)
        assert downloads() == 1
        assert original.content_type == "image/jpeg"
        assert original.size == len(jpeg)

        renders = 0
        render_path = cache._render_variant_path

        def counting_render(source: Path, destination: Path, width: int) -> int | None:
            nonlocal renders
            renders += 1
            return render_path(source, destination, width)

        monkeypatch.setattr(cache, "_render_variant_path", counting_render)

        variant = await cache.get(url, width=720)
        assert downloads() == 1  # the original came from the cache
        assert renders == 1
        assert variant.content_type == "image/webp"
        assert variant.path != original.path
        assert variant.path.suffix == ".webp"
        assert variant.size < original.size
        assert variant.etag != original.etag
        with Image.open(variant.path) as image:
            assert image.format == "WEBP"
            assert image.width == 720
            assert image.height == round(ORIGINAL_HEIGHT * 720 / ORIGINAL_WIDTH)
            assert not image.getexif()

        cached = await cache.get(url, width=720)
        assert downloads() == 1
        assert renders == 1
        assert cached.path == variant.path
        assert cached.etag == variant.etag
        assert cached.size == variant.size
    finally:
        await cache.close()


@pytest.mark.asyncio
async def test_small_image_is_not_upscaled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = Image.effect_noise((600, 800), 48).convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=92)
    jpeg = buffer.getvalue()
    _mock_download(monkeypatch, jpeg, "image/jpeg")
    cache = _cache(tmp_path)
    try:
        media = await cache.get("https://example.com/small.jpg", width=720)
        assert media.content_type == "image/webp"
        with Image.open(media.path) as variant:
            assert variant.width == 600
            assert variant.height == 800
    finally:
        await cache.close()


@pytest.mark.asyncio
async def test_width_none_returns_original_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    jpeg = _jpeg_bytes()
    _mock_download(monkeypatch, jpeg, "image/jpeg")
    cache = _cache(tmp_path)
    try:
        media = await cache.get("https://example.com/page.jpg", width=None)
        assert media.content_type == "image/jpeg"
        assert media.size == len(jpeg)
        assert media.path.read_bytes() == jpeg
        assert not list(cache.root.rglob("*-w*.webp"))
    finally:
        await cache.close()


@pytest.mark.asyncio
async def test_concurrent_variant_requests_share_cached_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    jpeg = _jpeg_bytes()
    downloads = _mock_download(monkeypatch, jpeg, "image/jpeg")
    cache = _cache(tmp_path)
    url = "https://example.com/concurrent.jpg"
    try:
        results = await asyncio.gather(*(cache.get(url, width=720) for _ in range(6)))
        assert downloads() == 1
        assert len({item.path for item in results}) == 1
        assert len({item.size for item in results}) == 1
        assert len({item.etag for item in results}) == 1
        with Image.open(results[0].path) as image:
            assert image.format == "WEBP"
            assert image.width == 720
        assert not list(cache.root.rglob("*.tmp"))
    finally:
        await cache.close()


@pytest.mark.asyncio
async def test_gif_falls_back_to_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    buffer = io.BytesIO()
    Image.new("P", (ORIGINAL_WIDTH, ORIGINAL_HEIGHT)).save(buffer, format="GIF")
    gif = buffer.getvalue()
    _mock_download(monkeypatch, gif, "image/gif")
    cache = _cache(tmp_path)
    try:
        media = await cache.get("https://example.com/animated.gif", width=720)
        assert media.content_type == "image/gif"
        assert media.size == len(gif)
        assert media.path.read_bytes() == gif
        assert not list(cache.root.rglob("*-w*.webp"))
    finally:
        await cache.close()


@pytest.mark.asyncio
async def test_undecodable_image_falls_back_to_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"this is not a real jpeg" * 1000
    _mock_download(monkeypatch, payload, "image/jpeg")
    cache = _cache(tmp_path)
    try:
        media = await cache.get("https://example.com/broken.jpg", width=720)
        assert media.content_type == "image/jpeg"
        assert media.size == len(payload)
        assert media.path.read_bytes() == payload
        assert not list(cache.root.rglob("*-w*.webp"))
    finally:
        await cache.close()


@pytest.mark.asyncio
async def test_archive_bytes_variant_is_cached(tmp_path: Path) -> None:
    jpeg = _jpeg_bytes()
    cache = _cache(tmp_path)
    try:
        variant = await cache.variant_from_bytes(jpeg, "image/jpeg", 720)
        assert variant is not None
        assert variant.content_type == "image/webp"
        assert variant.path.exists()
        with Image.open(variant.path) as image:
            assert image.width == 720

        again = await cache.variant_from_bytes(jpeg, "image/jpeg", 720)
        assert again is not None
        assert again.path == variant.path
        assert again.etag == variant.etag
    finally:
        await cache.close()


def test_resolve_width_clamps_to_supported_values() -> None:
    assert resolve_width(None) is None
    assert resolve_width(0) is None
    assert resolve_width(320) == 480
    assert resolve_width(500) == 480
    assert resolve_width(720) == 720
    assert resolve_width(1000) == 1080
    assert resolve_width(1280) == 1280
    assert resolve_width(1600) == 1600


class _RecordingCache:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.widths: list[int | None] = []

    async def get(
        self, url: str, referer: str | None = None, width: int | None = None
    ) -> MediaFile:
        self.widths.append(width)
        return MediaFile(
            path=self.path,
            content_type="image/webp",
            size=self.path.stat().st_size,
            etag="variant-etag",
        )


def _client(cache: object) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.state.cache = cache
    app.dependency_overrides[get_settings] = lambda: Settings(internal_token="test-token")
    return TestClient(app)


def test_internal_image_rejects_width_outside_schema(tmp_path: Path) -> None:
    client = _client(_RecordingCache(tmp_path / "unused.webp"))
    headers = {"X-Internal-Token": "test-token"}
    for width in (100, 319, 1601, 5000):
        response = client.get(
            "/internal/image",
            params={"url": "https://example.com/page.jpg", "w": width},
            headers=headers,
        )
        assert response.status_code == 422, (width, response.text)


def test_internal_image_passes_clamped_width(tmp_path: Path) -> None:
    path = tmp_path / "page.webp"
    Image.new("RGB", (10, 10)).save(path, format="WEBP")
    cache = _RecordingCache(path)
    client = _client(cache)

    response = client.get(
        "/internal/image",
        params={"url": "https://example.com/page.jpg", "w": 500},
        headers={"X-Internal-Token": "test-token"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/webp"
    assert cache.widths == [480]


def test_internal_image_without_width_keeps_original_behaviour(tmp_path: Path) -> None:
    path = tmp_path / "page.webp"
    Image.new("RGB", (10, 10)).save(path, format="WEBP")
    cache = _RecordingCache(path)
    client = _client(cache)

    response = client.get(
        "/internal/image",
        params={"url": "https://example.com/page.jpg"},
        headers={"X-Internal-Token": "test-token"},
    )

    assert response.status_code == 200
    assert cache.widths == [None]
