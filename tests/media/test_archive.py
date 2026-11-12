from __future__ import annotations

import asyncio
import json
import sqlite3
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
from PIL import Image
from services.media.app.archive import ArchiveManager, ArchivePage, ArchiveRequest
from services.media.app.cache import MediaFile


class FakeCache:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.files: dict[str, Path] = {}
        self.calls: list[str] = []
        for index, color in enumerate([(30, 40, 60), (90, 30, 40), (200, 180, 40)], start=1):
            path = self.root / f"{index}.jpg"
            Image.new("RGB", (120, 180), color).save(path, "JPEG")
            self.files[f"https://example.com/{index}.jpg"] = path

    async def get(self, url: str, *, referer: str | None = None) -> MediaFile:
        self.calls.append(url)
        path = self.files[url]
        return MediaFile(path=path, content_type="image/jpeg", size=path.stat().st_size, etag="x")


def _pages() -> list[ArchivePage]:
    # Intentionally unsorted to prove the worker orders pages by number.
    return [
        ArchivePage(number=3, url="https://example.com/3.jpg", width=120, height=180),
        ArchivePage(number=1, url="https://example.com/1.jpg", width=120, height=180),
        ArchivePage(number=2, url="https://example.com/2.jpg", width=120, height=180),
    ]


async def _wait(manager: ArchiveManager, chapter_id: uuid.UUID):  # type: ignore[no-untyped-def]
    for _ in range(200):
        state = await manager.metadata(chapter_id)
        if state is not None and state.status in {"done", "failed"}:
            return state
        await asyncio.sleep(0.05)
    raise AssertionError("archive did not finish")


