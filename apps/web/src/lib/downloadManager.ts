/**
 * Менеджер офлайн-загрузок на устройство.
 *
 * Очередь одна на приложение: изображения качаются строго последовательно.
 * Для полного тайтла между изображениями выдерживается пауза
 * 2000 + Math.random() * 2890 мс (2,0–4,89 с). Для одной главы — 150–400 мс.
 *
 * Прогресс и очередь сохраняются после каждого изображения. При следующем
 * запуске приложения незавершённые задания снова становятся в очередь,
 * уже скачанные страницы/главы пропускаются.
 */

import { useSyncExternalStore } from 'react';
import { api, resolveApiUrl } from '../api/client';
import type { ChapterOut, MangaDetailOut, PageOut } from '../api/types';
import {
  deleteOfflineTitle,
  getOfflinePageInfo,
  getOfflineTitle,
  isChapterFullyDownloaded,
  offlinePagePath,
  readDownloadQueue,
  saveOfflinePage,
  saveOfflineTitle,
  writeDownloadQueue,
} from './offlineStorage';
import {
  isActiveJob,
  sortOfflineChapters,
  type DownloadJob,
  type DownloadJobChapter,
  type DownloadJobMode,
  type DownloadJobStatus,
  type OfflineMangaMeta,
  type OfflinePage,
  type OfflineTitle,
} from './offlineTypes';

export const WHOLE_TITLE_MIN_DELAY_MS = 2000;
export const WHOLE_TITLE_MAX_EXTRA_DELAY_MS = 2890;
export const SINGLE_CHAPTER_MIN_DELAY_MS = 150;
export const SINGLE_CHAPTER_MAX_EXTRA_DELAY_MS = 250;

/** Задержка между двумя изображениями очереди «весь тайтл». */
export function wholeTitleImageDelay(): number {
  return WHOLE_TITLE_MIN_DELAY_MS + Math.random() * WHOLE_TITLE_MAX_EXTRA_DELAY_MS;
}

/** Задержка между изображениями одиночной главы. */
export function singleChapterImageDelay(): number {
  return SINGLE_CHAPTER_MIN_DELAY_MS + Math.random() * SINGLE_CHAPTER_MAX_EXTRA_DELAY_MS;
}

export interface StartTitleDownloadInput {
  manga: MangaDetailOut;
  chapters: ChapterOut[];
  /** id выбранного варианта источника (может отличаться от manga.id). */
  mangaId?: string;
  title?: string;
  poster?: string | null;
  source?: string;
}

export interface StartChapterDownloadInput {
  manga: MangaDetailOut;
  chapter: ChapterOut;
  mangaId?: string;
  title?: string;
  poster?: string | null;
  source?: string;
}

function nowIso(): string {
  return new Date().toISOString();
}

function errorMessage(error: unknown): string {
  if (error instanceof Error && error.message) return error.message;
  return 'Не удалось скачать изображение';
}

function guessContentType(url: string): string {
  const clean = url.split('?')[0]?.toLowerCase() ?? '';
  if (clean.endsWith('.png')) return 'image/png';
  if (clean.endsWith('.webp')) return 'image/webp';
  if (clean.endsWith('.gif')) return 'image/gif';
  if (clean.endsWith('.avif')) return 'image/avif';
  return 'image/jpeg';
}

function metaFromManga(
  manga: MangaDetailOut,
  overrides: { mangaId?: string; title?: string; poster?: string | null; source?: string },
): OfflineMangaMeta {
  return {
    id: overrides.mangaId ?? manga.id,
    source: overrides.source ?? manga.source,
    title: overrides.title ?? manga.title,
    titleEn: manga.title_en,
    titleAlt: manga.title_alt,
    poster: overrides.poster !== undefined ? overrides.poster : manga.poster_url,
    description: manga.description,
    year: manga.year,
    status: manga.status,
    contentType: manga.content_type,
    rating: manga.rating,
    ratingCount: manga.rating_count,
    genres: Array.isArray(manga.genres) ? [...manga.genres] : [],
    adult: Boolean(manga.adult),
    lastChapterAt: manga.last_chapter_at,
  };
}

