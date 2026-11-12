/**
 * Менеджер офлайн-загрузок на устройство.
 *
 * Полный тайтл сначала подготавливается на сервере: gateway архивирует главы,
 * а клиент опрашивает прогресс. Как только готовы очередные 5 глав, они
 * ставятся в очередь на устройство; подготовка остальных продолжается
 * параллельно. Искусственной паузы 2–4,89 с между изображениями больше нет:
 * после подготовки страницы отдаются из серверного архива.
 *
 * Одиночная глава по-прежнему скачивается быстро и без ожидания подготовки.
 * Прогресс и очередь сохраняются после каждого изображения и переживают
 * перезапуск приложения.
 */

import { useSyncExternalStore } from 'react';
import { api, resolveApiUrl } from '../api/client';
import type { PrepareStatusOut } from '../api/client';
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

/** Сколько подготовленных глав скачивается одной пачкой. */
export const PREPARE_BATCH_SIZE = 5;
/** Интервал опроса состояния подготовки на сервере. */
export const PREPARE_POLL_MS = 1700;

/**
 * Задержка между двумя изображениями очереди «весь тайтл». После серверной
 * подготовки изображения приходят из архива, поэтому троттлинг равен нулю.
 */
export const WHOLE_TITLE_MIN_DELAY_MS = 0;
export const WHOLE_TITLE_MAX_EXTRA_DELAY_MS = 0;
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

export type PreparePhaseStatus = 'idle' | 'running' | 'done' | 'error' | 'cancelled';

export interface PrepareJobState {
  status: PreparePhaseStatus;
  total: number;
  prepared: number;
  failed: number;
  error: string | null;
  /** id глав, которые сервер уже подготовил (переживает перезапуск). */
  preparedIds: string[];
  /** id -> сообщение ошибки подготовки. */
  errors: Record<string, string>;
}

