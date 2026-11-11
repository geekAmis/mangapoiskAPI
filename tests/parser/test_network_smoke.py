"""Opt-in live smoke test.

Run with::

    RUN_NETWORK_TESTS=1 pytest tests/parser/test_network_smoke.py -m network
"""

from __future__ import annotations

import os

import pytest
from manga_common.cache import MemoryCache
from manga_common.config import Settings
from manga_common.http import build_client
from services.parser.app.adapters.mangapoisk import MangaPoiskAdapter

pytestmark = [
    pytest.mark.network,
    pytest.mark.skipif(
        os.getenv("RUN_NETWORK_TESTS") != "1",
        reason="set RUN_NETWORK_TESTS=1 to hit the real MangaPoisk site",
    ),
]


async def test_mangapoisk_live_smoke() -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        service_name="parser-network-smoke",
        log_json=False,
        scraper_requests_per_minute=30,
        scraper_cache_ttl_seconds=60,
        scraper_max_retries=1,
        http_timeout_seconds=30.0,
    )
    client = build_client(settings)
    cache = MemoryCache()
    try:
        adapter = MangaPoiskAdapter(client, settings, cache)

        home = await adapter.latest()
        assert home.source == "mangapoisk"
        assert home.popular or home.latest

        search = await adapter.search("Overgeared")
        assert search.items
        item = search.items[0]
        assert item.source_id

        detail = await adapter.get_manga(item.source_id, chapters_limit=5)
        assert detail.title
        assert detail.source_id

        if detail.chapters:
            chapter = detail.chapters[0]
            assert chapter.url
            chapter_detail = await adapter.get_chapter(chapter.source_id, url=chapter.url)
            assert isinstance(chapter_detail.pages, list)
    finally:
        await client.aclose()
        await cache.close()
