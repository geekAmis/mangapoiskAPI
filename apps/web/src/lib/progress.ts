import type { ProgressOut } from '../api/types';

export const LOCAL_PROGRESS_KEY = 'mp:progress:v1';
export const LOCAL_READING_DAYS_KEY = 'mp:reading-days:v1';
export const LOCAL_PROGRESS_EVENT = 'mp:progress';
const MAX_LOCAL_ITEMS = 100;
const MAX_LOCAL_DAYS = 400;

export interface ProgressMangaSnapshot {
  id: string;
  title: string;
  poster_url: string | null;
  source: string;
  adult: boolean;
  genres: string[];
  rating: number | null;
  chapters_count: number;
  status: string | null;
}

export interface ProgressChapterSnapshot {
  id: string;
  volume: string | null;
  number: string;
  title: string;
  page_count: number;
}

export interface LocalProgressItem {
  manga_id: string;
  chapter_id: string;
  page: number;
  total_pages: number;
  updated_at: string;
  owner_id: string | null;
  finished: boolean;
  manga: ProgressMangaSnapshot;
  chapter: ProgressChapterSnapshot;
}

export interface ReadingResume {
  manga_id: string;
  chapter_id: string;
  page: number;
  total_pages: number;
  updated_at: string;
  title: string;
  poster_url: string | null;
  source: string;
  chapter: {
    volume: string | null;
    number: string;
    title: string;
    page_count: number;
  };
  finished: boolean;
}

export interface LocalStreak {
  current: number;
  longest: number;
  readToday: boolean;
  days: string[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function asString(value: unknown): string | null {
  return typeof value === 'string' && value ? value : null;
}

function asNumber(value: unknown, fallback = 0): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

function normalizeItem(value: unknown): LocalProgressItem | null {
  if (!isRecord(value)) return null;
  const manga = value.manga;
  const chapter = value.chapter;
  if (!isRecord(manga) || !isRecord(chapter)) return null;
  const mangaId = asString(value.manga_id) ?? asString(manga.id);
  const chapterId = asString(value.chapter_id) ?? asString(chapter.id);
  const title = asString(manga.title);
  if (!mangaId || !chapterId || !title) return null;
  const updatedAt = asString(value.updated_at);
  if (!updatedAt || Number.isNaN(new Date(updatedAt).getTime())) return null;
  return {
    manga_id: mangaId,
    chapter_id: chapterId,
    page: Math.max(1, Math.trunc(asNumber(value.page, 1))),
    total_pages: Math.max(0, Math.trunc(asNumber(value.total_pages, 0))),
    updated_at: updatedAt,
    owner_id: asString(value.owner_id),
    finished: Boolean(value.finished),
    manga: {
      id: mangaId,
      title,
      poster_url: asString(manga.poster_url),
      source: asString(manga.source) ?? '',
      adult: Boolean(manga.adult),
      genres: Array.isArray(manga.genres)
        ? manga.genres.filter((item): item is string => typeof item === 'string')
        : [],
      rating: typeof manga.rating === 'number' ? manga.rating : null,
      chapters_count: Math.max(0, Math.trunc(asNumber(manga.chapters_count, 0))),
      status: asString(manga.status),
    },
    chapter: {
      id: chapterId,
      volume: asString(chapter.volume),
      number: asString(chapter.number) ?? '0',
      title: asString(chapter.title) ?? '',
      page_count: Math.max(0, Math.trunc(asNumber(chapter.page_count, 0))),
    },
  };
}

export function readLocalProgress(ownerId?: string | null): LocalProgressItem[] {
  if (typeof window === 'undefined') return [];
  let raw: string | null = null;
  try {
    raw = window.localStorage.getItem(LOCAL_PROGRESS_KEY);
  } catch {
    return [];
  }
  if (!raw) return [];
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return [];
  }
  const items = (Array.isArray(parsed) ? parsed : [])
    .map(normalizeItem)
    .filter((item): item is LocalProgressItem => item !== null)
    .filter(
      (item) =>
        ownerId === undefined ||
        item.owner_id === null ||
        item.owner_id === ownerId,
    );
  return dedupeByManga(items).slice(0, MAX_LOCAL_ITEMS);
}

function writeLocalProgress(items: LocalProgressItem[]): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(LOCAL_PROGRESS_KEY, JSON.stringify(items.slice(0, MAX_LOCAL_ITEMS)));
  } catch {
    return;
  }
  window.dispatchEvent(new Event(LOCAL_PROGRESS_EVENT));
}

