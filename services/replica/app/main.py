from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from manga_common.service import add_ready_check, create_service_app

from .api import router
from .config import ReplicaSettings
from .store import SnapshotStore
from .sync import ReplicaSync

logger = logging.getLogger(__name__)


def create_app(settings: ReplicaSettings | None = None) -> FastAPI:
    resolved = settings or ReplicaSettings()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        snapshots = SnapshotStore(resolved)
        await snapshots.startup()
        sync = ReplicaSync(resolved, snapshots)
        application.state.store = snapshots
        application.state.sync = sync

        async def storage_ready() -> bool:
            return await snapshots.ready()

        add_ready_check(application, "storage", storage_ready)
        await sync.startup()
        logger.info(
            "replica service ready self=%s sync_disabled=%s",
            resolved.self_replica_url or "(unset)",
            resolved.sync_disabled,
        )
        try:
            yield
        finally:
            await sync.close()

    application = create_service_app(
        settings=resolved,
        title="MangaPoisk Reborn — Replica",
        description=(
            "Continuous snapshot replication for SQLite databases and chapter archives, "
            "with bootstrap and promotion endpoints."
        ),
    )
    application.router.lifespan_context = lifespan
    application.include_router(router)
    return application


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=app.state.settings.host,
        port=app.state.settings.port,
        reload=app.state.settings.debug,
    )
