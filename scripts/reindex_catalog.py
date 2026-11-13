"""Explicit catalogue search reindex command.

Use this before a deploy when you want the backfill finished before health
checks start.  Normally the catalog starts instantly and the same work runs in
the background, so the command is optional.

Examples:
    .venv/Scripts/python scripts/reindex_catalog.py --database-url "$CATALOG_DATABASE_URL"
    .venv/Scripts/python scripts/reindex_catalog.py --force --rebuild-fts
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os

from manga_common.db import create_engine, create_session_factory
from services.catalog.app.config import CatalogSettings
from services.catalog.app.migrations import ensure_runtime_schema
from services.catalog.app.models import Manga
from services.catalog.app.repository import rebuild_catalog_groups, search_backfill_stats
from services.catalog.app.search_backfill import (
    BackfillConfig,
    SearchBackfillWorker,
    bootstrap_search_index,
)
from services.catalog.app.search_fts import rebuild_search_fts
from sqlalchemy import update


async def run(args: argparse.Namespace) -> int:
    dsn = args.database_url or os.environ.get("CATALOG_DATABASE_URL") or os.environ.get(
        "DATABASE_URL"
    )
    if not dsn:
        print("No database URL. Pass --database-url or set CATALOG_DATABASE_URL.")
        return 2
    settings = CatalogSettings(service_name="catalog-reindex", catalog_database_url=dsn)
    engine = create_engine(settings.catalog_dsn)
    factory = create_session_factory(engine)
    try:
        print("schema: applying additive changes")
        await ensure_runtime_schema(engine)
        if args.rebuild_catalog:
            async with factory() as session:
                count = await rebuild_catalog_groups(session)
                await session.commit()
            print(f"catalog: rebuilt {count} cards")
        if args.force:
            async with factory() as session:
                await session.execute(update(Manga).values(search_indexed=False))
                await session.commit()
            print("force: all rows marked for reindex")
        if args.rebuild_fts:
            async with factory() as session:
                count = await rebuild_search_fts(session)
                await session.commit()
            print(f"fts: rebuilt {count} rows")
        bootstrap = await bootstrap_search_index(factory, batch_size=args.batch_size)
        print("bootstrap:", json.dumps(bootstrap, ensure_ascii=False))
        if bootstrap["pending"] <= 0 and not args.force:
            print("nothing to do")
            return 0

        def progress(payload: dict[str, int]) -> None:
            print("progress:", json.dumps(payload, ensure_ascii=False), flush=True)

        worker = SearchBackfillWorker(
            factory,
            BackfillConfig(
                batch_size=args.batch_size,
                lease_seconds=args.lease_seconds,
                yield_seconds=args.yield_seconds,
            ),
            owner="cli-reindex",
            on_progress=progress,
        )
        await worker.run()
        async with factory() as session:
            state = await search_backfill_stats(session)
            if state is not None:
                print("final:", state.model_dump_json())
                return 0 if state.status == "completed" else 1
    finally:
        await engine.dispose()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--lease-seconds", type=int, default=120)
    parser.add_argument("--yield-seconds", type=float, default=0.01)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Reindex every row, including rows already normalized.",
    )
    parser.add_argument(
        "--rebuild-fts",
        action="store_true",
        help="Rebuild the SQLite FTS mirror before normalizing (SQLite only).",
    )
    parser.add_argument(
        "--rebuild-catalog",
        action="store_true",
        help="Force a rebuild of the materialised catalogue card tables.",
    )
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