@pytest.mark.asyncio
async def test_small_chapter_uses_db_blobs(tmp_path: Path) -> None:
    cache = FakeCache(tmp_path / "cache")
    manager = ArchiveManager(
        cache,
        db_path=tmp_path / "archives.db",
        archive_dir=tmp_path / "chapter-archives",
        threshold_bytes=1024 * 1024,
    )
    chapter_id = uuid.uuid4()
    request = ArchiveRequest(
        chapter_id=chapter_id,
        source="test-source",
        translator="test-team",
        pages=_pages(),
    )
    try:
        queued, created = await manager.create(request)
        assert created is True
        assert queued.status in {"queued", "running"}

        state = await _wait(manager, chapter_id)
        assert state is not None
        assert state.status == "done", state.error
        assert state.mode == "db"
        assert state.page_count == 3
        assert state.total_bytes == sum(path.stat().st_size for path in cache.files.values())
        assert state.sha256 is None
        assert state.translator == "test-team"

        page = await manager.page(chapter_id, 2)
        assert page is not None
        assert page.content_type == "image/jpeg"
        assert page.data == cache.files["https://example.com/2.jpg"].read_bytes()
        assert await manager.page(chapter_id, 99) is None

        assert await manager.delete(chapter_id) is True
        assert await manager.metadata(chapter_id) is None
        assert await manager.page(chapter_id, 1) is None
        assert await manager.delete(chapter_id) is False
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_large_chapter_uses_zip(tmp_path: Path) -> None:
    cache = FakeCache(tmp_path / "cache")
    manager = ArchiveManager(
        cache,
        db_path=tmp_path / "archives.db",
        archive_dir=tmp_path / "chapter-archives",
        threshold_bytes=1,
    )
    chapter_id = uuid.uuid4()
    request = ArchiveRequest(
        chapter_id=chapter_id,
        source="test-source",
        translator=None,
        pages=_pages(),
    )
    try:
        await manager.create(request)
        state = await _wait(manager, chapter_id)
        assert state is not None
        assert state.status == "done", state.error
        assert state.mode == "zip"
        assert state.page_count == 3
        assert state.sha256 is not None and len(state.sha256) == 64
        assert state.archive_path is not None
        archive_path = Path(state.archive_path)
        assert archive_path.exists()
        assert archive_path.parent == (tmp_path / "chapter-archives").resolve()

        with zipfile.ZipFile(archive_path) as bundle:
            names = set(bundle.namelist())
            assert {"0001.jpg", "0002.jpg", "0003.jpg", "manifest.json"} <= names
            manifest = json.loads(bundle.read("manifest.json"))
        assert manifest["source"] == "test-source"
        assert manifest["translator"] is None
        assert manifest["page_count"] == 3
        assert manifest["pages"][0]["width"] == 120
        assert manifest["pages"][0]["height"] == 180

        page = await manager.page(chapter_id, 1)
        assert page is not None
        assert page.content_type == "image/jpeg"
        assert page.data == cache.files["https://example.com/1.jpg"].read_bytes()
        assert await manager.page(chapter_id, 4) is None

        assert await manager.delete(chapter_id) is True
        assert not archive_path.exists()
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_startup_recovers_unfinished_jobs(tmp_path: Path) -> None:
    cache = FakeCache(tmp_path / "cache")
    archive_dir = tmp_path / "chapter-archives"
    db_path = tmp_path / "archives.db"
    manager = ArchiveManager(
        cache,
        db_path=db_path,
        archive_dir=archive_dir,
        threshold_bytes=1024 * 1024,
    )
    chapter_id = uuid.uuid4()
    timestamp = datetime.now(UTC).isoformat()
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO chapter_archives (
                chapter_id, source, status, page_count, total_bytes,
                created_at, updated_at
            )
            VALUES (?, 'test-source', 'running', 3, 0, ?, ?)
            """,
            (str(chapter_id), timestamp, timestamp),
        )

    leftover = archive_dir / ".tmp" / "leftover"
    leftover.mkdir(parents=True)
    (leftover / "0001.jpg").write_bytes(b"partial")
    orphan = archive_dir / "orphan.zip.tmp"
    orphan.write_bytes(b"partial")

    try:
        await manager.startup()
        state = await manager.metadata(chapter_id)
        assert state is not None
        assert state.status == "failed"
        assert state.error
        assert not leftover.exists()
        assert not orphan.exists()
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_archive_summary_reports_mixed_states(tmp_path: Path) -> None:
    cache = FakeCache(tmp_path / "cache")
    manager = ArchiveManager(
        cache,
        db_path=tmp_path / "archives.db",
        archive_dir=tmp_path / "chapter-archives",
        threshold_bytes=1024 * 1024,
    )
    ready_id = uuid.uuid4()
    failed_id = uuid.uuid4()
    missing_id = uuid.uuid4()
    ready = ArchiveRequest(
        chapter_id=ready_id,
        source="test-source",
        pages=_pages(),
    )
    failing = ArchiveRequest(
        chapter_id=failed_id,
        source="test-source",
        pages=[ArchivePage(number=1, url="https://example.com/missing.jpg")],
    )
    try:
        await manager.create(ready)
        await _wait(manager, ready_id)
        await manager.create(failing)
        await _wait(manager, failed_id)

        items = await manager.summary([missing_id, ready_id, failed_id, ready_id])
        assert [item.chapter_id for item in items] == [missing_id, ready_id, failed_id]
        by_id = {item.chapter_id: item for item in items}
        assert by_id[missing_id].status == "missing"
        assert by_id[ready_id].status == "done"
        assert by_id[ready_id].page_count == 3
        assert by_id[failed_id].status == "error"
        assert by_id[failed_id].error
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_archive_is_idempotent(tmp_path: Path) -> None:
    cache = FakeCache(tmp_path / "cache")
    manager = ArchiveManager(
        cache,
        db_path=tmp_path / "archives.db",
        archive_dir=tmp_path / "chapter-archives",
        threshold_bytes=1024 * 1024,
    )
    chapter_id = uuid.uuid4()
    request = ArchiveRequest(
        chapter_id=chapter_id,
        source="test-source",
        pages=_pages(),
    )
    try:
        first, first_created = await manager.create(request)
        second, second_created = await manager.create(request)
        assert first_created is True
        assert second_created is False
        assert second.status in {"queued", "running"}

        state = await _wait(manager, chapter_id)
        assert state is not None
        assert state.status == "done"
        calls_after_done = list(cache.calls)
        assert sorted(calls_after_done) == sorted(cache.files)

        third, third_created = await manager.create(request)
        assert third_created is False
        assert third.status == "done"
        assert third.mode == state.mode
        assert third.page_count == state.page_count
        assert cache.calls == calls_after_done
        assert first.chapter_id == third.chapter_id
    finally:
        await manager.close()
