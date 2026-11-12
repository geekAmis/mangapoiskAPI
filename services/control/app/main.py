from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from manga_common.db import create_all, create_engine, create_session_factory, ping
from manga_common.service import add_ready_check, create_service_app
from sqlalchemy import text, update

from .ads import AdsService
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
    async with engine.begin() as conn:
        if engine.dialect.name == "sqlite":
            rows = await conn.execute(text("PRAGMA table_info(servers)"))
            columns = {row[1] for row in rows}
            if "priority" not in columns:
                await conn.execute(
                    text("ALTER TABLE servers ADD COLUMN priority INTEGER NOT NULL DEFAULT 100")
                )
            job_rows = await conn.execute(text("PRAGMA table_info(deployment_jobs)"))
            job_columns = {row[1] for row in job_rows}
            if "last_output_at" not in job_columns:
                await conn.execute(
                    text("ALTER TABLE deployment_jobs ADD COLUMN last_output_at DATETIME")
                )
        else:
            await conn.execute(
                text("ALTER TABLE servers ADD COLUMN IF NOT EXISTS priority INTEGER NOT NULL DEFAULT 100")
            )
            await conn.execute(
                text(
                    "ALTER TABLE deployment_jobs ADD COLUMN IF NOT EXISTS "
                    "last_output_at TIMESTAMP WITH TIME ZONE"
                )
            )
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
    app.state.ads = AdsService(settings, session_factory, box=service.box)

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

    async def reap_stale() -> None:
        while True:
            try:
                await service.reap_stale_jobs()
            except Exception:
                logger.warning("stale deploy job cleanup failed", exc_info=True)
            await asyncio.sleep(60)

    stale_task = asyncio.create_task(reap_stale())
    logger.info("control service ready")
    try:
        yield
    finally:
        task.cancel()
        stale_task.cancel()
        await asyncio.gather(task, stale_task, return_exceptions=True)
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
