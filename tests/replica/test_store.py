from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest
from services.replica.app.config import ReplicaSettings
from services.replica.app.store import SnapshotStore, safe_archive_name

from tests.replica.support import append_db, create_db, db_values, make_zip


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.asyncio
async def test_snapshot_checksum_size_and_contents(replica_settings: ReplicaSettings) -> None:
    create_db(replica_settings.live_db_path("catalog"), ["one", "two"])
    create_db(replica_settings.live_db_path("library"), ["favourite"])
    store = SnapshotStore(replica_settings)
    await store.startup()

    catalog = await store.snapshot("catalog")
    library = await store.snapshot("library")

    catalog_path = replica_settings.snapshot_dir / "catalog.db"
    assert catalog_path.is_file()
    assert catalog.size == catalog_path.stat().st_size
    assert catalog.sha256 == _sha256(catalog_path)
    assert catalog.updated_at.tzinfo is not None
    assert catalog.source == "local"

    assert db_values(catalog_path) == ["one", "two"]
    assert db_values(replica_settings.snapshot_dir / "library.db") == ["favourite"]
    assert library.sha256 == _sha256(replica_settings.snapshot_dir / "library.db")

    cached = await store.meta("catalog")
    assert cached is not None
    assert cached.sha256 == catalog.sha256
    assert cached.size == catalog.size

    with pytest.raises(FileNotFoundError):
        await store.snapshot("media")


@pytest.mark.asyncio
async def test_promote_replaces_live_database_and_creates_backup(
    replica_settings: ReplicaSettings,
) -> None:
    live = replica_settings.live_db_path("catalog")
    create_db(live, ["before"])
    store = SnapshotStore(replica_settings)
    await store.startup()
    snapshot = await store.snapshot("catalog")

    append_db(live, ["after-snapshot"])
    assert db_values(live) == ["before", "after-snapshot"]

    result = await store.promote("catalog")

    assert result.promoted is True
    assert result.store == "catalog"
    assert result.size == snapshot.size
    assert result.sha256 == snapshot.sha256
    assert db_values(live) == ["before"]
    backup = live.with_name(f"{live.name}.bak")
    assert backup.is_file()
    assert db_values(backup) == ["before", "after-snapshot"]
    # Promotion copies; the snapshot remains available for other nodes.
    assert (replica_settings.snapshot_dir / "catalog.db").is_file()


@pytest.mark.asyncio
async def test_promote_requires_a_snapshot(replica_settings: ReplicaSettings) -> None:
    store = SnapshotStore(replica_settings)
    await store.startup()
    with pytest.raises(FileNotFoundError):
        await store.promote("library")


@pytest.mark.asyncio
async def test_archive_manifest_union_and_safe_names(
    replica_settings: ReplicaSettings,
) -> None:
    store = SnapshotStore(replica_settings)
    await store.startup()
    make_zip(replica_settings.media_archive_path / "a.zip", b"a")
    make_zip(replica_settings.media_archive_path / "b.zip", b"b")
    (replica_settings.media_archive_path / "ignored.txt").write_text("nope")
    cached_payload = make_zip(replica_settings.archive_cache_dir / "c.zip", b"ccc")

    manifest = await store.archive_manifest()

    assert [entry.name for entry in manifest] == ["a.zip", "b.zip", "c.zip"]
    by_name = {entry.name: entry for entry in manifest}
    assert by_name["a.zip"].sha256 == _sha256(replica_settings.media_archive_path / "a.zip")
    assert by_name["c.zip"].size == len(cached_payload)

    assert await store.archive_file("a.zip") == (
        replica_settings.media_archive_path / "a.zip"
    ).resolve()
    assert await store.archive_file("c.zip") == (
        replica_settings.archive_cache_dir / "c.zip"
    ).resolve()

    for bad in (
        "..",
        "../catalog.db",
        "..\\catalog.db",
        "/etc/passwd.zip",
        "sub/dir.zip",
        "C:\\evil.zip",
        ".hidden.zip",
        "not-a-zip.txt",
        "",
    ):
        with pytest.raises(ValueError):
            safe_archive_name(bad)

    with pytest.raises(ValueError):
        await store.archive_file("../catalog.db")
    with pytest.raises(FileNotFoundError):
        await store.archive_file("missing.zip")


@pytest.mark.asyncio
async def test_write_archive_and_promote_archives(replica_settings: ReplicaSettings) -> None:
    store = SnapshotStore(replica_settings)
    await store.startup()
    payload = make_zip(replica_settings.archive_cache_dir / "chapter.zip", b"cached")

    entry = await store.write_archive("chapter.zip", payload)
    assert entry.size == len(payload)
    assert entry.sha256 == hashlib.sha256(payload).hexdigest()

    copied = await store.promote_archives()
    assert copied.copied == 1
    assert copied.skipped == 0
    assert (replica_settings.media_archive_path / "chapter.zip").read_bytes() == payload

    again = await store.promote_archives()
    assert again.copied == 0
    assert again.skipped == 1


@pytest.mark.asyncio
async def test_install_snapshot_rejects_bad_checksum(
    replica_settings: ReplicaSettings,
) -> None:
    store = SnapshotStore(replica_settings)
    await store.startup()
    temp = store.new_snapshot_temp("catalog")
    temp.write_bytes(b"not-a-real-database")

    with pytest.raises(ValueError):
        await store.install_snapshot("catalog", temp, expected_sha256="0" * 64)
    assert not temp.exists()
    assert await store.meta("catalog") is None


@pytest.mark.asyncio
async def test_unknown_store_is_rejected(replica_settings: ReplicaSettings) -> None:
    store = SnapshotStore(replica_settings)
    with pytest.raises(ValueError):
        await store.snapshot("unknown")
    with pytest.raises(ValueError):
        await store.promote("unknown")
    with pytest.raises(ValueError):
        store.live_db_path("unknown")


def test_sqlite_file_is_not_left_locked(replica_settings: ReplicaSettings) -> None:
    create_db(replica_settings.live_db_path("catalog"), ["row"])
    store = SnapshotStore(replica_settings)
    # Exercise the synchronous read-only path directly to prove it closes the
    # connection before returning.
    store._snapshot_sync("catalog")
    with sqlite3.connect(replica_settings.live_db_path("catalog")) as connection:
        connection.execute("INSERT INTO items (value) VALUES ('after')")
        connection.commit()
    assert db_values(replica_settings.snapshot_dir / "catalog.db") == ["row"]
