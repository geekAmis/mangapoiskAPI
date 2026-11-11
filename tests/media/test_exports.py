from __future__ import annotations

import asyncio
import uuid
import zipfile
from pathlib import Path

import pytest
from PIL import Image
from services.media.app.cache import MediaFile
from services.media.app.exporter import ExportManager, ExportPage, ExportRequest


class FakeCache:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.files: dict[str, Path] = {}
        for index, color in enumerate([(30, 40, 60), (90, 30, 40), (200, 180, 40)], start=1):
            path = self.root / f"{index}.jpg"
            Image.new("RGB", (120, 180), color).save(path, "JPEG")
            self.files[f"https://example.com/{index}.jpg"] = path

    async def get(self, url: str, *, referer: str | None = None) -> MediaFile:
        path = self.files[url]
        return MediaFile(path=path, content_type="image/jpeg", size=path.stat().st_size, etag="x")


async def _wait(manager: ExportManager, job_id: uuid.UUID):  # type: ignore[no-untyped-def]
    for _ in range(100):
        job = await manager.get(job_id)
        if job.status in {"done", "failed"}:
            return job
        await asyncio.sleep(0.05)
    raise AssertionError("export did not finish")


@pytest.mark.asyncio
async def test_exports_cbz_pdf_html(tmp_path: Path) -> None:
    cache = FakeCache(tmp_path / "cache")
    manager = ExportManager(cache, tmp_path / "exports", max_pages=300, ttl_hours=1)
    pages = [
        ExportPage(number=index, url=f"https://example.com/{index}.jpg") for index in range(1, 4)
    ]

    cbz = await manager.create(
        ExportRequest(
            chapter_id=uuid.uuid4(),
            manga_title="Тестовая манга",
            chapter_label="Глава 1",
            format="cbz",
            pages=pages,
        )
    )
    cbz_job = await _wait(manager, cbz.id)
    assert cbz_job.status == "done", cbz_job.error
    path, filename = await manager.download(cbz.id)
    assert filename.endswith(".cbz")
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        assert "ComicInfo.xml" in names
        assert len([name for name in names if name.endswith(".jpg")]) == 3

    pdf = await manager.create(
        ExportRequest(
            chapter_id=uuid.uuid4(),
            manga_title="Тестовая манга",
            chapter_label="Глава 2",
            format="pdf",
            pages=pages,
        )
    )
    pdf_job = await _wait(manager, pdf.id)
    assert pdf_job.status == "done", pdf_job.error
    path, filename = await manager.download(pdf.id)
    assert filename.endswith(".pdf")
    assert path.read_bytes().startswith(b"%PDF")

    html = await manager.create(
        ExportRequest(
            chapter_id=uuid.uuid4(),
            manga_title="Тестовая манга",
            chapter_label="Глава 3",
            format="html",
            pages=pages,
        )
    )
    html_job = await _wait(manager, html.id)
    assert html_job.status == "done", html_job.error
    path, filename = await manager.download(html.id)
    assert filename.endswith(".zip")
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        assert "index.html" in names
        assert len([name for name in names if name.startswith("images/")]) == 3

    await manager.close()
