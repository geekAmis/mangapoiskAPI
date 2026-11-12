from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import mimetypes
import os
import shutil
import sqlite3
import uuid
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from .cache import MediaCache, usage_level

logger = logging.getLogger(__name__)

DEFAULT_THRESHOLD_BYTES = 1024 * 1024

_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/avif": ".avif",
}
_CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".avif": "image/avif",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS chapter_archives (
    chapter_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    translator TEXT,
    status TEXT NOT NULL,
    mode TEXT,
    page_count INTEGER NOT NULL DEFAULT 0,
    total_bytes INTEGER NOT NULL DEFAULT 0,
    sha256 TEXT,
    archive_path TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_accessed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_chapter_archives_status
    ON chapter_archives (status);
CREATE TABLE IF NOT EXISTS page_blobs (
    chapter_id TEXT NOT NULL,
    number INTEGER NOT NULL,
    content_type TEXT NOT NULL,
    bytes BLOB NOT NULL,
    PRIMARY KEY (chapter_id, number)
);
"""


class ArchivePage(BaseModel):
    number: int = Field(ge=1)
    url: str = Field(min_length=1, max_length=4096)
    width: int | None = None
    height: int | None = None


class ArchiveRequest(BaseModel):
    chapter_id: uuid.UUID
    source: str = Field(min_length=1, max_length=64)
    translator: str | None = Field(default=None, max_length=256)
    pages: list[ArchivePage] = Field(min_length=1)


class ArchiveState(BaseModel):
    chapter_id: uuid.UUID
    source: str
    translator: str | None = None
    status: Literal["queued", "running", "done", "failed"]
    mode: Literal["db", "zip"] | None = None
    page_count: int = 0
    total_bytes: int = 0
    sha256: str | None = None
    archive_path: str | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class ArchiveSummaryItem(BaseModel):
    """Compact per-chapter state for the gateway download pipeline."""

    chapter_id: uuid.UUID
    status: Literal["done", "pending", "error", "missing"]
    page_count: int = 0
    total_bytes: int = 0
    error: str | None = None


class ArchiveSummary(BaseModel):
    items: list[ArchiveSummaryItem]


@dataclass(slots=True)
class ArchiveStats:
    total: int
    done: int
    failed: int
    pending: int
    done_bytes: int
    db_bytes: int
    evictions: int
    last_pruned_at: datetime | None


@dataclass(slots=True)
class ArchivePruneResult:
    removed: int
    freed_bytes: int
    used_bytes: int
    cap_bytes: int
    dry_run: bool


@dataclass(slots=True)
class ArchivedPage:
    data: bytes
    content_type: str


@dataclass(slots=True)
class _Entry:
    page: ArchivePage
    path: Path
    content_type: str
    size: int


def _now() -> datetime:
    return datetime.now(UTC)


def _normalize_pages(pages: list[ArchivePage]) -> list[ArchivePage]:
    # A chapter may occasionally repeat a page number.  Keep the last copy so
    # the archive filenames and page count stay consistent.
    unique: dict[int, ArchivePage] = {}
    for page in sorted(pages, key=lambda item: item.number):
        unique[page.number] = page
    return list(unique.values())


def _extension_for(content_type: str, path: Path) -> str:
    normalized = (content_type or "").split(";")[0].strip().lower()
    if normalized in _EXTENSIONS:
        return _EXTENSIONS[normalized]
    suffix = path.suffix.lower()
    if suffix and len(suffix) <= 8 and suffix.lstrip(".").isalnum():
        return suffix
    guessed = mimetypes.guess_extension(normalized) if normalized else None
    return guessed or ".img"


def _content_type_for(filename: str) -> str:
    return _CONTENT_TYPES.get(Path(filename).suffix.lower(), "application/octet-stream")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _state_from_row(row: sqlite3.Row) -> ArchiveState:
    return ArchiveState(
        chapter_id=uuid.UUID(row["chapter_id"]),
        source=row["source"],
        translator=row["translator"],
        status=row["status"],
        mode=row["mode"],
        page_count=int(row["page_count"] or 0),
        total_bytes=int(row["total_bytes"] or 0),
        sha256=row["sha256"],
        archive_path=row["archive_path"],
        error=row["error"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


class ArchiveManager:
    """Persist fetched chapters so later readers never touch the source again.

    Small chapters live in SQLite page blobs (``mode="db"``); larger ones are
    packed into a ZIP on disk (``mode="zip"``).  Downloads go through the
    existing :class:`MediaCache`, which already implements polite rate limits.
    """

    def __init__(
        self,
        cache: MediaCache,
        *,
        db_path: Path,
        archive_dir: Path,
        threshold_bytes: int = DEFAULT_THRESHOLD_BYTES,
        max_bytes: int = 0,
        prune_interval_seconds: int = 60 * 60,
    ) -> None:
        self.cache = cache
        self.db_path = Path(db_path).resolve()
        self.root = Path(archive_dir).resolve()
        self.threshold_bytes = max(0, int(threshold_bytes))
        self.max_bytes = max(0, int(max_bytes))
        self.prune_interval_seconds = max(0, int(prune_interval_seconds))
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._guard = asyncio.Lock()
        self._prune_guard = asyncio.Lock()
        self._prune_task: asyncio.Task[None] | None = None
        self._evictions = 0
        self._last_pruned_at: datetime | None = None
        self._ensure_schema()

    # ------------------------------------------------------------------
    # SQLite plumbing
    # ------------------------------------------------------------------

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA busy_timeout = 30000")
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _ensure_schema(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(_SCHEMA)
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(chapter_archives)").fetchall()
            }
            if "last_accessed_at" not in columns:
                connection.execute(
                    "ALTER TABLE chapter_archives ADD COLUMN last_accessed_at TEXT"
                )
                connection.execute(
                    "UPDATE chapter_archives SET last_accessed_at = updated_at "
                    "WHERE last_accessed_at IS NULL"
                )

    def _get_row(self, chapter_id: str) -> sqlite3.Row | None:
        with self._connect() as connection:
            return connection.execute(
                "SELECT * FROM chapter_archives WHERE chapter_id = ?", (chapter_id,)
            ).fetchone()

    def _touch_sync(self, chapter_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE chapter_archives SET last_accessed_at = ? WHERE chapter_id = ?",
                (_now().isoformat(), chapter_id),
            )

    def _queue(
        self,
        chapter_id: str,
        source: str,
        translator: str | None,
        page_count: int,
        now: datetime,
    ) -> sqlite3.Row:
        timestamp = now.isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO chapter_archives (
                    chapter_id, source, translator, status, mode, page_count,
                    total_bytes, sha256, archive_path, error, created_at, updated_at
                )
                VALUES (?, ?, ?, 'queued', NULL, ?, 0, NULL, NULL, NULL, ?, ?)
                ON CONFLICT(chapter_id) DO UPDATE SET
                    source = excluded.source,
                    translator = excluded.translator,
                    status = 'queued',
                    mode = NULL,
                    page_count = excluded.page_count,
                    total_bytes = 0,
                    sha256 = NULL,
                    archive_path = NULL,
                    error = NULL,
                    updated_at = excluded.updated_at
                """,
                (chapter_id, source, translator, page_count, timestamp, timestamp),
            )
            row = connection.execute(
                "SELECT * FROM chapter_archives WHERE chapter_id = ?", (chapter_id,)
            ).fetchone()
        if row is None:  # pragma: no cover - the insert above cannot vanish
            raise RuntimeError("archive row was not persisted")
        return row

    def _mark(
        self,
        chapter_id: str,
        status: Literal["queued", "running", "done", "failed"],
        *,
        mode: Literal["db", "zip"] | None = None,
        page_count: int = 0,
        total_bytes: int = 0,
        sha256: str | None = None,
        archive_path: str | None = None,
        error: str | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE chapter_archives SET
                    status = ?, mode = ?, page_count = ?, total_bytes = ?,
                    sha256 = ?, archive_path = ?, error = ?, updated_at = ?
                WHERE chapter_id = ?
                """,
                (
                    status,
                    mode,
                    page_count,
                    total_bytes,
                    sha256,
                    archive_path,
                    error,
                    _now().isoformat(),
                    chapter_id,
                ),
            )
            if status == "done":
                connection.execute(
                    "UPDATE chapter_archives SET last_accessed_at = ? WHERE chapter_id = ?",
                    (_now().isoformat(), chapter_id),
                )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _startup_sync(self) -> None:
        self._ensure_schema()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE chapter_archives
                SET status = 'failed', error = ?, updated_at = ?
                WHERE status IN ('queued', 'running')
                """,
                ("Сервис был перезапущен", _now().isoformat()),
            )
        shutil.rmtree(self.root / ".tmp", ignore_errors=True)
        for path in self.root.glob("*.tmp"):
            with suppress(OSError):
                path.unlink(missing_ok=True)

    async def startup(self) -> None:
        await asyncio.to_thread(self._startup_sync)

    def _ready_sync(self) -> bool:
        if not self.root.exists() or not self.db_path.exists():
            return False
        try:
            with self._connect() as connection:
                connection.execute("SELECT 1 FROM chapter_archives LIMIT 1").fetchone()
        except sqlite3.Error:
            return False
        return True

    async def ready(self) -> bool:
        return await asyncio.to_thread(self._ready_sync)

    async def stats(self) -> ArchiveStats:
        return await asyncio.to_thread(self._stats_sync)

    def _stats_sync(self) -> ArchiveStats:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT status, COUNT(*) AS count, COALESCE(SUM(total_bytes), 0) AS bytes
                FROM chapter_archives
                GROUP BY status
                """
            ).fetchall()
        counts = {str(row["status"]): int(row["count"]) for row in rows}
        done_bytes = int(
            next((row["bytes"] for row in rows if row["status"] == "done"), 0) or 0
        )
        db_bytes = self.db_path.stat().st_size if self.db_path.exists() else 0
        return ArchiveStats(
            total=sum(counts.values()),
            done=counts.get("done", 0),
            failed=counts.get("failed", 0),
            pending=counts.get("queued", 0) + counts.get("running", 0),
            done_bytes=done_bytes,
            db_bytes=db_bytes,
            evictions=self._evictions,
            last_pruned_at=self._last_pruned_at,
        )

    async def close(self) -> None:
        prune_task = self._prune_task
        self._prune_task = None
        if prune_task is not None:
            prune_task.cancel()
            await asyncio.gather(prune_task, return_exceptions=True)
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()

    # ------------------------------------------------------------------
    # Public operations
    # ------------------------------------------------------------------

    async def create(self, request: ArchiveRequest) -> tuple[ArchiveState, bool]:
        """Queue an archive job.

        Returns ``(state, created)``.  ``created`` is true only when a new
        worker was started; repeat calls for a finished chapter are idempotent.
        """
        pages = _normalize_pages(request.pages)
        chapter_id = str(request.chapter_id)
        async with self._guard:
            row = await asyncio.to_thread(self._get_row, chapter_id)
            if row is not None:
                state = _state_from_row(row)
                if state.status == "done" and state.page_count == len(pages):
                    await asyncio.to_thread(self._touch_sync, chapter_id)
                    return state, False
                if state.status in {"queued", "running"}:
                    return state, False
            row = await asyncio.to_thread(
                self._queue,
                chapter_id,
                request.source,
                request.translator,
                len(pages),
                _now(),
            )
            state = _state_from_row(row)
            normalized = request.model_copy(update={"pages": pages})
            self._spawn(chapter_id, normalized)
        return state, True

    def _spawn(self, chapter_id: str, request: ArchiveRequest) -> None:
        task = asyncio.create_task(self._run(request))
        self._tasks[chapter_id] = task

        def _forget(completed: asyncio.Task[None]) -> None:
            if self._tasks.get(chapter_id) is completed:
                self._tasks.pop(chapter_id, None)

        task.add_done_callback(_forget)

    async def metadata(self, chapter_id: uuid.UUID) -> ArchiveState | None:
        row = await asyncio.to_thread(self._get_row, str(chapter_id))
        return _state_from_row(row) if row is not None else None

    async def summary(self, chapter_ids: list[uuid.UUID]) -> list[ArchiveSummaryItem]:
        """Return archive status for many chapters without raising for missing rows."""

        keys = list(dict.fromkeys(str(chapter_id) for chapter_id in chapter_ids))
        if not keys:
            return []
        return await asyncio.to_thread(self._summary_sync, keys)

    async def page(self, chapter_id: uuid.UUID, number: int) -> ArchivedPage | None:
        row = await asyncio.to_thread(self._get_row, str(chapter_id))
        if row is None or row["status"] != "done":
            return None
        result: ArchivedPage | None = None
        if row["mode"] == "db":
            result = await asyncio.to_thread(self._read_blob, str(chapter_id), number)
        elif row["mode"] == "zip" and row["archive_path"]:
            result = await asyncio.to_thread(
                self._read_zip_page, Path(row["archive_path"]), number
            )
        if result is not None:
            await asyncio.to_thread(self._touch_sync, str(chapter_id))
        return result

    async def delete(self, chapter_id: uuid.UUID) -> bool:
        key = str(chapter_id)
        async with self._guard:
            row = await asyncio.to_thread(self._get_row, key)
            task = self._tasks.pop(key, None)
            if task is not None and not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            await asyncio.to_thread(self._delete_sync, key)
        return row is not None

    async def prune(self, *, dry_run: bool = False) -> ArchivePruneResult:
        """Evict least-recently-read chapters until the archive fits its cap."""

        if self.max_bytes <= 0:
            stats = await self.stats()
            return ArchivePruneResult(
                removed=0,
                freed_bytes=0,
                used_bytes=stats.done_bytes,
                cap_bytes=0,
                dry_run=dry_run,
            )
        async with self._prune_guard:
            result = await asyncio.to_thread(self._prune_sync, dry_run)
        if not dry_run:
            if result.removed:
                self._evictions += result.removed
                logger.info(
                    "chapter archive LRU evicted %s chapter(s), %s bytes; cap=%s bytes",
                    result.removed,
                    result.freed_bytes,
                    self.max_bytes,
                )
            self._last_pruned_at = _now()
        self._log_usage(result.used_bytes)
        return result

    def _prune_sync(self, dry_run: bool) -> ArchivePruneResult:
        with self._connect() as connection:
            used_bytes = int(
                connection.execute(
                    "SELECT COALESCE(SUM(total_bytes), 0) FROM chapter_archives "
                    "WHERE status = 'done'"
                ).fetchone()[0]
                or 0
            )
            if used_bytes <= self.max_bytes:
                return ArchivePruneResult(
                    removed=0,
                    freed_bytes=0,
                    used_bytes=used_bytes,
                    cap_bytes=self.max_bytes,
                    dry_run=dry_run,
                )
            rows = connection.execute(
                """
                SELECT chapter_id, total_bytes, archive_path
                FROM chapter_archives
                WHERE status = 'done'
                ORDER BY COALESCE(last_accessed_at, updated_at) ASC, chapter_id ASC
                """
            ).fetchall()
            removed = 0
            freed_bytes = 0
            for row in rows:
                if used_bytes <= self.max_bytes:
                    break
                size = int(row["total_bytes"] or 0)
                if not dry_run and not self._remove_archive_files(row):
                    # Keep the row so the next cycle retries once the file is
                    # no longer held open by a reader.  Removing metadata while
                    # the ZIP is still on disk would leave an orphan.
                    continue
                key = str(row["chapter_id"])
                if not dry_run:
                    connection.execute(
                        "DELETE FROM page_blobs WHERE chapter_id = ?", (key,)
                    )
                    connection.execute(
                        "DELETE FROM chapter_archives WHERE chapter_id = ?", (key,)
                    )
                used_bytes -= size
                removed += 1
                freed_bytes += size
            return ArchivePruneResult(
                removed=removed,
                freed_bytes=freed_bytes,
                used_bytes=max(0, used_bytes),
                cap_bytes=self.max_bytes,
                dry_run=dry_run,
            )

    def _remove_archive_files(self, row: sqlite3.Row) -> bool:
        key = str(row["chapter_id"])
        paths: list[Path] = [self.root / f"{key}.zip", self.root / f"{key}.zip.tmp"]
        archive_path = row["archive_path"]
        if archive_path:
            candidate = Path(str(archive_path))
            try:
                resolved = candidate.resolve()
            except OSError:
                resolved = candidate
            # Never unlink outside the configured archive directory, even if a
            # stale or tampered row points elsewhere.
            if resolved.is_relative_to(self.root):
                paths.append(resolved)
        seen: set[Path] = set()
        for path in paths:
            if path in seen:
                continue
            seen.add(path)
            try:
                path.unlink(missing_ok=True)
            except OSError:
                logger.warning(
                    "could not evict chapter archive file; will retry next cycle",
                    extra={"path": str(path)},
                )
                return False
        return True

    def _log_usage(self, used_bytes: int) -> None:
        level = usage_level(used_bytes, self.max_bytes)
        if level == "critical":
            logger.error(
                "chapter archive is above 90%% of its cap: %s/%s bytes",
                used_bytes,
                self.max_bytes,
            )
        elif level == "warning":
            logger.warning(
                "chapter archive is above 80%% of its cap: %s/%s bytes",
                used_bytes,
                self.max_bytes,
            )

    def start_periodic_prune(
        self, interval_seconds: float | None = None
    ) -> asyncio.Task[None] | None:
        """Start the hourly archive sweep; returns ``None`` when uncapped."""

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
            self._prune_loop(interval), name="chapter-archive-prune"
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
                logger.exception("periodic chapter archive prune failed")

    # ------------------------------------------------------------------
    # Worker
    # ------------------------------------------------------------------

    async def _run(self, request: ArchiveRequest) -> None:
        chapter_id = str(request.chapter_id)
        pages = _normalize_pages(request.pages)
        work_dir = self.root / ".tmp" / f"{chapter_id}-{uuid.uuid4().hex}"
        try:
            work_dir.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(self._mark, chapter_id, "running", page_count=len(pages))
            entries: list[_Entry] = []
            total_bytes = 0
            for page in pages:
                media = await self.cache.get(page.url)
                extension = _extension_for(media.content_type, media.path)
                destination = work_dir / f"{page.number:04d}{extension}"
                await asyncio.to_thread(shutil.copyfile, media.path, destination)
                size = destination.stat().st_size
                total_bytes += size
                entries.append(
                    _Entry(
                        page=page,
                        path=destination,
                        content_type=media.content_type or "application/octet-stream",
                        size=size,
                    )
                )

            if total_bytes <= self.threshold_bytes:
                await asyncio.to_thread(self._store_blobs, chapter_id, entries)
                await asyncio.to_thread(
                    self._mark,
                    chapter_id,
                    "done",
                    mode="db",
                    page_count=len(entries),
                    total_bytes=total_bytes,
                )
            else:
                archive_path = self.root / f"{chapter_id}.zip"
                temp_path = self.root / f"{chapter_id}.zip.tmp"
                await asyncio.to_thread(self._build_zip, temp_path, request, entries)
                os.replace(temp_path, archive_path)
                digest = await asyncio.to_thread(_sha256_file, archive_path)
                await asyncio.to_thread(self._clear_blobs, chapter_id)
                await asyncio.to_thread(
                    self._mark,
                    chapter_id,
                    "done",
                    mode="zip",
                    page_count=len(entries),
                    total_bytes=total_bytes,
                    sha256=digest,
                    archive_path=str(archive_path),
                )
            logger.info(
                "chapter archive ready",
                extra={
                    "chapter_id": chapter_id,
                    "pages": len(entries),
                    "bytes": total_bytes,
                },
            )
            with suppress(Exception):
                await self.prune()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("chapter archive failed", extra={"chapter_id": chapter_id})
            with suppress(Exception):
                await asyncio.to_thread(
                    self._mark,
                    chapter_id,
                    "failed",
                    page_count=len(pages),
                    error=str(exc)[:500],
                )
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    # ------------------------------------------------------------------
    # Storage helpers (run in a worker thread)
    # ------------------------------------------------------------------

    def _summary_sync(self, chapter_ids: list[str]) -> list[ArchiveSummaryItem]:
        placeholders = ",".join("?" for _ in chapter_ids)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT chapter_id, status, page_count, total_bytes, error
                FROM chapter_archives
                WHERE chapter_id IN ({placeholders})
                """,
                tuple(chapter_ids),
            ).fetchall()
        by_id = {row["chapter_id"]: row for row in rows}
        items: list[ArchiveSummaryItem] = []
        for chapter_id in chapter_ids:
            row = by_id.get(chapter_id)
            if row is None:
                items.append(
                    ArchiveSummaryItem(chapter_id=uuid.UUID(chapter_id), status="missing")
                )
                continue
            raw_status = str(row["status"])
            if raw_status == "done":
                status: Literal["done", "pending", "error", "missing"] = "done"
            elif raw_status in {"queued", "running"}:
                status = "pending"
            else:
                status = "error"
            items.append(
                ArchiveSummaryItem(
                    chapter_id=uuid.UUID(chapter_id),
                    status=status,
                    page_count=int(row["page_count"] or 0),
                    total_bytes=int(row["total_bytes"] or 0),
                    error=row["error"],
                )
            )
        return items

    def _clear_blobs(self, chapter_id: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM page_blobs WHERE chapter_id = ?", (chapter_id,))

    def _store_blobs(self, chapter_id: str, entries: list[_Entry]) -> None:
        rows = [
            (
                chapter_id,
                entry.page.number,
                entry.content_type,
                entry.path.read_bytes(),
            )
            for entry in entries
        ]
        with self._connect() as connection:
            connection.execute("DELETE FROM page_blobs WHERE chapter_id = ?", (chapter_id,))
            connection.executemany(
                """
                INSERT INTO page_blobs (chapter_id, number, content_type, bytes)
                VALUES (?, ?, ?, ?)
                """,
                rows,
            )
        (self.root / f"{chapter_id}.zip").unlink(missing_ok=True)

    def _build_zip(self, destination: Path, request: ArchiveRequest, entries: list[_Entry]) -> None:
        manifest = {
            "chapter_id": str(request.chapter_id),
            "source": request.source,
            "translator": request.translator,
            "page_count": len(entries),
            "mode": "zip",
            "pages": [
                {
                    "number": entry.page.number,
                    "filename": entry.path.name,
                    "content_type": entry.content_type,
                    "bytes": entry.size,
                    "width": entry.page.width,
                    "height": entry.page.height,
                }
                for entry in entries
            ],
        }
        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr(
                "manifest.json",
                json.dumps(manifest, ensure_ascii=False, indent=2),
            )
            for entry in entries:
                bundle.write(entry.path, entry.path.name)

    def _read_blob(self, chapter_id: str, number: int) -> ArchivedPage | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT content_type, bytes FROM page_blobs
                WHERE chapter_id = ? AND number = ?
                """,
                (chapter_id, number),
            ).fetchone()
        if row is None:
            return None
        return ArchivedPage(data=bytes(row["bytes"]), content_type=row["content_type"])

    def _read_zip_page(self, path: Path, number: int) -> ArchivedPage | None:
        if not path.exists():
            return None
        try:
            with zipfile.ZipFile(path) as bundle:
                manifest: dict[str, object] = {}
                if "manifest.json" in bundle.namelist():
                    raw_manifest = json.loads(bundle.read("manifest.json"))
                    if isinstance(raw_manifest, dict):
                        manifest = raw_manifest
                filename: str | None = None
                content_type: str | None = None
                raw_pages = manifest.get("pages")
                if isinstance(raw_pages, list):
                    for item in raw_pages:
                        if not isinstance(item, dict):
                            continue
                        if item.get("number") != number:
                            continue
                        value = item.get("filename")
                        if isinstance(value, str):
                            filename = value
                            raw_type = item.get("content_type")
                            if isinstance(raw_type, str):
                                content_type = raw_type
                        break
                if filename is None:
                    prefix = f"{number:04d}."
                    filename = next(
                        (name for name in bundle.namelist() if name.startswith(prefix)),
                        None,
                    )
                if filename is None:
                    return None
                data = bundle.read(filename)
        except (OSError, ValueError, KeyError, zipfile.BadZipFile):
            logger.warning("chapter archive is unreadable", extra={"path": str(path)})
            return None
        return ArchivedPage(
            data=data,
            content_type=content_type or _content_type_for(filename),
        )

    def _delete_sync(self, chapter_id: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM page_blobs WHERE chapter_id = ?", (chapter_id,))
            connection.execute("DELETE FROM chapter_archives WHERE chapter_id = ?", (chapter_id,))
        (self.root / f"{chapter_id}.zip").unlink(missing_ok=True)
        (self.root / f"{chapter_id}.zip.tmp").unlink(missing_ok=True)
