from __future__ import annotations

import asyncio
import contextlib
import html
import logging
import shutil
import uuid
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from manga_common.errors import NotFoundError, ValidationError
from manga_common.schemas import ExportJobOut
from manga_common.text import slugify
from pydantic import BaseModel, Field

from .cache import MediaCache

logger = logging.getLogger(__name__)


class ExportPage(BaseModel):
    number: int = Field(ge=1)
    url: str


class ExportRequest(BaseModel):
    chapter_id: uuid.UUID
    manga_title: str = Field(min_length=1, max_length=512)
    chapter_label: str = Field(min_length=1, max_length=256)
    format: Literal["cbz", "pdf", "html"] = "cbz"
    pages: list[ExportPage] = Field(min_length=1)
    referer: str | None = None


class ExportJobState(BaseModel):
    id: uuid.UUID
    status: Literal["queued", "running", "done", "failed"]
    format: str
    chapter_id: uuid.UUID
    progress: int = 0
    total: int = 0
    error: str | None = None
    filename: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def out(self) -> ExportJobOut:
        return ExportJobOut(
            id=self.id,
            status=self.status,
            format=self.format,
            chapter_id=self.chapter_id,
            progress=self.progress,
            total=self.total,
            error=self.error,
            download_url=f"/internal/exports/{self.id}/download" if self.status == "done" else None,
            created_at=self.created_at,
        )