/** Задание с добавленной фазой серверной подготовки. */
export interface ManagedDownloadJob extends DownloadJob {
  prepare: PrepareJobState;
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

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
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

function emptyPrepare(mode: DownloadJobMode, total: number): PrepareJobState {
  return {
    status: mode === 'chapter' ? 'done' : 'idle',
    total,
    prepared: 0,
    failed: 0,
    error: null,
    preparedIds: [],
    errors: {},
  };
}

function normalizePrepare(raw: unknown, job: DownloadJob): PrepareJobState {
  if (!isRecord(raw)) return emptyPrepare(job.mode, job.chapters.length);
  const chapterIds = new Set(job.chapters.map((chapter) => chapter.id));
  const preparedIds = Array.isArray(raw.preparedIds)
    ? raw.preparedIds.filter((value): value is string => typeof value === 'string' && chapterIds.has(value))
    : [];
  const errors: Record<string, string> = {};
  if (isRecord(raw.errors)) {
    for (const [key, value] of Object.entries(raw.errors)) {
      if (chapterIds.has(key) && typeof value === 'string' && value.trim()) errors[key] = value;
    }
  }
  const phases: PreparePhaseStatus[] = ['idle', 'running', 'done', 'error', 'cancelled'];
  const status = phases.includes(raw.status as PreparePhaseStatus)
    ? (raw.status as PreparePhaseStatus)
    : job.mode === 'chapter'
      ? 'done'
      : 'idle';
  return {
    status,
    total: job.chapters.length,
    prepared: Math.max(
      0,
      Math.min(
        job.chapters.length,
        job.chapters.filter(
          (chapter) => chapter.status === 'done' || preparedIds.includes(chapter.id),
        ).length,
      ),
    ),
    failed: Object.keys(errors).length,
    error: typeof raw.error === 'string' ? raw.error : null,
    preparedIds,
    errors,
  };
}

function normalizeJob(job: DownloadJob): ManagedDownloadJob {
  const record = job as DownloadJob & { prepare?: unknown };
  return {
    ...job,
    prepare: normalizePrepare(record.prepare, job),
  };
}

/** Пересчитывает счётчики подготовки после изменения списка глав. */
function recomputePrepare(
  job: ManagedDownloadJob,
  patch: Partial<PrepareJobState> = {},
): PrepareJobState {
  const chapterIds = new Set(job.chapters.map((chapter) => chapter.id));
  const source = { ...job.prepare, ...patch };
  const preparedIds = Array.from(
    new Set(source.preparedIds.filter((id) => chapterIds.has(id))),
  );
  const errors: Record<string, string> = {};
  for (const [id, message] of Object.entries(source.errors)) {
    if (chapterIds.has(id) && message.trim()) errors[id] = message;
  }
  const prepared = job.chapters.filter(
    (chapter) => chapter.status === 'done' || preparedIds.includes(chapter.id),
  ).length;
  const failed = job.chapters.filter(
    (chapter) => chapter.status !== 'done' && errors[chapter.id] !== undefined,
  ).length;
  return {
    ...source,
    total: job.chapters.length,
    prepared,
    failed,
    preparedIds,
    errors,
  };
}

function cloneJobs(jobs: ManagedDownloadJob[]): ManagedDownloadJob[] {
  return jobs.map((job) => ({
    ...job,
    meta: { ...job.meta, genres: [...job.meta.genres] },
    prepare: {
      ...job.prepare,
      preparedIds: [...job.prepare.preparedIds],
      errors: { ...job.prepare.errors },
    },
    chapters: job.chapters.map((chapter) => ({ ...chapter })),
  }));
}

/* ------------------------------------------------------------------ */
/* Состояние и подписки                                                */
/* ------------------------------------------------------------------ */

let jobs: ManagedDownloadJob[] = [];
let initPromise: Promise<void> | null = null;
let workerRunning = false;
let workerWakeRequested = false;
let persistChain: Promise<void> = Promise.resolve();
/** Следующий разрешённый старт одиночного изображения. */
let nextSingleImageAt = 0;
/** Текущий цикл опроса подготовки; смена токена останавливает старый. */
const prepareLoops = new Map<string, symbol>();
const jobListeners = new Set<() => void>();

function notifyJobs(): void {
  for (const listener of jobListeners) listener();
}

function subscribeJobs(listener: () => void): () => void {
  jobListeners.add(listener);
  return () => jobListeners.delete(listener);
}

export function getDownloadJobs(): ManagedDownloadJob[] {
  return jobs;
}

export function useDownloadJobs(): ManagedDownloadJob[] {
  return useSyncExternalStore(subscribeJobs, getDownloadJobs, getDownloadJobs);
}

export function getActiveDownloadJob(mangaId: string): ManagedDownloadJob | null {
  return (
    jobs.find(
      (job) =>
        job.mangaId === mangaId &&
        (job.status === 'running' || job.status === 'queued' || job.status === 'error'),
    ) ?? null
  );
}

function replaceJob(next: ManagedDownloadJob): void {
  jobs = jobs.map((job) => (job.id === next.id ? next : job));
  notifyJobs();
}

function patchJob(jobId: string, patch: Partial<ManagedDownloadJob>): ManagedDownloadJob | null {
  const current = jobs.find((job) => job.id === jobId);
  if (!current) return null;
  const next: ManagedDownloadJob = { ...current, ...patch, updatedAt: nowIso() };
  replaceJob(next);
  return next;
}

function patchPrepare(
  jobId: string,
  patch: Partial<PrepareJobState>,
): ManagedDownloadJob | null {
  const current = jobs.find((job) => job.id === jobId);
  if (!current) return null;
  return patchJob(jobId, {
    prepare: recomputePrepare(current, patch),
  });
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

    // Завершённые задания не нужны после перезапуска: манифест уже содержит
    // скачанные главы. Отменённые и остановившиеся задания сохраняем, чтобы
    // пользователь мог продолжить их без повторной подготовки готового.
    const kept = stored.filter((job) => job.status !== 'done');
    const pruned = stored.filter((job) => job.status === 'done');
    jobs = kept.map((job) => {
      const normalized = normalizeJob(job);
      const allPrepared =
        normalized.mode === 'chapter' ||
        normalized.chapters.every(
          (chapter) =>
            chapter.status === 'done' || normalized.prepare.preparedIds.includes(chapter.id),
        );
      return {
        ...normalized,
        status: normalized.status === 'running' ? 'queued' : normalized.status,
        currentChapterId: null,
        currentPage: null,
        prepare: {
          ...normalized.prepare,
          status:
            normalized.mode === 'chapter'
              ? 'done'
              : normalized.status === 'cancelled'
                ? 'cancelled'
                : allPrepared
                  ? 'done'
                  : 'idle',
          error: normalized.prepare.status === 'error' ? normalized.prepare.error : null,
        },
        chapters: normalized.chapters.map((chapter) =>
          chapter.status === 'downloading' ? { ...chapter, status: 'pending' } : chapter,
        ),
      };
    });
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

export async function startTitleDownload(
  input: StartTitleDownloadInput,
): Promise<ManagedDownloadJob | null> {
  await initDownloadManager();
  const meta = metaFromManga(input.manga, input);
  const chapters = sortOfflineChapters(input.chapters.filter((chapter) => !chapter.is_external));

  const active = jobs.find(
    (job) => job.id === meta.id && job.mode === 'title' && isActiveJob(job),
  );
  if (active) {
    // Добавляем главы, которых ещё нет в активной очереди (например, после обновления).
    const known = new Set(active.chapters.map((chapter) => chapter.id));
    const additions = chapters.filter((chapter) => !known.has(chapter.id)).map(toJobChapter);
    if (additions.length > 0) {
      const nextChapters = [...active.chapters, ...additions];
      const nextJob = { ...active, chapters: nextChapters };
      stopPrepareLoop(active.id);
      const next = patchJob(active.id, {
        chapters: nextChapters,
        totalPages:
          active.totalPages + additions.reduce((sum, chapter) => sum + chapter.pageCount, 0),
        prepare: recomputePrepare(nextJob, {
          status: 'idle',
          error: null,
          errors: {},
        }),
      });
      if (next) await persistAndNotify();
      void pumpQueue();
    } else {
      void pumpQueue();
    }
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

  const job: ManagedDownloadJob = {
    id: meta.id,
    mangaId: meta.id,
    mode: 'title',
    meta,
    chapters: pending.map(toJobChapter),
    prepare: emptyPrepare('title', pending.length),
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
): Promise<ManagedDownloadJob | null> {
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

  const job: ManagedDownloadJob = {
    id: jobId,
    mangaId: meta.id,
    mode: 'chapter',
    meta,
    chapters: [toJobChapter(input.chapter)],
    prepare: emptyPrepare('chapter', 1),
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
  stopPrepareLoop(jobId);
  const cancelled = patchJob(jobId, {
    status: 'cancelled',
    currentChapterId: null,
    currentPage: null,
    error: null,
    prepare: {
      ...job.prepare,
      status: 'cancelled',
    },
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
  stopPrepareLoop(jobId);
  const chapters = job.chapters.map((chapter) => ({
    ...chapter,
    status: chapter.status === 'done' ? ('done' as const) : ('pending' as const),
    error: null,
  }));
  const nextJob = { ...job, chapters };
  patchJob(jobId, {
    status: 'queued',
    error: null,
    currentChapterId: null,
    currentPage: null,
    chapters,
    prepare: recomputePrepare(nextJob, {
      status:
        job.mode === 'chapter' ||
        chapters.every(
          (chapter) =>
            chapter.status === 'done' || job.prepare.preparedIds.includes(chapter.id),
        )
          ? 'done'
          : 'idle',
      error: null,
      errors: {},
    }),
  });
  await persistAndNotify();
  void pumpQueue();
}

export async function removeDownloadJob(jobId: string): Promise<void> {
  stopPrepareLoop(jobId);
  jobs = jobs.filter((job) => job.id !== jobId);
  await persistAndNotify();
}

/** Прогресс серверной подготовки в процентах. */
export function preparePercent(job: ManagedDownloadJob): number {
  if (job.prepare.total <= 0) return 0;
  return Math.min(
    100,
    Math.max(0, Math.round((job.prepare.prepared / job.prepare.total) * 100)),
  );
}

/** Готовы ли все главы задания к скачиванию на устройство. */
export function isPrepareComplete(job: ManagedDownloadJob): boolean {
  return job.prepare.status === 'done' || job.prepare.status === 'error';
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
/* Подготовка на сервере                                               */
/* ------------------------------------------------------------------ */

function terminalPrepare(status: PreparePhaseStatus): boolean {
  return status === 'done' || status === 'error' || status === 'cancelled';
}

function stopPrepareLoop(jobId: string): void {
  prepareLoops.delete(jobId);
}

function startPrepareLoop(jobId: string): void {
  if (prepareLoops.has(jobId)) return;
  const token = Symbol(`prepare:${jobId}`);
  prepareLoops.set(jobId, token);
  void runPrepareLoop(jobId, token).finally(() => {
    if (prepareLoops.get(jobId) === token) prepareLoops.delete(jobId);
  });
}

function prepareLoopActive(jobId: string, token: symbol): boolean {
  return prepareLoops.get(jobId) === token;
}

/**
 * Применяет снимок статуса подготовки к заданию. Возвращает true, если
 * состояние изменилось и его нужно сохранить.
 */
function applyPrepareSnapshot(jobId: string, snapshot: PrepareStatusOut): boolean {
  const job = currentJob(jobId);
  if (!job) return false;
  const jobIds = new Set(job.chapters.map((chapter) => chapter.id));
  const reported = new Set<string>();
  const preparedIds = new Set(job.prepare.preparedIds);
  const errors: Record<string, string> = { ...job.prepare.errors };
  let reportedFailed = 0;
  let reportedPending = 0;

  for (const item of snapshot.chapters) {
    if (!jobIds.has(item.id)) continue;
    reported.add(item.id);
    if (item.status === 'done') {
      preparedIds.add(item.id);
      delete errors[item.id];
    } else if (item.status === 'error') {
      reportedFailed += 1;
      preparedIds.delete(item.id);
      errors[item.id] = item.error || 'Не удалось подготовить главу';
    } else {
      reportedPending += 1;
      preparedIds.delete(item.id);
      delete errors[item.id];
    }
  }

  const missing = job.chapters.filter((chapter) => !reported.has(chapter.id)).length;
  const allReported = missing === 0;
  const terminal = allReported && reportedPending === 0;

  const chapters = job.chapters.map((chapter) => {
    if (chapter.status === 'done') return chapter;
    const prepareError = errors[chapter.id];
    if (prepareError) {
      return {
        ...chapter,
        status: 'error' as const,
        error: `Подготовка на сервере: ${prepareError}`,
      };
    }
    if (preparedIds.has(chapter.id) && job.prepare.errors[chapter.id] !== undefined) {
      return { ...chapter, status: 'pending' as const, error: null };
    }
    return chapter;
  });

  let status: PreparePhaseStatus;
  let prepareError: string | null = null;
  if (snapshot.error) {
    status = 'error';
    prepareError = snapshot.error;
  } else if (terminal) {
    status = 'done';
    prepareError =
      reportedFailed > 0 ? `Не удалось подготовить глав: ${reportedFailed}` : null;
  } else {
    status = 'running';
  }

  const nextPrepare = recomputePrepare({ ...job, chapters }, {
    status,
    error: prepareError,
    preparedIds: Array.from(preparedIds),
    errors,
  });

  const changed =
    job.prepare.status !== nextPrepare.status ||
    job.prepare.total !== nextPrepare.total ||
    job.prepare.prepared !== nextPrepare.prepared ||
    job.prepare.failed !== nextPrepare.failed ||
    job.prepare.error !== nextPrepare.error ||
    job.prepare.preparedIds.length !== nextPrepare.preparedIds.length ||
    job.prepare.preparedIds.some((id, index) => id !== nextPrepare.preparedIds[index]) ||
    JSON.stringify(job.prepare.errors) !== JSON.stringify(nextPrepare.errors) ||
    chapters.some(
      (chapter, index) =>
        chapter.status !== job.chapters[index]?.status ||
        chapter.error !== job.chapters[index]?.error,
    );

  if (!changed) return false;
  patchJob(jobId, {
    chapters,
    prepare: nextPrepare,
    completedChapters: chapters.filter((chapter) => chapter.status === 'done').length,
  });
  return true;
}

async function runPrepareLoop(jobId: string, token: symbol): Promise<void> {
  const initial = currentJob(jobId);
  if (!initial || initial.mode !== 'title') return;
  let posted = false;
  let failures = 0;

  while (prepareLoopActive(jobId, token)) {
    const job = currentJob(jobId);
    if (!job || job.mode !== 'title') return;
    if (job.status !== 'running' && job.status !== 'queued') return;
    if (terminalPrepare(job.prepare.status)) return;

    if (!posted) {
      try {
        await api.prepareManga(job.mangaId);
        posted = true;
        failures = 0;
      } catch (error: unknown) {
        failures += 1;
        if (failures >= 3) {
          patchPrepare(jobId, {
            status: 'error',
            error: `Не удалось запустить подготовку: ${errorMessage(error)}`,
          });
          await persistAndNotify();
          return;
        }
        await sleep(800 * failures);
        continue;
      }
    }

    try {
      const snapshot = await api.getPrepareStatus(job.mangaId);
      if (!prepareLoopActive(jobId, token)) return;
      if (isCancelled(jobId)) return;
      const changed = applyPrepareSnapshot(jobId, snapshot);
      if (changed) await persistAndNotify();
      failures = 0;
      const current = currentJob(jobId);
      if (!current || terminalPrepare(current.prepare.status)) return;
    } catch (error: unknown) {
      failures += 1;
      if (failures >= 3) {
        patchPrepare(jobId, {
          status: 'error',
          error: `Не удалось получить прогресс подготовки: ${errorMessage(error)}`,
        });
        await persistAndNotify();
        return;
      }
    }
    await sleep(PREPARE_POLL_MS);
  }
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

function nextQueuedJob(): ManagedDownloadJob | null {
  return jobs.find((job) => job.status === 'queued') ?? null;
}

function isCancelled(jobId: string): boolean {
  return jobs.find((job) => job.id === jobId)?.status === 'cancelled';
}

function currentJob(jobId: string): ManagedDownloadJob | null {
  return jobs.find((job) => job.id === jobId) ?? null;
}

/**
 * Выбирает следующую пачку для устройства: не меньше 5 подготовленных глав
 * либо все оставшиеся, когда подготовка уже завершилась/остановилась.
 */
function selectDownloadBatch(job: ManagedDownloadJob): DownloadJobChapter[] {
  if (job.mode === 'chapter') {
    return job.chapters.filter((chapter) => chapter.status !== 'done').slice(0, 1);
  }
  const prepared = job.chapters.filter(
    (chapter) =>
      chapter.status !== 'done' &&
      chapter.status !== 'error' &&
      job.prepare.preparedIds.includes(chapter.id) &&
      job.prepare.errors[chapter.id] === undefined,
  );
  if (prepared.length >= PREPARE_BATCH_SIZE) {
    return prepared.slice(0, PREPARE_BATCH_SIZE);
  }
  if (terminalPrepare(job.prepare.status)) return prepared;
  return [];
}

/** Помечает главы, которые так и не были подготовлены, ошибками. */
async function markUnpreparedAsFailed(jobId: string): Promise<void> {
  const job = currentJob(jobId);
  if (!job) return;
  const errors = { ...job.prepare.errors };
  const chapters = job.chapters.map((chapter) => {
    if (chapter.status === 'done') return chapter;
    if (job.prepare.preparedIds.includes(chapter.id) || errors[chapter.id]) return chapter;
    errors[chapter.id] = job.prepare.error ?? 'Глава не была подготовлена на сервере';
    return {
      ...chapter,
      status: 'error' as const,
      error: `Подготовка на сервере: ${errors[chapter.id]}`,
    };
  });
  patchJob(jobId, {
    chapters,
    prepare: recomputePrepare({ ...job, chapters }, { errors }),
  });
  await persistAndNotify();
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
    return { ...chapter, error: null };
  });
  const completedChapters = chapters.filter((chapter) => chapter.status === 'done').length;
  const totalPages = chapters.reduce((sum, chapter) => sum + (chapter.pageCount || 0), 0);
  const nextJob = { ...started, chapters };
  const prepare = recomputePrepare(nextJob, {
    status:
      started.mode === 'chapter' || terminalPrepare(started.prepare.status)
        ? started.prepare.status
        : 'running',
    error: started.prepare.status === 'error' ? started.prepare.error : null,
  });

  patchJob(jobId, {
    status: 'running',
    chapters,
    prepare,
    completedChapters,
    downloadedPages: manifestPagesForChapters(manifest, jobChapterIds),
    totalPages,
    error: null,
    currentChapterId: null,
    currentPage: null,
  });
  await persistAndNotify();

  if (started.mode === 'title' && !terminalPrepare(prepare.status)) {
    startPrepareLoop(jobId);
  }

  while (!isCancelled(jobId)) {
    const job = currentJob(jobId);
    if (!job) return;

    if (
      job.mode === 'title' &&
      (job.prepare.status === 'idle' || job.prepare.status === 'running') &&
      !prepareLoops.has(jobId)
    ) {
      patchPrepare(jobId, { status: 'running' });
      startPrepareLoop(jobId);
    }

    const batch = selectDownloadBatch(job);
    if (batch.length === 0) {
      const unfinished = job.chapters.some((chapter) => chapter.status !== 'done');
      if (!unfinished) break;
      if (job.mode === 'title' && terminalPrepare(job.prepare.status)) {
        const pendingPrepared = job.chapters.some(
          (chapter) =>
            chapter.status !== 'done' &&
            chapter.status !== 'error' &&
            job.prepare.preparedIds.includes(chapter.id) &&
            job.prepare.errors[chapter.id] === undefined,
        );
        if (!pendingPrepared) {
          await markUnpreparedAsFailed(jobId);
          break;
        }
      }
      await sleep(200);
      continue;
    }

    for (const chapter of batch) {
      if (isCancelled(jobId)) return;
      await downloadChapter(jobId, chapter.id);
    }
  }

  if (isCancelled(jobId)) return;
  const finalJob = currentJob(jobId);
  if (!finalJob) return;
  stopPrepareLoop(jobId);
  const allDone = finalJob.chapters.every((chapter) => chapter.status === 'done');
  const failed = finalJob.chapters.find((chapter) => chapter.status === 'error');
  const status: DownloadJobStatus = allDone ? 'done' : failed ? 'error' : 'cancelled';
  patchJob(jobId, {
    status,
    error: allDone
      ? null
      : (failed?.error ?? finalJob.prepare.error ?? 'Загрузка прервана'),
    currentChapterId: null,
    currentPage: null,
  });
  await persistAndNotify();
}

async function downloadChapter(jobId: string, chapterId: string): Promise<void> {
  const job = currentJob(jobId);
  if (!job) return;
  const chapterRef = job.chapters.find((chapter) => chapter.id === chapterId);
  if (!chapterRef || chapterRef.status === 'done') return;

  patchJob(jobId, {
    currentChapterId: chapterRef.id,
    currentPage: 0,
    chapters: job.chapters.map((chapter) =>
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

    const updated = currentJob(jobId);
    if (!updated) return;
    const currentChapter = updated.chapters.find((chapter) => chapter.id === chapterRef.id);
    if (currentChapter) {
      currentChapter.pageCount = pages.length;
      currentChapter.title = detail.title || currentChapter.title;
      currentChapter.translator = detail.translator?.trim() || currentChapter.translator;
    }
    patchJob(jobId, {
      totalPages: updated.chapters.reduce((sum, chapter) => sum + (chapter.pageCount || 0), 0),
      chapters: updated.chapters.map((chapter) => ({ ...chapter })),
    });
    await persistAndNotify();

    const already = await isChapterFullyDownloaded(job.mangaId, chapterRef.id, pages.length);
    if (already) {
      markChapterDone(jobId, chapterRef.id);
      await persistAndNotify();
      return;
    }

    const downloadedPages: OfflinePage[] = [];
    for (let pageIndex = 0; pageIndex < pages.length; pageIndex += 1) {
      if (isCancelled(jobId)) return;
      const page = pages[pageIndex];
      if (!page) continue;
      const path = offlinePagePath(job.mangaId, chapterRef.id, page.number);
      const existing = await getOfflinePageInfo(path);

      let offlinePage: OfflinePage;
      let downloadedNow = false;
      if (existing.exists && existing.size > 0) {
        offlinePage = manifestPageFromExisting(page, path, existing);
      } else {
        // После серверной подготовки изображения не загружаются с источника:
        // для полного тайтла искусственная пауза не нужна вовсе. Одиночная
        // глава сохраняет прежний щадящий темп.
        if (job.mode === 'chapter') {
          await waitForImageSlot();
          if (isCancelled(jobId)) return;
        }
        const requestStartedAt = Date.now();
        const responsePromise = fetch(resolveApiUrl(page.url), { credentials: 'same-origin' });
        if (job.mode === 'chapter') {
          nextSingleImageAt = requestStartedAt + singleChapterImageDelay();
        }

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
          mangaId: job.mangaId,
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
        const current = currentJob(jobId);
        const nextDownloaded = (current?.downloadedPages ?? 0) + 1;
        patchJob(jobId, { downloadedPages: nextDownloaded, currentPage: pageIndex + 1 });
        await persistAndNotify();
      }

      if (isCancelled(jobId)) return;
    }

    if (isCancelled(jobId)) return;

    const latest = await getOfflineTitle(job.mangaId);
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
        ...job.meta,
        chapters: [],
        downloadedAt: now,
        updatedAt: now,
      }),
      ...job.meta,
      chapters: nextChapters,
    });

    markChapterDone(jobId, chapterRef.id);
    await persistAndNotify();
  } catch (error: unknown) {
    if (isCancelled(jobId)) return;
    const current = currentJob(jobId);
    if (!current) return;
    const message = errorMessage(error);
    patchJob(jobId, {
      error: message,
      chapters: current.chapters.map((chapter) =>
        chapter.id === chapterRef.id
          ? { ...chapter, status: 'error', error: message }
          : chapter,
      ),
    });
    await persistAndNotify();
    // Продолжаем следующие главы: одна проблемная глава не должна
    // блокировать весь тайтл. Повтор — кнопкой «Повторить».
  }
}

function markChapterDone(jobId: string, chapterId: string): void {
  const job = currentJob(jobId);
  if (!job) return;
  const chapters = job.chapters.map((chapter) =>
    chapter.id === chapterId ? { ...chapter, status: 'done' as const, error: null } : chapter,
  );
  const errors = { ...job.prepare.errors };
  delete errors[chapterId];
  const refreshed = { ...job, chapters };
  patchJob(jobId, {
    chapters,
    completedChapters: chapters.filter((chapter) => chapter.status === 'done').length,
    prepare: recomputePrepare(refreshed, {
      errors,
      preparedIds: job.prepare.preparedIds.includes(chapterId)
        ? job.prepare.preparedIds
        : [...job.prepare.preparedIds, chapterId],
    }),
  });
}

async function waitForImageSlot(): Promise<void> {
  const wait = nextSingleImageAt - Date.now();
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
