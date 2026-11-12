from __future__ import annotations

import asyncio

import pytest
from manga_common.config import Settings
from manga_common.errors import UpstreamError
from services.media.app.cache import MediaCache


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/image.jpg",
        "http://10.0.0.7/image.jpg",
        "http://192.168.1.1/image.jpg",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/image.jpg",
        "http://[::ffff:127.0.0.1]/image.jpg",
        "http://localhost/image.jpg",
    ],
)
def test_private_image_hosts_are_rejected(tmp_path, url: str) -> None:
    cache = MediaCache(Settings(media_cache_dir=str(tmp_path), media_allowed_hosts=""))
    with pytest.raises(UpstreamError):
        asyncio.run(cache._validate_url(url))