export function saveLocalProgress(
  input: Omit<LocalProgressItem, 'owner_id' | 'updated_at'> & {
    owner_id: string | null;
    updated_at?: string;
  },
): void {
  const existing = readLocalProgress();
  const next: LocalProgressItem = {
    ...input,
    updated_at: input.updated_at ?? new Date().toISOString(),
    owner_id: input.owner_id,
    page: Math.max(1, Math.trunc(input.page)),
    total_pages: Math.max(0, Math.trunc(input.total_pages)),
  };
  const items = dedupeByManga([next, ...existing]);
  writeLocalProgress(items);
}

export function clearLocalProgress(mangaId?: string): void {
  const existing = readLocalProgress();
  writeLocalProgress(mangaId ? existing.filter((item) => item.manga_id !== mangaId) : []);
}

export function markLocalProgressSynced(ownerId: string): void {
  let changed = false;
  const items = readLocalProgress().map((item) => {
    if (item.owner_id === null) {
      changed = true;
      return { ...item, owner_id: ownerId };
    }
    return item;
  });
  if (changed) writeLocalProgress(items);
}

function dedupeByManga(items: LocalProgressItem[]): LocalProgressItem[] {
  const byManga = new Map<string, LocalProgressItem>();
  for (const item of items) {
    const current = byManga.get(item.manga_id);
    if (!current || new Date(item.updated_at) > new Date(current.updated_at)) {
      byManga.set(item.manga_id, item);
    }
  }
  return [...byManga.values()].sort(
    (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
  );
}

export function resumeFromLocal(item: LocalProgressItem): ReadingResume {
  return {
    manga_id: item.manga_id,
    chapter_id: item.chapter_id,
    page: item.page,
    total_pages: item.total_pages || item.chapter.page_count,
    updated_at: item.updated_at,
    title: item.manga.title,
    poster_url: item.manga.poster_url,
    source: item.manga.source,
    chapter: item.chapter,
    finished: item.finished,
  };
}

export function resumeFromProgress(item: ProgressOut): ReadingResume | null {
  if (!item.manga) return null;
  return {
    manga_id: item.manga_id,
    chapter_id: item.chapter_id,
    page: item.page,
    total_pages: item.total_pages || item.chapter?.page_count || 0,
    updated_at: item.updated_at,
    title: item.manga.title,
    poster_url: item.manga.poster_url,
    source: item.manga.source,
    chapter: {
      volume: item.chapter?.volume ?? null,
      number: item.chapter?.number ?? '',
      title: item.chapter?.title ?? '',
      page_count: item.chapter?.page_count ?? 0,
    },
    // Whether this is the final chapter is established by the title page; the
    // progress row alone cannot tell it.
    finished: false,
  };
}

export function mergeResumes(
  local: ReadingResume[],
  remote: ReadingResume[],
): ReadingResume[] {
  const byManga = new Map<string, ReadingResume>();
  for (const item of [...remote, ...local]) {
    const current = byManga.get(item.manga_id);
    if (!current || new Date(item.updated_at) > new Date(current.updated_at)) {
      byManga.set(item.manga_id, item);
    }
  }
  return [...byManga.values()].sort(
    (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
  );
}

/* ------------------------------------------------------------------ */
/* Anonymous streak                                                    */
/* ------------------------------------------------------------------ */

function browserTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch {
    return 'UTC';
  }
}

function dateKey(value: Date, timezone: string): string {
  const format = (options: Intl.DateTimeFormatOptions): string => {
    const parts = new Intl.DateTimeFormat('en-US', options).formatToParts(value);
    const pick = (type: string) => parts.find((part) => part.type === type)?.value ?? '';
    return `${pick('year')}-${pick('month')}-${pick('day')}`;
  };
  try {
    return format({ timeZone: timezone, year: 'numeric', month: '2-digit', day: '2-digit' });
  } catch {
    return format({ year: 'numeric', month: '2-digit', day: '2-digit' });
  }
}

function previousDay(key: string): string {
  const date = new Date(`${key}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() - 1);
  return date.toISOString().slice(0, 10);
}

export function recordLocalReadingDay(timestamp = new Date()): void {
  if (typeof window === 'undefined') return;
  const timezone = browserTimezone();
  const day = dateKey(timestamp, timezone);
  let saved: Record<string, string> = {};
  try {
    const raw = window.localStorage.getItem(LOCAL_READING_DAYS_KEY);
    const parsed = raw ? (JSON.parse(raw) as unknown) : {};
    if (isRecord(parsed)) {
      for (const [key, value] of Object.entries(parsed)) {
        if (typeof value === 'string' && !Number.isNaN(new Date(value).getTime())) {
          saved[key] = value;
        }
      }
    }
  } catch {
    saved = {};
  }
  saved[day] = timestamp.toISOString();
  const entries = Object.entries(saved)
    .sort((a, b) => b[0].localeCompare(a[0]))
    .slice(0, MAX_LOCAL_DAYS);
  try {
    window.localStorage.setItem(LOCAL_READING_DAYS_KEY, JSON.stringify(Object.fromEntries(entries)));
  } catch {
    return;
  }
  window.dispatchEvent(new Event(LOCAL_PROGRESS_EVENT));
}

export function readLocalReadingDayTimestamps(): string[] {
  return readLocalReadingDays();
}

export function clearLocalReadingDays(): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.removeItem(LOCAL_READING_DAYS_KEY);
  } catch {
    return;
  }
  window.dispatchEvent(new Event(LOCAL_PROGRESS_EVENT));
}

function readLocalReadingDays(): string[] {
  if (typeof window === 'undefined') return [];
  try {
    const raw = window.localStorage.getItem(LOCAL_READING_DAYS_KEY);
    const parsed = raw ? (JSON.parse(raw) as unknown) : {};
    if (!isRecord(parsed)) return [];
    return Object.values(parsed).filter(
      (value): value is string =>
        typeof value === 'string' && !Number.isNaN(new Date(value).getTime()),
    );
  } catch {
    return [];
  }
}

export function computeLocalStreak(
  timestamps: string[] = readLocalReadingDays(),
  timezone = browserTimezone(),
  now = new Date(),
): LocalStreak {
  const days = new Set<string>();
  for (const timestamp of timestamps) {
    const date = new Date(timestamp);
    if (!Number.isNaN(date.getTime())) days.add(dateKey(date, timezone));
  }
  if (days.size === 0) return { current: 0, longest: 0, readToday: false, days: [] };

  const today = dateKey(now, timezone);
  let anchor: string | null = null;
  if (days.has(today)) anchor = today;
  else if (days.has(previousDay(today))) anchor = previousDay(today);

  let current = 0;
  let cursor = anchor;
  while (cursor && days.has(cursor)) {
    current += 1;
    cursor = previousDay(cursor);
  }

  const sorted = [...days].sort();
  let longest = 0;
  let run = 0;
  let previous: string | null = null;
  for (const day of sorted) {
    run = previous && previousDay(day) === previous ? run + 1 : 1;
    longest = Math.max(longest, run);
    previous = day;
  }
  return {
    current,
    longest,
    readToday: days.has(today),
    days: sorted.slice(-30),
  };
}