function toJobChapter(chapter: ChapterOut): DownloadJobChapter {
  return {
    id: chapter.id,
    number: chapter.number,
    volume: chapter.volume,
    title: chapter.title,
    translator: chapter.translator?.trim() || null,
    pageCount: chapter.page_count || 0,
    status: 'pending',
    error: null,
  };
}

function cloneJobs(jobs: DownloadJob[]): DownloadJob[] {
  return jobs.map((job) => ({
    ...job,
    meta: { ...job.meta, genres: [...job.meta.genres] },
    chapters: job.chapters.map((chapter) => ({ ...chapter })),
  }));
}

/* ------------------------------------------------------------------ */
/* Состояние и подписки                                                */
/* ------------------------------------------------------------------ */

let jobs: DownloadJob[] = [];
let initPromise: Promise<void> | null = null;
let workerRunning = false;
let workerWakeRequested = false;
let persistChain: Promise<void> = Promise.resolve();
/** Следующий разрешённый старт изображения (общий для всех заданий режима). */
let nextWholeImageAt = 0;
let nextSingleImageAt = 0;
const jobListeners = new Set<() => void>();

function notifyJobs(): void {
  for (const listener of jobListeners) listener();
}

function subscribeJobs(listener: () => void): () => void {
  jobListeners.add(listener);
  return () => jobListeners.delete(listener);
}

export function getDownloadJobs(): DownloadJob[] {
  return jobs;
}

export function useDownloadJobs(): DownloadJob[] {
  return useSyncExternalStore(subscribeJobs, getDownloadJobs, getDownloadJobs);
}

export function getActiveDownloadJob(mangaId: string): DownloadJob | null {
  return (
    jobs.find(
      (job) =>
        job.mangaId === mangaId &&
        (job.status === 'running' || job.status === 'queued' || job.status === 'error'),
    ) ?? null
  );
}

function replaceJob(next: DownloadJob): void {
  jobs = jobs.map((job) => (job.id === next.id ? next : job));
  notifyJobs();
}

function patchJob(jobId: string, patch: Partial<DownloadJob>): DownloadJob | null {
  const current = jobs.find((job) => job.id === jobId);
  if (!current) return null;
  const next: DownloadJob = { ...current, ...patch, updatedAt: nowIso() };
  replaceJob(next);
  return next;
}

function persistJobs(): Promise<void> {
  const snapshot = cloneJobs(jobs);
  persistChain = persistChain
    .catch(() => undefined)
    .then(() => writeDownloadQueue(snapshot))
    .catch(() => undefined);
  return persistChain;
}

async function persistAndNotify(): Promise<void> {
  notifyJobs();
  await persistJobs();
}

/* ------------------------------------------------------------------ */
/* Инициализация и восстановление очереди                              */
/* ------------------------------------------------------------------ */

export function initDownloadManager(): Promise<void> {
  if (initPromise) return initPromise;
  initPromise = (async () => {
    let stored: DownloadJob[] = [];
    try {
      const raw = await readDownloadQueue<unknown>();
      if (Array.isArray(raw)) {
        stored = raw.filter(isStoredJob);
      }
    } catch {
      stored = [];
    }

    // Завершённые и отменённые задания не нужны после перезапуска: манифест
    // уже содержит скачанные главы, а прогресс завершённого задания не показан.
    const kept = stored.filter((job) => job.status !== 'done' && job.status !== 'cancelled');
    const pruned = stored.filter((job) => job.status === 'done' || job.status === 'cancelled');
    jobs = kept.map((job) => ({
      ...job,
      status: job.status === 'running' ? 'queued' : job.status,
      currentChapterId: null,
      currentPage: null,
      chapters: job.chapters.map((chapter) =>
        chapter.status === 'downloading' ? { ...chapter, status: 'pending' } : chapter,
      ),
    }));
    await persistAndNotify();

    // Отмена до конца первой главы оставляла пустой манифест. Убираем такие
    // записи и недокачанные файлы, чтобы в «Скачано» не было пустых карточек.
    const emptyCandidates = new Set(
      pruned.filter((job) => job.mode === 'title').map((job) => job.mangaId),
    );
    for (const mangaId of emptyCandidates) {
      try {
        const title = await getOfflineTitle(mangaId);
        if (title && title.chapters.length === 0) await deleteOfflineTitle(mangaId);
      } catch {
        // Чистка не должна мешать запуску очереди.
      }
    }
    if (jobs.some((job) => job.status === 'queued')) void pumpQueue();
  })().catch((error: unknown) => {
    initPromise = null;
    throw error;
  });
  return initPromise;
}

