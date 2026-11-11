from __future__ import annotations

import asyncio
from collections.abc import Callable

from fastapi.testclient import TestClient
from manga_common.config import get_settings
from services.replica.app.config import ReplicaSettings
from services.replica.app.main import create_app
from services.replica.app.store import SnapshotStore

from tests.replica.support import (
    append_db,
    build_replica_routes,
    create_db,
    db_values,
    make_zip,
    prepare_destination,
    prepare_source,
    serve,
)


def _prepare_local(settings: ReplicaSettings) -> None:
    store = SnapshotStore(settings)
    asyncio.run(store.startup())
    create_db(settings.live_db_path("catalog"), ["before"])
    create_db(settings.live_db_path("media"), ["media-row"])
    make_zip(settings.media_archive_path / "chapter-1.zip", b"page")
    asyncio.run(store.snapshot("catalog"))
    asyncio.run(store.snapshot("media"))
    append_db(settings.live_db_path("catalog"), ["after-snapshot"])


def _client(settings: ReplicaSettings) -> TestClient:
    application = create_app(settings)
    application.dependency_overrides[get_settings] = lambda: settings
    return TestClient(application)


def test_status_downloads_promotion_and_archive_endpoints(
    settings_factory: Callable[..., ReplicaSettings],
) -> None:
    settings = settings_factory()
    _prepare_local(settings)
    headers = {"X-Internal-Token": settings.internal_token}

    with _client(settings) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/internal/replica/status").status_code == 401

        response = client.get("/internal/replica/status", headers=headers)
        assert response.status_code == 200
        payload = response.json()
        assert payload["service"] == "replica"
        assert payload["self_url"] == settings.self_replica_url
        assert payload["sync_disabled"] is True
        assert payload["stores"]["catalog"]["available"] is True
        assert payload["stores"]["catalog"]["size"] > 0
        assert len(payload["stores"]["catalog"]["sha256"]) == 64
        assert payload["stores"]["library"]["available"] is False
        assert payload["archives"]["count"] == 1
        assert payload["archives"]["bytes"] > 0
        assert "last_run_at" in payload["last_sync"]

        snapshot_bytes = (settings.snapshot_dir / "catalog.db").read_bytes()
        download = client.get("/internal/replica/db/catalog", headers=headers)
        assert download.status_code == 200
        assert download.content == snapshot_bytes
        assert download.headers["content-type"].startswith("application/octet-stream")
        assert download.headers["x-checksum"] == payload["stores"]["catalog"]["sha256"]
        assert download.headers["x-size"] == str(len(snapshot_bytes))
        assert download.headers["x-updated-at"]

        meta = client.get("/internal/replica/db/catalog/meta", headers=headers)
        assert meta.status_code == 200
        assert meta.json()["sha256"] == payload["stores"]["catalog"]["sha256"]

        assert client.get("/internal/replica/db/unknown", headers=headers).status_code == 404
        assert (
            client.get("/internal/replica/db/unknown/meta", headers=headers).status_code
            == 404
        )

        invalid = client.post(
            "/internal/replica/sync",
            headers=headers,
            json={"stores": ["unknown"]},
        )
        assert invalid.status_code == 422

        manifest = client.get("/internal/replica/archives", headers=headers)
        assert manifest.status_code == 200
        body = manifest.json()
        assert body["count"] == 1
        assert body["archives"][0]["name"] == "chapter-1.zip"
        assert body["bytes"] == body["archives"][0]["size"]

        archive = client.get(
            "/internal/replica/archives/chapter-1.zip", headers=headers
        )
        assert archive.status_code == 200
        assert archive.content == (settings.media_archive_path / "chapter-1.zip").read_bytes()

        assert (
            client.get("/internal/replica/archives/..", headers=headers).status_code
            == 404
        )
        assert (
            client.get(
                "/internal/replica/archives/..%5Csecret.zip", headers=headers
            ).status_code
            == 404
        )
        assert (
            client.get("/internal/replica/archives/missing.zip", headers=headers).status_code
            == 404
        )

        promoted = client.post("/internal/replica/promote", headers=headers)
        assert promoted.status_code == 200
        results = promoted.json()["results"]
        assert len(results) == 4
        catalog = next(item for item in results if item["store"] == "catalog")
        assert catalog["promoted"] is True
        assert db_values(settings.live_db_path("catalog")) == ["before"]
        backup = settings.live_db_path("catalog").with_name("catalog.db.bak")
        assert db_values(backup) == ["before", "after-snapshot"]


def test_sync_endpoint_pulls_from_explicit_peer(
    settings_factory: Callable[..., ReplicaSettings],
) -> None:
    source_settings = settings_factory()
    destination_settings = settings_factory()
    source = asyncio.run(prepare_source(source_settings))
    routes = asyncio.run(build_replica_routes(source))
    headers = {"X-Internal-Token": destination_settings.internal_token}

    with (
        serve(routes, token=destination_settings.internal_token) as (base, state),
        _client(destination_settings) as client,
    ):
        response = client.post(
            "/internal/replica/sync",
            headers=headers,
            json={"peers": [base]},
        )
        assert response.status_code == 200
        report = response.json()
        assert report["mode"] == "peers"
        assert report["errors"] == {}
        assert all(item["status"] == "pulled" for item in report["stores"].values())
        assert report["archives"]["pulled"] == 1

        status = client.get("/internal/replica/status", headers=headers).json()
        assert status["stores"]["catalog"]["available"] is True
        assert status["archives"]["count"] == 1

    assert all(token == destination_settings.internal_token for _, token in state.requests)
    assert db_values(destination_settings.snapshot_dir / "catalog.db") == ["catalog-row"]


def test_bootstrap_endpoint_promotes_with_one_call(
    settings_factory: Callable[..., ReplicaSettings],
) -> None:
    source_settings = settings_factory()
    destination_settings = settings_factory()
    source = asyncio.run(prepare_source(source_settings))
    asyncio.run(prepare_destination(destination_settings))
    routes = asyncio.run(build_replica_routes(source))
    headers = {"X-Internal-Token": destination_settings.internal_token}

    with (
        serve(routes, token=destination_settings.internal_token) as (base, _),
        _client(destination_settings) as client,
    ):
        response = client.post(
            "/internal/replica/bootstrap",
            headers=headers,
            json={"source": base, "promote": True},
        )
        assert response.status_code == 200
        report = response.json()
        assert report["source"] == base
        assert report["errors"] == {}
        assert len(report["promoted"]) == 4
        assert all(item["promoted"] for item in report["promoted"])
        assert report["archives_copied"] == 1

    assert db_values(destination_settings.live_db_path("catalog")) == ["catalog-row"]
    assert db_values(destination_settings.live_db_path("media")) == ["media-row"]
    assert (destination_settings.media_archive_path / "chapter-1.zip").is_file()
    assert destination_settings.live_db_path("catalog").with_name("catalog.db.bak").is_file()