class ExportManager:
    def __init__(self, cache: MediaCache, root: Path, *, max_pages: int, ttl_hours: int) -> None:
        self.cache = cache
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_pages = max_pages
        self.ttl = timedelta(hours=ttl_hours)
        self._jobs: dict[uuid.UUID, ExportJobState] = {}
        self._tasks: set[asyncio.Task] = set()
        self._lock = asyncio.Lock()
        self._load()

    def _job_dir(self, job_id: uuid.UUID) -> Path:
        return self.root / str(job_id)

    def _load(self) -> None:
        for path in self.root.glob("*/job.json"):
            try:
                state = ExportJobState.model_validate_json(path.read_text(encoding="utf-8"))
                if state.status in {"queued", "running"}:
                    state.status = "failed"
                    state.error = "Сервис был перезапущен"
                self._jobs[state.id] = state
            except Exception:
                continue

    async def _save(self, state: ExportJobState) -> None:
        state.updated_at = datetime.now(UTC)
        directory = self._job_dir(state.id)
        directory.mkdir(parents=True, exist_ok=True)
        temp = directory / "job.json.tmp"
        temp.write_text(state.model_dump_json(indent=2), encoding="utf-8")
        temp.replace(directory / "job.json")

    async def create(self, request: ExportRequest) -> ExportJobOut:
        if len(request.pages) > self.max_pages:
            raise ValidationError(
                f"Слишком много страниц для экспорта (максимум {self.max_pages})"
            )
        state = ExportJobState(
            id=uuid.uuid4(),
            status="queued",
            format=request.format,
            chapter_id=request.chapter_id,
            total=len(request.pages),
        )
        async with self._lock:
            self._jobs[state.id] = state
            await self._save(state)
        task = asyncio.create_task(self._run(state.id, request))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return state.out()

    async def _run(self, job_id: uuid.UUID, request: ExportRequest) -> None:
        state = self._jobs[job_id]
        directory = self._job_dir(job_id)
        images_dir = directory / "images"
        images_dir.mkdir(parents=True, exist_ok=True)
        try:
            state.status = "running"
            await self._save(state)
            images: list[Path] = []
            for index, page in enumerate(sorted(request.pages, key=lambda item: item.number), start=1):
                media = await self.cache.get(page.url, referer=request.referer)
                extension = media.path.suffix or ".jpg"
                destination = images_dir / f"{index:04d}{extension}"
                if not destination.exists() or destination.stat().st_size != media.size:
                    shutil.copyfile(media.path, destination)
                images.append(destination)
                state.progress = index
                await self._save(state)

            safe_title = slugify(request.manga_title)[:80]
            safe_chapter = slugify(request.chapter_label)[:60]
            base_name = f"{safe_title}-{safe_chapter}"
            if request.format == "cbz":
                archive = directory / f"{base_name}.cbz"
                await asyncio.to_thread(self._build_cbz, archive, images, request)
            elif request.format == "pdf":
                archive = directory / f"{base_name}.pdf"
                await asyncio.to_thread(self._build_pdf, archive, images)
            else:
                archive = directory / f"{base_name}-html.zip"
                await asyncio.to_thread(self._build_html, archive, images, request)
            state.filename = archive.name
            state.status = "done"
            await self._save(state)
            logger.info("export finished", extra={"job_id": str(job_id), "format": request.format})
        except Exception as exc:
            logger.exception("export failed", extra={"job_id": str(job_id)})
            state.status = "failed"
            state.error = str(exc)[:500]
            await self._save(state)

    def _build_cbz(self, archive: Path, images: list[Path], request: ExportRequest) -> None:
        comic_info = (
            "<?xml version=\"1.0\" encoding=\"utf-8\"?>\n"
            "<ComicInfo xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\">"
            f"<Series>{html.escape(request.manga_title)}</Series>"
            f"<Title>{html.escape(request.chapter_label)}</Title>"
            "<LanguageISO>ru</LanguageISO><Manga>Yes</Manga>"
            "</ComicInfo>"
        )
        # CBZ readers are conservative.  Convert modern formats to JPEG so the
        # archive opens in older Android/iOS/comic-reader software.
        prepared: list[Path] = []
        temp_dir = archive.parent / "cbz-tmp"
        for image in images:
            if image.suffix.lower() not in {".webp", ".avif", ".gif"}:
                prepared.append(image)
                continue
            from PIL import Image

            temp_dir.mkdir(parents=True, exist_ok=True)
            target = temp_dir / f"{image.stem}.jpg"
            with Image.open(image) as source:
                source.convert("RGB").save(target, "JPEG", quality=92)
            prepared.append(target)
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr("ComicInfo.xml", comic_info)
            for index, image in enumerate(prepared, start=1):
                bundle.write(image, f"{index:04d}{image.suffix}")
        shutil.rmtree(temp_dir, ignore_errors=True)

    def _build_pdf(self, archive: Path, images: list[Path]) -> None:
        import img2pdf
        from PIL import Image

        prepared: list[Path] = []
        temp_dir = archive.parent / "pdf-tmp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        for image in images:
            try:
                prepared.append(image)
                with Image.open(image) as probe:
                    probe.verify()
            except Exception:
                with Image.open(image) as source:
                    converted = source.convert("RGB")
                    target = temp_dir / f"{image.stem}.jpg"
                    converted.save(target, "JPEG", quality=92)
                    prepared.append(target)
        with archive.open("wb") as output:
            output.write(img2pdf.convert([str(path) for path in prepared]))
        shutil.rmtree(temp_dir, ignore_errors=True)

    def _build_html(
        self, archive: Path, images: list[Path], request: ExportRequest
    ) -> None:
        title = html.escape(f"{request.manga_title} — {request.chapter_label}")
        image_tags = "\n".join(
            f'      <img src="images/{image.name}" loading="lazy" alt="Страница {index}">'
            for index, image in enumerate(images, start=1)
        )
        document = f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{ color-scheme: dark; }}
    body {{ margin: 0; background: #0b0e14; color: #e8edf6; font-family: system-ui, sans-serif; }}
    header {{ position: sticky; top: 0; padding: 12px 18px; background: rgba(11,14,20,.86);
      backdrop-filter: blur(12px); border-bottom: 1px solid #253044; z-index: 2; }}
    h1 {{ font-size: 16px; margin: 0; font-weight: 600; }}
    main {{ max-width: 920px; margin: 0 auto; padding: 16px; }}
    img {{ display: block; width: 100%; height: auto; margin: 0 auto 8px; background: #111827; }}
    footer {{ padding: 24px; text-align: center; color: #93a4bd; font-size: 13px; }}
  </style>
</head>
<body>
  <header><h1>{title}</h1></header>
  <main>
{image_tags}
  </main>
  <footer>Офлайн-экспорт MangaPoisk Reborn</footer>
</body>
</html>
"""
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr("index.html", document)
            for image in images:
                bundle.write(image, f"images/{image.name}")

    async def get(self, job_id: uuid.UUID) -> ExportJobOut:
        state = self._jobs.get(job_id)
        if state is None:
            raise NotFoundError("Экспорт не найден")
        return state.out()

    async def download(self, job_id: uuid.UUID) -> tuple[Path, str]:
        state = self._jobs.get(job_id)
        if state is None or state.status != "done" or not state.filename:
            raise NotFoundError("Экспорт не готов")
        path = self._job_dir(job_id) / state.filename
        if not path.exists():
            raise NotFoundError("Файл экспорта не найден")
        return path, state.filename

    async def delete(self, job_id: uuid.UUID) -> None:
        state = self._jobs.pop(job_id, None)
        if state is None:
            raise NotFoundError("Экспорт не найден")
        shutil.rmtree(self._job_dir(job_id), ignore_errors=True)

    async def cleanup(self) -> int:
        cutoff = datetime.now(UTC) - self.ttl
        removed = 0
        for directory in self.root.iterdir():
            if not directory.is_dir():
                continue
            job_file = directory / "job.json"
            try:
                modified = datetime.fromtimestamp(job_file.stat().st_mtime, tz=UTC)
            except OSError:
                modified = datetime.fromtimestamp(directory.stat().st_mtime, tz=UTC)
            if modified < cutoff:
                shutil.rmtree(directory, ignore_errors=True)
                removed += 1
                with contextlib.suppress(ValueError):
                    self._jobs.pop(uuid.UUID(directory.name), None)
        return removed

    async def close(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
