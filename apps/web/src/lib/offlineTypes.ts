/**
 * Модель офлайн-библиотеки: манифесты тайтлов, страницы, очередь загрузки.
 *
 * Манифест хранится отдельно от байтов изображений: на нативе — в Preferences
 * (JSON), в браузере — в IndexedDB. Изображения лежат в Filesystem/IndexedDB.
 */

export type DownloadJobStatus = 'queued' | 'running' | 'done' | 'error' | 'cancelled';
export type DownloadJobMode = 'title' | 'chapter';
export type DownloadChapterStatus = 'pending' | 'downloading' | 'done' | 'error';

export interface OfflinePage {
  number: number;
  /** Относительный путь в Directory.Data / ключ IndexedDB. */
  path: string;
  width: number | null;
  height: number | null;
  contentType: string;
  /** Размер в байтах, если известен. */
  size: number;
}

export interface OfflineChapter {
  id: string;
  number: string;
  volume: string | null;
  title: string;
  translator: string | null;
  pages: OfflinePage[];
  downloadedAt: string;
}

export interface OfflineMangaMeta {
  id: string;
  source: string;
  title: string;
  titleEn: string | null;
  titleAlt: string | null;
  poster: string | null;
  description: string | null;
  year: number | null;
  status: string | null;
  contentType: string | null;
  rating: number | null;
  ratingCount: number | null;
  genres: string[];
  adult: boolean;
  lastChapterAt: string | null;
}

export interface OfflineTitle extends OfflineMangaMeta {
  chapters: OfflineChapter[];
  downloadedAt: string;
  updatedAt: string;
}

export interface OfflineProgress {
  mangaId: string;
  chapterId: string;
  page: number;
  totalPages: number;
  updatedAt: string;
}

export interface DownloadJobChapter {
  id: string;
  number: string;
  volume: string | null;
  title: string;
  translator: string | null;
  pageCount: number;
  status: DownloadChapterStatus;
  error: string | null;
}

export interface DownloadJob {
  /** Для полного тайтла совпадает с mangaId, для одной главы — уникальный. */
  id: string;
  mangaId: string;
  mode: DownloadJobMode;
  meta: OfflineMangaMeta;
  chapters: DownloadJobChapter[];
  status: DownloadJobStatus;
  createdAt: string;
  updatedAt: string;
  totalPages: number;
  downloadedPages: number;
  completedChapters: number;
  currentChapterId: string | null;
  currentPage: number | null;
  error: string | null;
}

export interface OfflineStats {
  chapters: number;
  pages: number;
  bytes: number;
}

export const EMPTY_OFFLINE_STATS: OfflineStats = { chapters: 0, pages: 0, bytes: 0 };

export function compareOfflineChapters(
  a: { volume: string | null; number: string },
  b: { volume: string | null; number: string },
): number {
  const byVolume = (a.volume ?? '').localeCompare(b.volume ?? '', 'ru', { numeric: true });
  if (byVolume !== 0) return byVolume;
  return a.number.localeCompare(b.number, 'ru', { numeric: true });
}

export function sortOfflineChapters<T extends { volume: string | null; number: string }>(
  chapters: T[],
): T[] {
  return [...chapters].sort(compareOfflineChapters);
}

export function offlineTitleStats(title: OfflineTitle): OfflineStats {
  let pages = 0;
  let bytes = 0;
  for (const chapter of title.chapters) {
    pages += chapter.pages.length;
    for (const page of chapter.pages) bytes += page.size || 0;
  }
  return { chapters: title.chapters.length, pages, bytes };
}

const bytesFormatter = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 });

/** «12,3 МБ» — компактный размер для карточек и страницы тайтла. */
export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 Б';
  const units = ['Б', 'КБ', 'МБ', 'ГБ'];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  if (unit === 0) return `${bytesFormatter.format(Math.round(value))} Б`;
  return `${bytesFormatter.format(value)} ${units[unit]}`;
}

export function isActiveJob(job: DownloadJob): boolean {
  return job.status === 'queued' || job.status === 'running';
}

export function jobPercent(job: DownloadJob): number {
  if (job.totalPages > 0) {
    return Math.min(100, Math.max(0, Math.round((job.downloadedPages / job.totalPages) * 100)));
  }
  if (job.chapters.length > 0) {
    return Math.min(100, Math.round((job.completedChapters / job.chapters.length) * 100));
  }
  return 0;
}
