"""Test helpers for the replica service."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import zipfile
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from services.replica.app.config import STORE_NAMES, ReplicaSettings
from services.replica.app.store import SnapshotStore

TABLE = "items"


def create_db(path: Path, values: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(f"CREATE TABLE {TABLE} (value TEXT NOT NULL)")
        connection.executemany(
            f"INSERT INTO {TABLE} (value) VALUES (?)", [(value,) for value in values]
        )
        connection.commit()


def append_db(path: Path, values: list[str]) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.executemany(
            f"INSERT INTO {TABLE} (value) VALUES (?)", [(value,) for value in values]
        )
        connection.commit()


def db_values(path: Path) -> list[str]:
    with closing(sqlite3.connect(path)) as connection:
        rows = connection.execute(f"SELECT value FROM {TABLE} ORDER BY rowid").fetchall()
    return [str(row[0]) for row in rows]


def make_zip(path: Path, content: bytes = b"page-data") -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("001.jpg", content)
    path.write_bytes(buffer.getvalue())
    return buffer.getvalue()


@dataclass(slots=True)
class StubResponse:
    body: bytes = b""
    status: int = 200
    headers: dict[str, str] = field(default_factory=dict)

    @classmethod
    def json(cls, payload: Any, status: int = 200) -> StubResponse:
        return cls(
            body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            status=status,
            headers={"Content-Type": "application/json"},
        )


@dataclass(slots=True)
class StubState:
    routes: dict[str, StubResponse]
    token: str | None = None
    requests: list[tuple[str, str | None]] = field(default_factory=list)


@contextmanager
def serve(
    routes: dict[str, StubResponse], *, token: str | None = None
) -> Iterator[tuple[str, StubState]]:
    state = StubState(routes=routes, token=token)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = urlsplit(self.path).path
            supplied = self.headers.get("X-Internal-Token")
            state.requests.append((path, supplied))
            if state.token is not None and supplied != state.token:
                self._send(401, b'{"error":"unauthorized"}', {"Content-Type": "application/json"})
                return
            route = state.routes.get(path)
            if route is None:
                self._send(404, b'{"error":"not found"}', {"Content-Type": "application/json"})
                return
            self._send(route.status, route.body, route.headers)

        def _send(self, status: int, body: bytes, headers: dict[str, str]) -> None:
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


async def build_replica_routes(store: SnapshotStore) -> dict[str, StubResponse]:
    routes: dict[str, StubResponse] = {}
    for store_name in STORE_NAMES:
        meta = await store.meta(store_name)
        if meta is None:
            continue
        body = await asyncio.to_thread(store.snapshot_path(store_name).read_bytes)
        routes[f"/internal/replica/db/{store_name}/meta"] = StubResponse.json(
            meta.model_dump(mode="json")
        )
        routes[f"/internal/replica/db/{store_name}"] = StubResponse(
            body=body,
            headers={
                "Content-Type": "application/octet-stream",
                "X-Checksum": meta.sha256,
                "X-Size": str(meta.size),
                "X-Updated-At": meta.updated_at.isoformat(),
            },
        )

    manifest = await store.archive_manifest()
    routes["/internal/replica/archives"] = StubResponse.json(
        {
            "archives": [entry.model_dump(mode="json") for entry in manifest],
            "count": len(manifest),
            "bytes": sum(entry.size for entry in manifest),
        }
    )
    for entry in manifest:
        path = await store.archive_file(entry.name)
        routes[f"/internal/replica/archives/{entry.name}"] = StubResponse(
            body=await asyncio.to_thread(path.read_bytes),
            headers={"Content-Type": "application/zip"},
        )
    return routes


def registry_payload(replica_url: str, *, server_id: str = "server-primary") -> dict[str, Any]:
    ports = {"catalog": 8002, "library": 8003, "control": 8005, "media": 8004}
    services: dict[str, list[dict[str, Any]]] = {}
    for code, port in ports.items():
        services[code] = [
            {
                "server_id": server_id,
                "server_name": "primary",
                "host": "127.0.0.1",
                "port": port,
                "url": f"http://127.0.0.1:{port}",
                "healthy": True,
                "priority": 1,
                "is_fallback": False,
            }
        ]
    services["replica"] = [
        {
            "server_id": server_id,
            "server_name": "primary",
            "host": "127.0.0.1",
            "port": 8108,
            "url": replica_url,
            "healthy": True,
            "priority": 1,
            "is_fallback": False,
        }
    ]
    return {"services": services}


async def prepare_source(settings: ReplicaSettings) -> SnapshotStore:
    """Create one row in every live database plus a chapter ZIP, then snapshot."""

    store = SnapshotStore(settings)
    await store.startup()
    for store_name in STORE_NAMES:
        create_db(settings.live_db_path(store_name), [f"{store_name}-row"])
    make_zip(settings.media_archive_path / "chapter-1.zip", b"page-one")
    for store_name in STORE_NAMES:
        await store.snapshot(store_name)
    return store


async def prepare_destination(settings: ReplicaSettings) -> SnapshotStore:
    store = SnapshotStore(settings)
    await store.startup()
    for store_name in STORE_NAMES:
        create_db(settings.live_db_path(store_name), [f"old-{store_name}"])
    return store
