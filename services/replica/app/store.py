from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from .config import STORE_NAMES, ReplicaSettings
from .schemas import (
    ArchiveCopySummary,
    ArchiveEntry,
    PromoteResult,
    SnapshotMeta,
)

logger = logging.getLogger(__name__)

_CHUNK_SIZE = 1024 * 1024
_ARCHIVE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,191}\.zip$", re.IGNORECASE)


def ensure_store(store: str) -> str:
    if store not in STORE_NAMES:
        raise ValueError(f"Unknown replica store: {store}")
    return store


def safe_archive_name(name: str) -> str:
    """Validate an archive filename without touching the filesystem.

    Only plain ``*.zip`` basenames are accepted: no directories, drive letters,
    traversal components or hidden files.  The replica API maps invalid names
    to 404 so a probe cannot learn whether a file outside the archive root
    exists.
    """

    if not name or "/" in name or "\\" in name or "\x00" in name or ":" in name:
        raise ValueError("Invalid archive filename")
    if name in {".", ".."} or not _ARCHIVE_NAME_RE.fullmatch(name):
        raise ValueError("Invalid archive filename")
    return name


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_matches(actual: str, expected: str | None) -> bool:
    return expected is None or actual.lower() == expected.lower()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class SnapshotStore:
    """Consistent SQLite snapshots plus a cache of chapter archives.

    All blocking filesystem and SQLite work runs in a worker thread.  Snapshots
    are created with ``VACUUM INTO`` from a read-only connection, so the
    writable services keep their normal transaction behaviour and no long write
    lock is held.
    """

    def __init__(self, settings: ReplicaSettings) -> None:
        self.settings = settings
        self._archive_hashes: dict[str, tuple[int, int, str]] = {}

    # ------------------------------------------------------------------
    # Paths and lifecycle
    # ------------------------------------------------------------------
    @property
    def snapshot_dir(self) -> Path:
        return self.settings.snapshot_dir

    @property
    def archive_cache_dir(self) -> Path:
        return self.settings.archive_cache_dir

    @property
    def live_archive_dir(self) -> Path:
        return self.settings.media_archive_path

    def live_db_path(self, store: str) -> Path:
        return self.settings.live_db_path(ensure_store(store))

    def snapshot_path(self, store: str) -> Path:
        return self.snapshot_dir / f"{ensure_store(store)}.db"

    def _meta_path(self, store: str) -> Path:
        return self.snapshot_dir / f"{ensure_store(store)}.meta.json"

    def new_snapshot_temp(self, store: str) -> Path:
        ensure_store(store)
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        return self.snapshot_dir / f".{store}.download-{uuid.uuid4().hex}.tmp"

    def new_archive_temp(self, name: str) -> Path:
        safe_archive_name(name)
        self.archive_cache_dir.mkdir(parents=True, exist_ok=True)
        return self.archive_cache_dir / f".{name}.download-{uuid.uuid4().hex}.tmp"

    async def startup(self) -> None:
        await asyncio.to_thread(self._startup_sync)

    def _startup_sync(self) -> None:
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self.archive_cache_dir.mkdir(parents=True, exist_ok=True)

    async def ready(self) -> bool:
        return await asyncio.to_thread(self._ready_sync)

    def _ready_sync(self) -> bool:
        return all(
            path.is_dir() and os.access(path, os.R_OK | os.W_OK)
            for path in (self.snapshot_dir, self.archive_cache_dir)
        )

    # ------------------------------------------------------------------
    # Snapshot metadata
    # ------------------------------------------------------------------
    async def meta(self, store: str) -> SnapshotMeta | None:
        return await asyncio.to_thread(self._read_meta_sync, ensure_store(store))

    async def latest(self, store: str) -> SnapshotMeta | None:
        return await self.meta(store)

    def _read_meta_sync(self, store: str) -> SnapshotMeta | None:
        path = self.snapshot_path(store)
        if not path.is_file():
            return None
        stat = path.stat()
        meta: SnapshotMeta | None = None
        try:
            payload = json.loads(self._meta_path(store).read_text(encoding="utf-8"))
            meta = SnapshotMeta.model_validate({**payload, "store": store})
        except (OSError, TypeError, ValueError):
            meta = None
        if meta is not None and meta.size == stat.st_size:
            return meta.model_copy(update={"updated_at": _as_utc(meta.updated_at)})
        return SnapshotMeta(
            store=store,
            size=stat.st_size,
            sha256=_sha256_file(path),
            updated_at=datetime.fromtimestamp(stat.st_mtime, UTC),
        )

    def _write_meta_sync(self, meta: SnapshotMeta) -> None:
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        target = self._meta_path(meta.store)
        temp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        try:
            temp.write_text(meta.model_dump_json(indent=2), encoding="utf-8")
            os.replace(temp, target)
        finally:
            temp.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------
    async def snapshot(self, store: str) -> SnapshotMeta:
        return await asyncio.to_thread(self._snapshot_sync, ensure_store(store))

    def _snapshot_sync(self, store: str) -> SnapshotMeta:
        live = self.live_db_path(store)
        if not live.is_file():
            raise FileNotFoundError(f"Live database for {store} not found: {live}")

        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        target = self.snapshot_path(store)
        temp = self.snapshot_dir / f".{store}.{uuid.uuid4().hex}.tmp"
        try:
            uri = live.resolve().as_uri() + "?mode=ro"
            connection = sqlite3.connect(uri, uri=True, timeout=30)
            try:
                connection.execute("PRAGMA busy_timeout = 30000")
                connection.execute("VACUUM INTO ?", (str(temp),))
            finally:
                connection.close()
            if not temp.is_file():  # pragma: no cover - defensive
                raise RuntimeError(f"SQLite did not create snapshot for {store}")
            os.replace(temp, target)
        finally:
            temp.unlink(missing_ok=True)

        stat = target.stat()
        meta = SnapshotMeta(
            store=store,
            size=stat.st_size,
            sha256=_sha256_file(target),
            updated_at=datetime.now(UTC),
            source="local",
        )
        self._write_meta_sync(meta)
        logger.info("snapshot created store=%s size=%s", store, meta.size)
        return meta

    async def install_snapshot(
        self,
        store: str,
        temp_path: Path,
        *,
        expected_sha256: str | None = None,
        expected_size: int | None = None,
        updated_at: datetime | None = None,
        source: str | None = None,
    ) -> SnapshotMeta:
        """Verify a downloaded snapshot and atomically move it into place."""

        return await asyncio.to_thread(
            self._install_snapshot_sync,
            ensure_store(store),
            temp_path,
            expected_sha256,
            expected_size,
            updated_at,
            source,
        )

    def _install_snapshot_sync(
        self,
        store: str,
        temp_path: Path,
        expected_sha256: str | None,
        expected_size: int | None,
        updated_at: datetime | None,
        source: str | None,
    ) -> SnapshotMeta:
        if not temp_path.is_file():
            raise FileNotFoundError(f"Downloaded snapshot missing: {temp_path}")
        size = temp_path.stat().st_size
        digest = _sha256_file(temp_path)
        try:
            if expected_size is not None and size != expected_size:
                raise ValueError(
                    f"Snapshot size mismatch for {store}: {size} != {expected_size}"
                )
            if not _hash_matches(digest, expected_sha256):
                raise ValueError(f"Snapshot checksum mismatch for {store}")
            self.snapshot_dir.mkdir(parents=True, exist_ok=True)
            os.replace(temp_path, self.snapshot_path(store))
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise

        meta = SnapshotMeta(
            store=store,
            size=size,
            sha256=digest,
            updated_at=_as_utc(updated_at) if updated_at else datetime.now(UTC),
            source=source,
        )
        self._write_meta_sync(meta)
        logger.info("snapshot installed store=%s size=%s source=%s", store, size, source)
        return meta

    async def promote(self, store: str) -> PromoteResult:
        """Copy the latest verified snapshot over the live database.

        The service that owns the live database must be stopped first.  The
        previous database is copied to ``<name>.bak`` before ``os.replace``
        switches the live file atomically.
        """

        return await asyncio.to_thread(self._promote_sync, ensure_store(store))

    def _promote_sync(self, store: str) -> PromoteResult:
        live = self.live_db_path(store)
        snapshot = self.snapshot_path(store)
        meta = self._read_meta_sync(store)
        if meta is None or not snapshot.is_file():
            raise FileNotFoundError(f"No snapshot available for {store}")

        if meta.size != snapshot.stat().st_size or not _hash_matches(
            _sha256_file(snapshot), meta.sha256
        ):
            raise ValueError(f"Snapshot for {store} failed checksum verification")

        live.parent.mkdir(parents=True, exist_ok=True)
        backup: Path | None = None
        temp = live.parent / f".{live.name}.promote-{uuid.uuid4().hex}.tmp"
        try:
            if live.exists():
                backup = live.with_name(f"{live.name}.bak")
                with backup.open("wb") as target_handle, live.open("rb") as source_handle:
                    for chunk in iter(lambda: source_handle.read(_CHUNK_SIZE), b""):
                        target_handle.write(chunk)
            with temp.open("wb") as target_handle, snapshot.open("rb") as source_handle:
                for chunk in iter(lambda: source_handle.read(_CHUNK_SIZE), b""):
                    target_handle.write(chunk)
            os.replace(temp, live)
        finally:
            temp.unlink(missing_ok=True)

        logger.info("snapshot promoted store=%s live=%s", store, live)
        return PromoteResult(
            store=store,
            promoted=True,
            live_path=str(live),
            snapshot_path=str(snapshot),
            backup_path=str(backup) if backup else None,
            size=meta.size,
            sha256=meta.sha256,
            updated_at=meta.updated_at,
        )

    # ------------------------------------------------------------------
    # Chapter archives
    # ------------------------------------------------------------------
    def _archive_roots(self) -> list[Path]:
        roots = [self.live_archive_dir, self.archive_cache_dir]
        unique: list[Path] = []
        seen: set[str] = set()
        for root in roots:
            key = str(root.resolve())
            if key in seen:
                continue
            seen.add(key)
            unique.append(root)
        return unique

    def _hash_cached_sync(self, path: Path) -> str:
        stat = path.stat()
        key = str(path.resolve())
        cached = self._archive_hashes.get(key)
        if cached is not None and cached[0] == stat.st_mtime_ns and cached[1] == stat.st_size:
            return cached[2]
        digest = _sha256_file(path)
        self._archive_hashes[key] = (stat.st_mtime_ns, stat.st_size, digest)
        return digest

    async def archive_manifest(self) -> list[ArchiveEntry]:
        return await asyncio.to_thread(self._archive_manifest_sync)

    def _archive_manifest_sync(self) -> list[ArchiveEntry]:
        entries: dict[str, ArchiveEntry] = {}
        for root in self._archive_roots():
            if not root.is_dir():
                continue
            for path in sorted(root.iterdir(), key=lambda item: item.name):
                if path.name in entries or not path.is_file():
                    continue
                try:
                    safe_archive_name(path.name)
                except ValueError:
                    continue
                stat = path.stat()
                entries[path.name] = ArchiveEntry(
                    name=path.name,
                    size=stat.st_size,
                    sha256=self._hash_cached_sync(path),
                    updated_at=datetime.fromtimestamp(stat.st_mtime, UTC),
                )
        return [entries[name] for name in sorted(entries)]

    async def archive_file(self, name: str) -> Path:
        return await asyncio.to_thread(self._archive_file_sync, name)

    def _archive_file_sync(self, name: str) -> Path:
        safe = safe_archive_name(name)
        for root in self._archive_roots():
            root_resolved = root.resolve()
            candidate = (root_resolved / safe).resolve()
            if candidate.parent != root_resolved:
                continue
            if candidate.is_file():
                return candidate
        raise FileNotFoundError(f"Archive not found: {safe}")

    async def write_archive(
        self,
        name: str,
        data: bytes,
        *,
        expected_sha256: str | None = None,
        updated_at: datetime | None = None,
    ) -> ArchiveEntry:
        safe = safe_archive_name(name)
        return await asyncio.to_thread(
            self._write_archive_sync, safe, data, expected_sha256, updated_at
        )

    def _write_archive_sync(
        self,
        name: str,
        data: bytes,
        expected_sha256: str | None,
        updated_at: datetime | None,
    ) -> ArchiveEntry:
        temp = self.new_archive_temp(name)
        try:
            temp.write_bytes(data)
            return self._install_archive_sync(
                name,
                temp,
                expected_sha256,
                len(data),
                updated_at,
            )
        finally:
            temp.unlink(missing_ok=True)

    async def install_archive(
        self,
        name: str,
        temp_path: Path,
        *,
        expected_sha256: str | None = None,
        expected_size: int | None = None,
        updated_at: datetime | None = None,
    ) -> ArchiveEntry:
        return await asyncio.to_thread(
            self._install_archive_sync,
            safe_archive_name(name),
            temp_path,
            expected_sha256,
            expected_size,
            updated_at,
        )

    def _install_archive_sync(
        self,
        name: str,
        temp_path: Path,
        expected_sha256: str | None,
        expected_size: int | None,
        updated_at: datetime | None,
    ) -> ArchiveEntry:
        if not temp_path.is_file():
            raise FileNotFoundError(f"Downloaded archive missing: {temp_path}")
        stat = temp_path.stat()
        digest = _sha256_file(temp_path)
        try:
            if expected_size is not None and stat.st_size != expected_size:
                raise ValueError(f"Archive size mismatch for {name}")
            if not _hash_matches(digest, expected_sha256):
                raise ValueError(f"Archive checksum mismatch for {name}")
            self.archive_cache_dir.mkdir(parents=True, exist_ok=True)
            target = self.archive_cache_dir / name
            os.replace(temp_path, target)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise

        final_stat = target.stat()
        self._archive_hashes[str(target.resolve())] = (
            final_stat.st_mtime_ns,
            final_stat.st_size,
            digest,
        )
        return ArchiveEntry(
            name=name,
            size=final_stat.st_size,
            sha256=digest,
            updated_at=_as_utc(updated_at)
            if updated_at
            else datetime.fromtimestamp(final_stat.st_mtime, UTC),
        )

    async def promote_archives(self) -> ArchiveCopySummary:
        return await asyncio.to_thread(self._promote_archives_sync)

    def _promote_archives_sync(self) -> ArchiveCopySummary:
        cache_root = self.archive_cache_dir
        live_root = self.live_archive_dir
        if not cache_root.is_dir():
            return ArchiveCopySummary()
        if cache_root.resolve() == live_root.resolve():
            return ArchiveCopySummary(skipped=len(list(cache_root.glob("*.zip"))))

        live_root.mkdir(parents=True, exist_ok=True)
        copied = 0
        skipped = 0
        total_bytes = 0
        for source in sorted(cache_root.iterdir(), key=lambda item: item.name):
            if not source.is_file():
                continue
            try:
                safe_archive_name(source.name)
            except ValueError:
                continue
            target = live_root / source.name
            if (
                target.is_file()
                and target.stat().st_size == source.stat().st_size
                and _hash_matches(_sha256_file(target), self._hash_cached_sync(source))
            ):
                skipped += 1
                continue
            temp = live_root / f".{source.name}.promote-{uuid.uuid4().hex}.tmp"
            try:
                with temp.open("wb") as target_handle, source.open("rb") as source_handle:
                    for chunk in iter(lambda: source_handle.read(_CHUNK_SIZE), b""):
                        target_handle.write(chunk)
                os.replace(temp, target)
                copied += 1
                total_bytes += source.stat().st_size
            finally:
                temp.unlink(missing_ok=True)
        return ArchiveCopySummary(copied=copied, skipped=skipped, bytes=total_bytes)