function isStoredJob(value: unknown): value is DownloadJob {
  if (typeof value !== 'object' || value === null) return false;
  const record = value as Record<string, unknown>;
  return (
    typeof record.id === 'string' &&
    typeof record.mangaId === 'string' &&
    Array.isArray(record.chapters) &&
    typeof record.meta === 'object' &&
    record.meta !== null
  );
}

/* ------------------------------------------------------------------ */
/* Публичное API                                                       */
/* ------------------------------------------------------------------ */

export async function startTitleDownload(input: StartTitleDownloadInput): Promise<DownloadJob | null> {
  await initDownloadManager();
  const meta = metaFromManga(input.manga, input);
  const chapters = sortOfflineChapters(
    input.chapters.filter((chapter) => !chapter.is_external),
  );

  const active = jobs.find(
    (job) => job.id === meta.id && job.mode === 'title' && isActiveJob(job),
  );
  if (active) {
    // Добавляем главы, которых ещё нет в активной очереди (например, после обновления).
    const known = new Set(active.chapters.map((chapter) => chapter.id));
    const additions = chapters.filter((chapter) => !known.has(chapter.id)).map(toJobChapter);
    if (additions.length > 0) {
      const next = patchJob(active.id, {
        chapters: [...active.chapters, ...additions],
        totalPages:
          active.totalPages + additions.reduce((sum, chapter) => sum + chapter.pageCount, 0),
      });
      if (next) await persistAndNotify();
    }
    void pumpQueue();
    return active;
  }

  const downloaded = await Promise.all(
    chapters.map((chapter) =>
      isChapterFullyDownloaded(meta.id, chapter.id, chapter.page_count || undefined),
    ),
  );
  const pending = chapters.filter((_, index) => !downloaded[index]);
  if (pending.length === 0) return null;

  await ensureTitleManifest(meta);

  const job: DownloadJob = {
    id: meta.id,
    mangaId: meta.id,
    mode: 'title',
    meta,
    chapters: pending.map(toJobChapter),
    status: 'queued',
    createdAt: nowIso(),
    updatedAt: nowIso(),
    totalPages: pending.reduce((sum, chapter) => sum + (chapter.page_count || 0), 0),
    downloadedPages: 0,
    completedChapters: 0,
    currentChapterId: null,
    currentPage: null,
    error: null,
  };

  jobs = [...jobs.filter((item) => item.id !== job.id), job];
  await persistAndNotify();
  void pumpQueue();
  return job;
}

export async function startChapterDownload(
  input: StartChapterDownloadInput,
): Promise<DownloadJob | null> {
  await initDownloadManager();
  const meta = metaFromManga(input.manga, input);
  if (input.chapter.is_external) return null;

  const already = await isChapterFullyDownloaded(
    meta.id,
    input.chapter.id,
    input.chapter.page_count || undefined,
  );
  if (already) return null;

  const jobId = `${meta.id}::chapter::${input.chapter.id}`;
  const active = jobs.find((job) => job.id === jobId && isActiveJob(job));
  if (active) {
    void pumpQueue();
    return active;
  }

  await ensureTitleManifest(meta);

  const job: DownloadJob = {
    id: jobId,
    mangaId: meta.id,
    mode: 'chapter',
    meta,
    chapters: [toJobChapter(input.chapter)],
    status: 'queued',
    createdAt: nowIso(),
    updatedAt: nowIso(),
    totalPages: input.chapter.page_count || 0,
    downloadedPages: 0,
    completedChapters: 0,
    currentChapterId: null,
    currentPage: null,
    error: null,
  };
  jobs = [...jobs.filter((item) => item.id !== job.id), job];
  await persistAndNotify();
  void pumpQueue();
  return job;
}

