"""Shared test configuration for the parser service.

The repository is intentionally not installed as a wheel in this workspace, so
put ``services/parser`` and ``packages/manga_common`` on ``sys.path`` before any
service imports.  In production both are installed by ``requirements.txt``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_DIR = Path(__file__).resolve().parent
for _path in (
    REPO_ROOT,
    REPO_ROOT / "packages" / "manga_common",
    TEST_DIR,
):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from manga_common.cache import MemoryCache
from manga_common.config import Settings
from manga_common.http import build_client


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        service_name="parser-test",
        log_json=False,
        log_level="WARNING",
        internal_token="test-internal-token",
        scraper_requests_per_minute=100_000,
        scraper_cache_ttl_seconds=60,
        scraper_max_retries=0,
        http_timeout_seconds=5.0,
    )


@pytest.fixture
def cache() -> MemoryCache:
    return MemoryCache()


@pytest.fixture
async def client(settings: Settings):
    http_client = build_client(settings)
    try:
        yield http_client
    finally:
        await http_client.aclose()
