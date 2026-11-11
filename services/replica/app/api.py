from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse
from manga_common.errors import NotFoundError
from manga_common.security import require_internal_token

from .schemas import (
    ArchiveManifest,
    BootstrapRequest,
    BootstrapResponse,
    PromoteRequest,
    PromoteResponse,
    ReplicaStatus,
    SnapshotMeta,
    SyncReport,
    SyncRequest,
)
from .store import SnapshotStore, ensure_store
from .sync import ReplicaSync

router = APIRouter(
    prefix="/internal/replica",
    tags=["replica"],
    dependencies=[Depends(require_internal_token)],
)


def get_store(request: Request) -> SnapshotStore:
    return request.app.state.store


def get_sync(request: Request) -> ReplicaSync:
    return request.app.state.sync


def _checked_store(store: str) -> str:
    try:
        return ensure_store(store)
    except ValueError as exc:
        raise NotFoundError(f"Unknown replica store: {store}") from exc


@router.get("/status", response_model=ReplicaStatus)
async def status(sync: ReplicaSync = Depends(get_sync)) -> ReplicaStatus:
    return await sync.status()


@router.get("/db/{store}")
async def download_db(
    store: str,
    snapshots: SnapshotStore = Depends(get_store),
) -> FileResponse:
    name = _checked_store(store)
    meta = await snapshots.meta(name)
    if meta is None:
        raise NotFoundError(f"No snapshot available for {name}")
    return FileResponse(
        snapshots.snapshot_path(name),
        media_type="application/octet-stream",
        filename=f"{name}.db",
        headers={
            "X-Checksum": meta.sha256,
            "X-Size": str(meta.size),
            "X-Updated-At": meta.updated_at.isoformat(),
            "Cache-Control": "no-store",
        },
    )


@router.get("/db/{store}/meta", response_model=SnapshotMeta)
async def db_meta(
    store: str,
    snapshots: SnapshotStore = Depends(get_store),
) -> SnapshotMeta:
    name = _checked_store(store)
    meta = await snapshots.meta(name)
    if meta is None:
        raise NotFoundError(f"No snapshot available for {name}")
    return meta


@router.post("/sync", response_model=SyncReport)
async def sync_peer(
    payload: SyncRequest | None = None,
    sync: ReplicaSync = Depends(get_sync),
) -> SyncReport:
    request = payload or SyncRequest()
    return await sync.sync(peers=request.peers, stores=request.stores)


@router.post("/bootstrap", response_model=BootstrapResponse)
async def bootstrap(
    payload: BootstrapRequest,
    sync: ReplicaSync = Depends(get_sync),
) -> BootstrapResponse:
    return await sync.bootstrap(
        payload.source,
        stores=payload.stores,
        promote=payload.promote,
    )


@router.post("/promote", response_model=PromoteResponse)
async def promote(
    payload: PromoteRequest | None = None,
    sync: ReplicaSync = Depends(get_sync),
) -> PromoteResponse:
    request = payload or PromoteRequest()
    return await sync.promote(stores=request.stores)


@router.get("/archives", response_model=ArchiveManifest)
async def archives(snapshots: SnapshotStore = Depends(get_store)) -> ArchiveManifest:
    entries = await snapshots.archive_manifest()
    return ArchiveManifest(
        archives=entries,
        count=len(entries),
        bytes=sum(item.size for item in entries),
    )


@router.get("/archives/{name}")
async def download_archive(
    name: str,
    snapshots: SnapshotStore = Depends(get_store),
) -> FileResponse:
    try:
        path = await snapshots.archive_file(name)
    except (ValueError, FileNotFoundError) as exc:
        raise NotFoundError(f"Archive not found: {name}") from exc
    return FileResponse(
        path,
        media_type="application/zip",
        filename=name,
        headers={"Cache-Control": "no-store"},
    )
