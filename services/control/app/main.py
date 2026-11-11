from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from manga_common.db import create_all, create_engine, create_session_factory, ping
from manga_common.service import add_ready_check, create_service_app
from sqlalchemy import update

from .api import router
from .config import ControlSettings
from .models import DeploymentJob
from .service import ControlService

logger = logging.getLogger(__name__)
settings = ControlSettings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = create_engine(settings.control_dsn, echo=settings.debug)
    session_factory = create_session_factory(engine)
    await create_all(engine)
    async with session_factory() as session:
        stale = await session.execute(
            update(DeploymentJob)
            .where(DeploymentJob.status == "running")
            .values(
                status="failed",
                error="Control перезапущен во время развёртывания. Проверьте сервисы вручную.",
            )
        )
        if stale.rowcount:
            logger.warning("marked %s stale deployment jobs as failed", stale.rowcount)
        await session.commit()
    service = ControlService(settings, session_factory)
    app.state.engine = engine
    app.state.service = service

    async def db_ready() -> bool:
        return await ping(engine)

    add_ready_check(app, "database", db_ready)

    async def monitor() -> None:
        while True:
            try:
                await service.health_check_all()
            except Exception:
                logger.warning("server health check failed", exc_info=True)
            await asyncio.sleep(settings.server_health_interval_seconds)

    task = asyncio.create_task(monitor())
    logger.info("control service ready")
    try:
        yield
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await service.deployer.close()
        await engine.dispose()


app = create_service_app(
    settings=settings,
    title="MangaPoisk Reborn — Control",
    description="Server inventory, SSH deployment and failover registry.",
)
app.router.lifespan_context = lifespan
app.include_router(router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=settings.host, port=settings.port)
