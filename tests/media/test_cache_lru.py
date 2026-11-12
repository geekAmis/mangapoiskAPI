from __future__ import annotations

import asyncio
import hashlib
import os
import time
from pathlib import Path

import pytest
from services.media.app.cache import MediaCache, usage_level
from services.media.app.config import MediaSettings


def _cache(
    tmp_path: Path,
    *,
    cap: int,
    min_age: int = 0,
    interval: int = 3600,
) -> MediaCache:
    return MediaCache(
        MediaSettings(
            media_cache_dir=str(tmp_path / "media-cache"),
            media_cache_max_bytes=cap,
            media_cache_prune_min_age_seconds=min_age,
            media_cache_prune_interval_seconds=interval,
        )
    )


def _entry(
    cache: MediaCache,
    label: str,
    *,
    size: int = 100,
    mtime: float,
) -> tuple[Path, Path]:
    digest = hashlib.sha256(label.encode()).hexdigest()
    shard = cache.root / digest[:2]
    shard.mkdir(parents=True, exist_ok=True)
    path = shard / f"{digest}.jpg"
    path.write_bytes(b"x" * size)
    meta = path.with_name(f"{path.name}.json")
    meta.write_text('{"content_type": "image/jpeg"}', encoding="utf-8")
    os.utime(path, (mtime, mtime))
    os.utime(meta, (mtime, mtime))
    return path, meta


@pytest.mark.asyncio
async def test_image_cache_evicts_oldest_and_enforces_cap(tmp_path: Path) -> None:
    # Each entry is 100 image bytes + a 30-byte JSON sidecar.
    cache = _cache(tmp_path, cap=350)
    oldest, oldest_meta = _entry(cache, "oldest", size=100, mtime=1_000)
    middle, middle_meta = _entry(cache, "middle", size=100, mtime=2_000)
    newest, newest_meta = _entry(cache, "newest", size=100, mtime=3_000)
    try:
        result = await cache.prune()

        assert result.removed == 1
        assert result.freed_bytes == 130
        assert result.used_bytes <= cache.max_bytes
        assert not oldest.exists()
        assert not oldest_meta.exists()
        assert middle.exists() and middle_meta.exists()
        assert newest.exists() and newest_meta.exists()

        stats = await cache.stats()
        assert stats.files == 2
        assert stats.used_bytes == 260
        assert stats.evictions == 1
        assert stats.last_pruned_at is not None
        assert stats.level == "ok"
    finally:
        await cache.close()


@pytest.mark.asyncio
async def test_image_cache_dry_run_reports_without_deleting(tmp_path: Path) -> None:
    cache = _cache(tmp_path, cap=50)
    first, first_meta = _entry(cache, "first", size=100, mtime=1_000)
    second, second_meta = _entry(cache, "second", size=100, mtime=2_000)
    try:
        result = await cache.prune(dry_run=True)

        assert result.dry_run is True
        assert result.removed == 2
        assert first.exists() and second.exists()
        assert first_meta.exists() and second_meta.exists()
        stats = await cache.stats()
        assert stats.evictions == 0
        assert stats.last_pruned_at is None

        actual = await cache.prune()
        assert actual.removed == 2
        assert not first.exists() and not second.exists()
    finally:
        await cache.close()


@pytest.mark.asyncio
async def test_image_cache_never_deletes_metadata_or_archives(tmp_path: Path) -> None:
    cache = _cache(tmp_path, cap=50)
    image, meta = _entry(cache, "image", size=100, mtime=1_000)

    unrelated = {
        "catalogue.json": cache.root / "catalogue.json",
        "archive.zip": cache.root / "chapter-archives" / "chapter.zip",
        "cover.jpg": cache.root / "cover.jpg",
    }
    for path in unrelated.values():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"keep me")
    arbitrary_json = cache.root / "random-metadata.json"
    arbitrary_json.write_text('{"title": "keep"}', encoding="utf-8")

    import sqlite3

    archives_db = cache.root / "archives.db"
    with sqlite3.connect(archives_db) as connection:
        connection.execute("CREATE TABLE chapter_archives (chapter_id TEXT PRIMARY KEY)")
        connection.execute("INSERT INTO chapter_archives VALUES ('keep-me')")

    try:
        result = await cache.prune()

        assert result.removed == 1
        assert not image.exists() and not meta.exists()
        for path in unrelated.values():
            assert path.exists(), path
        assert arbitrary_json.exists()

        # The eviction must not corrupt archive metadata even when it lives
        # under the same parent directory.
        with sqlite3.connect(archives_db) as connection:
            assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            kept = connection.execute(
                "SELECT chapter_id FROM chapter_archives"
            ).fetchone()
        assert kept == ("keep-me",)
    finally:
        await cache.close()


@pytest.mark.asyncio
async def test_image_cache_periodic_prune_runs_without_new_writes(
    tmp_path: Path,
) -> None:
    cache = _cache(tmp_path, cap=130, interval=3600)
    old, old_meta = _entry(cache, "periodic-old", size=100, mtime=1_000)
    fresh, fresh_meta = _entry(cache, "periodic-new", size=100, mtime=2_000)
    try:
        task = cache.start_periodic_prune(interval_seconds=0.02)
        assert task is not None
        for _ in range(100):
            if not old.exists():
                break
            await asyncio.sleep(0.02)

        assert not old.exists() and not old_meta.exists()
        assert fresh.exists() and fresh_meta.exists()
        stats = await cache.stats()
        assert stats.evictions >= 1
    finally:
        await cache.close()


@pytest.mark.asyncio
async def test_image_cache_unbounded_mode_never_prunes(tmp_path: Path) -> None:
    cache = _cache(tmp_path, cap=0)
    image, meta = _entry(cache, "unbounded", size=100, mtime=1_000)
    try:
        assert cache.start_periodic_prune() is None
        result = await cache.prune()
        assert result.removed == 0
        assert image.exists() and meta.exists()
    finally:
        await cache.close()


@pytest.mark.asyncio
async def test_image_cache_min_age_keeps_current_files(tmp_path: Path) -> None:
    cache = _cache(tmp_path, cap=50, min_age=3600)
    image, meta = _entry(cache, "hot", size=100, mtime=time.time())
    try:
        result = await cache.prune()
        assert result.removed == 0
        assert image.exists() and meta.exists()
    finally:
        await cache.close()


def test_usage_level_thresholds() -> None:
    assert usage_level(79, 100) == "ok"
    assert usage_level(80, 100) == "warning"
    assert usage_level(89, 100) == "warning"
    assert usage_level(90, 100) == "critical"
    assert usage_level(10, 0) == "unbounded"