export async function cancelDownload(jobId: string): Promise<void> {
  await initDownloadManager();
  const job = jobs.find((item) => item.id === jobId);
  if (!job || (!isActiveJob(job) && job.status !== 'error')) return;
  const cancelled = patchJob(jobId, {
    status: 'cancelled',
    currentChapterId: null,
    currentPage: null,
    error: null,
    chapters: job.chapters.map((chapter) =>
      chapter.status === 'downloading' ? { ...chapter, status: 'pending' } : chapter,
    ),
  });
  await persistAndNotify();

  // Если ни одна глава ещё не была завершена, манифест пуст: удаляем его
  // вместе с частично скачанными страницами.
  if (cancelled) {
    try {
      const title = await getOfflineTitle(cancelled.mangaId);
      if (title && title.chapters.length === 0) await deleteOfflineTitle(cancelled.mangaId);
    } catch {
      // Не мешаем отмене из-за ошибки очистки.
    }
  }
}

export async function retryDownload(jobId: string): Promise<void> {
  await initDownloadManager();
  const job = jobs.find((item) => item.id === jobId);
  if (!job) return;
  patchJob(jobId, {
    status: 'queued',
    error: null,
    currentChapterId: null,
    currentPage: null,
    chapters: job.chapters.map((chapter) => ({
      ...chapter,
      status: chapter.status === 'done' ? 'done' : 'pending',
      error: null,
    })),
  });
  await persistAndNotify();
  void pumpQueue();
}

export async function removeDownloadJob(jobId: string): Promise<void> {
  jobs = jobs.filter((job) => job.id !== jobId);
  await persistAndNotify();
}

/* ------------------------------------------------------------------ */
/* Манифест                                                            */
/* ------------------------------------------------------------------ */

async function ensureTitleManifest(meta: OfflineMangaMeta): Promise<OfflineTitle> {
  const existing = await getOfflineTitle(meta.id);
  if (existing) {
    const merged: OfflineTitle = {
      ...existing,
      ...meta,
      downloadedAt: existing.downloadedAt,
      updatedAt: nowIso(),
    };
    // Метаданные могли обновиться вместе с тайтлом — сохраняем их для карточки.
    await saveOfflineTitle(merged);
    return merged;
  }

  const now = nowIso();
  const title: OfflineTitle = {
    ...meta,
    chapters: [],
    downloadedAt: now,
    updatedAt: now,
  };
  await saveOfflineTitle(title);
  return title;
}

function manifestPagesForChapters(manifest: OfflineTitle | null, chapterIds: Set<string>): number {
  if (!manifest) return 0;
  return manifest.chapters.reduce(
    (sum, chapter) => (chapterIds.has(chapter.id) ? sum + chapter.pages.length : sum),
    0,
  );
}

function manifestPageFromExisting(
  page: PageOut,
  path: string,
  info: { size: number; contentType: string | null },
): OfflinePage {
  return {
    number: page.number,
    path,
    width: page.width ?? null,
    height: page.height ?? null,
    contentType: info.contentType || guessContentType(page.url),
    size: info.size,
  };
}

/* ------------------------------------------------------------------ */
/* Worker                                                              */
/* ------------------------------------------------------------------ */

export function pumpQueue(): Promise<void> {
  workerWakeRequested = true;
  if (workerRunning) return Promise.resolve();
  workerRunning = true;
  const run = async () => {
    try {
      await initDownloadManager();
      let job = nextQueuedJob();
      while (job) {
        workerWakeRequested = false;
        await processJob(job.id);
        job = nextQueuedJob();
      }
    } finally {
      workerRunning = false;
      if (workerWakeRequested || nextQueuedJob()) void pumpQueue();
    }
  };
  return run();
}

function nextQueuedJob(): DownloadJob | null {
  return jobs.find((job) => job.status === 'queued') ?? null;
}

function isCancelled(jobId: string): boolean {
  return jobs.find((job) => job.id === jobId)?.status === 'cancelled';
}

function currentJob(jobId: string): DownloadJob | null {
  return jobs.find((job) => job.id === jobId) ?? null;
}

