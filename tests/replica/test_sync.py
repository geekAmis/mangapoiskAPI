from __future__ import annotations

from collections.abc import Callable

import pytest
from services.replica.app.config import ReplicaSettings
from services.replica.app.sync import ReplicaSync

from tests.replica.support import (
    StubResponse,
    build_replica_routes,
    db_values,
    prepare_destination,
    prepare_source,
    registry_payload,
    serve,
)


@pytest.mark.asyncio
async def test_explicit_peer_pulls_snapshots_and_archives(
    settings_factory: Callable[..., ReplicaSettings],
) -> None:
    source_settings = settings_factory()
    destination_settings = settings_factory()
    source = await prepare_source(source_settings)
    destination = await prepare_destination(destination_settings)
    routes = await build_replica_routes(source)

    with serve(routes, token=destination_settings.internal_token) as (base, state):
        manager = ReplicaSync(
            destination_settings,
            destination,
            attempts=1,
            backoff_seconds=0,
        )
        try:
            report = await manager.sync(peers=[base])
            assert report.mode == "peers"
            assert report.errors == {}
            assert set(report.stores) == {"catalog", "library", "control", "media"}
            assert all(result.status == "pulled" for result in report.stores.values())
            assert report.archives is not None
            assert report.archives.pulled == 1
            assert report.archives.failed == 0

            repeat = await manager.sync(peers=[base])
            assert all(result.status == "unchanged" for result in repeat.stores.values())
            assert repeat.archives is not None
            assert repeat.archives.skipped == 1
            assert repeat.archives.pulled == 0

            status = await manager.status()
        finally:
            await manager.close()

    assert all(token == destination_settings.internal_token for _, token in state.requests)
    assert status.last_sync.last_source == base
    assert status.last_error is None
    assert status.stores["catalog"].available is True
    assert status.stores["catalog"].sha256
    assert status.archives.count == 1
    assert status.archives.bytes > 0

    assert db_values(destination.snapshot_path("catalog")) == ["catalog-row"]
    assert db_values(destination.snapshot_path("library")) == ["library-row"]
    cached_archive = destination_settings.archive_cache_dir / "chapter-1.zip"
    assert cached_archive.is_file()

    promoted = await destination.promote("catalog")
    assert promoted.promoted is True
    assert db_values(destination_settings.live_db_path("catalog")) == ["catalog-row"]
    backup = destination_settings.live_db_path("catalog").with_name("catalog.db.bak")
    assert db_values(backup) == ["old-catalog"]


@pytest.mark.asyncio
async def test_registry_driven_sync_uses_selected_replica(
    settings_factory: Callable[..., ReplicaSettings],
) -> None:
    source_settings = settings_factory()
    destination_settings = settings_factory()
    source = await prepare_source(source_settings)
    destination = await prepare_destination(destination_settings)
    routes = await build_replica_routes(source)

    with serve(routes, token=destination_settings.internal_token) as (base, state):
        routes["/api/v1/registry"] = StubResponse.json(registry_payload(base))
        manager_settings = destination_settings.model_copy(
            update={"registry_url": f"{base}/api/v1/registry"}
        )
        manager = ReplicaSync(
            manager_settings,
            destination,
            attempts=1,
            backoff_seconds=0,
        )
        try:
            report = await manager.sync()
        finally:
            await manager.close()

    assert report.mode == "registry"
    assert report.errors == {}
    assert all(result.status == "pulled" for result in report.stores.values())
    assert report.archives is not None
    assert report.archives.pulled == 1
    registry_requests = [path for path, _ in state.requests if path == "/api/v1/registry"]
    assert registry_requests
    assert db_values(destination.snapshot_path("media")) == ["media-row"]


@pytest.mark.asyncio
async def test_source_node_snapshots_its_own_databases(
    settings_factory: Callable[..., ReplicaSettings],
) -> None:
    settings = settings_factory()
    store = await prepare_destination(settings)
    routes = {
        "/api/v1/registry": StubResponse.json(registry_payload(settings.self_replica_url))
    }

    with serve(routes, token=settings.internal_token) as (base, _):
        manager_settings = settings.model_copy(
            update={"registry_url": f"{base}/api/v1/registry"}
        )
        manager = ReplicaSync(
            manager_settings,
            store,
            attempts=1,
            backoff_seconds=0,
        )
        try:
            report = await manager.sync()
        finally:
            await manager.close()

    assert report.errors == {}
    assert all(result.status == "skipped" for result in report.stores.values())
    assert report.stores["catalog"].source == settings.self_replica_url
    assert report.stores["catalog"].sha256
    for store_name in ("catalog", "library", "control", "media"):
        assert db_values(settings.snapshot_dir / f"{store_name}.db") == [
            f"old-{store_name}"
        ]


@pytest.mark.asyncio
async def test_registry_failure_keeps_last_snapshots(
    settings_factory: Callable[..., ReplicaSettings],
) -> None:
    destination_settings = settings_factory()
    destination = await prepare_source(destination_settings)
    original = await destination.meta("catalog")
    assert original is not None

    with serve(
        {"/api/v1/registry": StubResponse(status=503)},
        token=destination_settings.internal_token,
    ) as (base, _):
        manager_settings = destination_settings.model_copy(
            update={"registry_url": f"{base}/api/v1/registry"}
        )
        manager = ReplicaSync(
            manager_settings,
            destination,
            attempts=1,
            backoff_seconds=0,
        )
        try:
            report = await manager.sync()
            status = await manager.status()
        finally:
            await manager.close()

    assert report.errors["registry"]
    assert all(result.status == "failed" for result in report.stores.values())
    assert "registry unavailable" in report.errors["registry"]
    assert status.last_error is not None
    assert status.stores["catalog"].error is not None
    current = await destination.meta("catalog")
    assert current is not None
    assert current.sha256 == original.sha256
    assert destination.snapshot_path("catalog").is_file()


@pytest.mark.asyncio
async def test_bootstrap_promotes_databases_and_archives(
    settings_factory: Callable[..., ReplicaSettings],
) -> None:
    source_settings = settings_factory()
    destination_settings = settings_factory()
    source = await prepare_source(source_settings)
    destination = await prepare_destination(destination_settings)
    routes = await build_replica_routes(source)

    with serve(routes, token=destination_settings.internal_token) as (base, _):
        manager = ReplicaSync(
            destination_settings,
            destination,
            attempts=1,
            backoff_seconds=0,
        )
        try:
            report = await manager.bootstrap(base, promote=True)
        finally:
            await manager.close()

    assert report.source == base
    assert report.errors == {}
    assert len(report.promoted) == 4
    assert all(result.promoted for result in report.promoted)
    assert report.archives_copied == 1

    for store in ("catalog", "library", "control", "media"):
        live = destination_settings.live_db_path(store)
        assert db_values(live) == [f"{store}-row"]
        backup = live.with_name(f"{live.name}.bak")
        assert db_values(backup) == [f"old-{store}"]
    live_archive = destination_settings.media_archive_path / "chapter-1.zip"
    assert live_archive.is_file()
    assert live_archive.read_bytes() == (
        source_settings.media_archive_path / "chapter-1.zip"
    ).read_bytes()
