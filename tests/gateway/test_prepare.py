from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from manga_common.schemas import ChapterOut
from services.gateway.app import api


def _chapter(number: int) -> ChapterOut:
    now = datetime.now(UTC)
    return ChapterOut(
        id=uuid.uuid4(),
        manga_id=uuid.uuid4(),
        source="test-source",
        source_id=str(number),
        number=str(number),
        title=f"Глава {number}",
        page_count=3,
        created_at=now,
        updated_at=now,
    )


def _summary(chapter: ChapterOut, status: str, **extra: object) -> dict[str, object]:
    return {
        "chapter_id": str(chapter.id),
        "status": status,
        "page_count": 3 if status == "done" else 0,
        "total_bytes": 120 if status == "done" else 0,
        "error": None,
        **extra,
    }


def test_prepare_status_counts_and_batch() -> None:
    chapters = [_chapter(index) for index in range(1, 8)]
    summary = {
        str(chapters[0].id): _summary(chapters[0], "done"),
        str(chapters[1].id): _summary(chapters[1], "done"),
        str(chapters[2].id): _summary(chapters[2], "done"),
        str(chapters[3].id): _summary(chapters[3], "done"),
        str(chapters[4].id): _summary(chapters[4], "done"),
        str(chapters[5].id): _summary(chapters[5], "error", error="Источник недоступен"),
        # The last chapter is missing from the archive database.
    }

    result = api._build_prepare_status(
        "manga-1",
        chapters,
        summary,
        active=False,
        job_id="job-1",
    )

    assert result.total == 7
    assert result.prepared == 5
    assert result.failed == 2
    assert result.pending == 0
    assert result.batch == [str(chapter.id) for chapter in chapters[:5]]
    statuses = {item.id: item.status for item in result.chapters}
    assert statuses[str(chapters[5].id)] == "error"
    assert statuses[str(chapters[6].id)] == "error"
    assert result.chapters[5].error == "Источник недоступен"
    assert result.job_id == "job-1"


def test_prepare_status_treats_unreached_chapters_as_pending_while_active() -> None:
    chapters = [_chapter(index) for index in range(1, 3)]
    summary = {str(chapters[0].id): _summary(chapters[0], "done")}

    result = api._build_prepare_status("manga-2", chapters, summary, active=True)

    assert result.prepared == 1
    assert result.pending == 1
    assert result.failed == 0
    assert result.batch == [str(chapters[0].id)]


def test_prepare_status_surfaces_worker_errors() -> None:
    chapter = _chapter(1)
    result = api._build_prepare_status(
        "manga-3",
        [chapter],
        {},
        active=False,
        job_errors={str(chapter.id): "Источник не отдал страницы главы"},
    )

    assert result.failed == 1
    assert result.chapters[0].status == "error"
    assert result.chapters[0].error == "Источник не отдал страницы главы"


async def test_prepare_registry_dedupes_concurrent_jobs() -> None:
    registry = api._PrepareRegistry()
    started = asyncio.Event()
    release = asyncio.Event()

    async def runner(_job: api._PrepareJob) -> None:
        started.set()
        await release.wait()

    first, first_created = registry.start("manga-1", ["a", "b"], runner)
    second, second_created = registry.start("manga-1", ["a", "b"], runner)
    await started.wait()

    assert first_created is True
    assert second_created is False
    assert first.job_id == second.job_id
    assert registry.active("manga-1") is first

    release.set()
    await first.task
    await asyncio.sleep(0)
    assert registry.active("manga-1") is None

    third, third_created = registry.start("manga-1", ["a"], runner)
    assert third_created is True
    assert third.job_id != first.job_id
    await third.task