async function processJob(jobId: string): Promise<void> {
  const started = currentJob(jobId);
  if (!started || started.status !== 'queued') return;

  const manifest = await ensureTitleManifest(started.meta);
  const jobChapterIds = new Set(started.chapters.map((chapter) => chapter.id));
  const chapterDoneIds = new Set(manifest.chapters.map((chapter) => chapter.id));

  const chapters: DownloadJobChapter[] = started.chapters.map((chapter) => {
    if (chapterDoneIds.has(chapter.id)) {
      return { ...chapter, status: 'done', error: null };
    }
    return {
      ...chapter,
      status: chapter.status === 'error' ? 'pending' : chapter.status,
      error: null,
    };
  });
  const completedChapters = chapters.filter((chapter) => chapter.status === 'done').length;
  const totalPages = chapters.reduce((sum, chapter) => sum + (chapter.pageCount || 0), 0);

  patchJob(jobId, {
    status: 'running',
    chapters,
    completedChapters,
    downloadedPages: manifestPagesForChapters(manifest, jobChapterIds),
    totalPages,
    error: null,
    currentChapterId: null,
    currentPage: null,
  });
  await persistAndNotify();

  for (let chapterIndex = 0; chapterIndex < chapters.length; chapterIndex += 1) {
    if (isCancelled(jobId)) return;
    const chapterRef = chapters[chapterIndex];
    if (!chapterRef || chapterRef.status === 'done') continue;

    patchJob(jobId, {
      currentChapterId: chapterRef.id,
      currentPage: 0,
      chapters: chapters.map((chapter) =>
        chapter.id === chapterRef.id
          ? { ...chapter, status: 'downloading', error: null }
          : chapter,
      ),
    });
    await persistAndNotify();

    try {
      const detail = await api.getChapter(chapterRef.id);
      if (isCancelled(jobId)) return;
      const pages = [...detail.pages].sort((a, b) => a.number - b.number);
      if (pages.length === 0) {
        throw new Error('Источник не отдал страницы главы');
      }

      chapterRef.pageCount = pages.length;
      chapterRef.title = detail.title || chapterRef.title;
      chapterRef.translator = detail.translator?.trim() || chapterRef.translator;
      const nextTotalPages = chapters.reduce((sum, chapter) => sum + (chapter.pageCount || 0), 0);
      patchJob(jobId, {
        totalPages: nextTotalPages,
        chapters: chapters.map((chapter) => ({ ...chapter })),
      });
      await persistAndNotify();

      const already = await isChapterFullyDownloaded(started.mangaId, chapterRef.id, pages.length);
      if (already) {
        chapterRef.status = 'done';
        const refreshed = await getOfflineTitle(started.mangaId);
        patchJob(jobId, {
          completedChapters: chapters.filter((chapter) => chapter.status === 'done').length,
          downloadedPages: manifestPagesForChapters(refreshed, jobChapterIds),
          chapters: chapters.map((chapter) => ({ ...chapter })),
        });
        await persistAndNotify();
        continue;
      }

      const downloadedPages: OfflinePage[] = [];
      for (let pageIndex = 0; pageIndex < pages.length; pageIndex += 1) {
        if (isCancelled(jobId)) return;
        const page = pages[pageIndex];
        if (!page) continue;
        const path = offlinePagePath(started.mangaId, chapterRef.id, page.number);
        const existing = await getOfflinePageInfo(path);

        let offlinePage: OfflinePage;
        let downloadedNow = false;
        if (existing.exists && existing.size > 0) {
          offlinePage = manifestPageFromExisting(page, path, existing);
        } else {
          // Единый темп на всё приложение: одно изображение за интервал.
          await waitForImageSlot(started.mode);
          if (isCancelled(jobId)) return;
          const delay =
            started.mode === 'title' ? wholeTitleImageDelay() : singleChapterImageDelay();
          // Отсчитываем интервал от фактического старта запроса, чтобы служебные
          // операции не растягивали паузу сверх заданного диапазона.
          const requestStartedAt = Date.now();
          const responsePromise = fetch(resolveApiUrl(page.url), { credentials: 'same-origin' });
          if (started.mode === 'title') nextWholeImageAt = requestStartedAt + delay;
          else nextSingleImageAt = requestStartedAt + delay;

          const response = await responsePromise;
          if (!response.ok) {
            throw new Error(`Сервер вернул ${response.status} для страницы ${page.number}`);
          }
          const blob = await response.blob();
          if (isCancelled(jobId)) return;
          const contentType =
            response.headers.get('content-type')?.split(';')[0]?.trim() ||
            blob.type ||
            guessContentType(page.url);
          offlinePage = await saveOfflinePage({
            mangaId: started.mangaId,
            chapterId: chapterRef.id,
            number: page.number,
            width: page.width,
            height: page.height,
            blob,
            contentType,
          });
          downloadedNow = true;
        }

        downloadedPages.push(offlinePage);
        if (downloadedNow) {
          const job = currentJob(jobId);
          const nextDownloaded = (job?.downloadedPages ?? 0) + 1;
          patchJob(jobId, { downloadedPages: nextDownloaded, currentPage: pageIndex + 1 });
          await persistAndNotify();
        }

        if (isCancelled(jobId)) return;
      }

      if (isCancelled(jobId)) return;

      const latest = await getOfflineTitle(started.mangaId);
      const now = nowIso();
      const offlineChapter = {
        id: chapterRef.id,
        number: chapterRef.number,
        volume: chapterRef.volume,
        title: chapterRef.title,
        translator: chapterRef.translator,
        pages: [...downloadedPages].sort((a, b) => a.number - b.number),
        downloadedAt: now,
      };
      const nextChapters = [
        ...(latest?.chapters ?? []).filter((chapter) => chapter.id !== offlineChapter.id),
        offlineChapter,
      ];
      await saveOfflineTitle({
        ...(latest ?? {
          ...started.meta,
          chapters: [],
          downloadedAt: now,
          updatedAt: now,
        }),
        ...started.meta,
        chapters: nextChapters,
      });

      chapterRef.status = 'done';
      chapterRef.error = null;
      const refreshed = await getOfflineTitle(started.mangaId);
      patchJob(jobId, {
        completedChapters: chapters.filter((chapter) => chapter.status === 'done').length,
        downloadedPages: manifestPagesForChapters(refreshed, jobChapterIds),
        chapters: chapters.map((chapter) => ({ ...chapter })),
      });
      await persistAndNotify();
    } catch (error: unknown) {
      if (isCancelled(jobId)) return;
      chapterRef.status = 'error';
      chapterRef.error = errorMessage(error);
      patchJob(jobId, {
        status: 'error',
        error: chapterRef.error,
        chapters: chapters.map((chapter) => ({ ...chapter })),
      });
      await persistAndNotify();
      // Продолжаем следующие главы: одна проблемная глава не должна
      // блокировать весь тайтл. Повтор — кнопкой «Повторить».
    }
  }

  if (isCancelled(jobId)) return;
  const finalJob = currentJob(jobId);
  if (!finalJob) return;
  const allDone = finalJob.chapters.every((chapter) => chapter.status === 'done');
  const failed = finalJob.chapters.find((chapter) => chapter.status === 'error');
  const status: DownloadJobStatus = allDone ? 'done' : failed ? 'error' : 'cancelled';
  patchJob(jobId, {
    status,
    error: allDone ? null : (failed?.error ?? 'Загрузка прервана'),
    currentChapterId: null,
    currentPage: null,
  });
  await persistAndNotify();
}

async function waitForImageSlot(mode: DownloadJobMode): Promise<void> {
  const nextAt = mode === 'title' ? nextWholeImageAt : nextSingleImageAt;
  const wait = nextAt - Date.now();
  if (wait > 0) await sleep(wait);
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

/* ------------------------------------------------------------------ */
/* Автостарт после импорта модуля (приложение/страница уже открыты)     */
/* ------------------------------------------------------------------ */

void initDownloadManager().catch(() => undefined);

/* Экспортируется для страниц: тип задания удобно использовать в UI. */
export type { DownloadJob, DownloadJobMode };
