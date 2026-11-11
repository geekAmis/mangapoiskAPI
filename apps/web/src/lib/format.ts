const numberFormatter = new Intl.NumberFormat('ru-RU');
const dateFormatter = new Intl.DateTimeFormat('ru-RU', {
  day: 'numeric',
  month: 'long',
  year: 'numeric',
});
const shortDateFormatter = new Intl.DateTimeFormat('ru-RU', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
});
const dateTimeFormatter = new Intl.DateTimeFormat('ru-RU', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
});
const relativeFormatter = new Intl.RelativeTimeFormat('ru', { numeric: 'auto' });

export const SOURCE_LABELS: Record<string, string> = {
  mangapoisk: 'MangaPoisk',
  mangalib: 'MangaLib',
  remanga: 'Remanga',
  readmanga: 'ReadManga',
  mangadex: 'MangaDex',
};

const STATUS_LABELS: Record<string, string> = {
  ongoing: 'Выходит',
  completed: 'Завершён',
  hiatus: 'На паузе',
  paused: 'На паузе',
  announced: 'Анонс',
  upcoming: 'Скоро',
  cancelled: 'Отменён',
  licensed: 'Лицензирован',
  unknown: 'Неизвестно',
};

const CONTENT_TYPE_LABELS: Record<string, string> = {
  manga: 'Манга',
  manhwa: 'Манхва',
  manhua: 'Маньхуа',
  one_shot: 'Ваншот',
  one_shot_manga: 'Ваншот',
  doujinshi: 'Додзинси',
  novel: 'Ранобэ',
  comic: 'Комикс',
};

export const SORT_OPTIONS = [
  { value: 'popular', label: 'По популярности' },
  { value: 'rating', label: 'По рейтингу' },
  { value: 'updated', label: 'По обновлению' },
  { value: 'title', label: 'По алфавиту' },
] as const;

export const STATUS_OPTIONS = [
  { value: 'ongoing', label: 'Выходит' },
  { value: 'completed', label: 'Завершён' },
  { value: 'hiatus', label: 'На паузе' },
  { value: 'announced', label: 'Анонс' },
  { value: 'cancelled', label: 'Отменён' },
] as const;

export const GENRE_OPTIONS = [
  'Боевик',
  'Боевые искусства',
  'Гарем',
  'Детектив',
  'Драма',
  'Исекай',
  'Исторический',
  'Комедия',
  'Меха',
  'Мистика',
  'Повседневность',
  'Приключения',
  'Психология',
  'Романтика',
  'Сёдзё',
  'Сёнэн',
  'Спорт',
  'Триллер',
  'Ужасы',
  'Фантастика',
  'Фэнтези',
  'Школа',
  'Этти',
] as const;

export function formatInt(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '0';
  return numberFormatter.format(value);
}

export function formatRating(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  return value.toFixed(1).replace('.', ',');
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return dateFormatter.format(date);
}

export function formatShortDate(value: string | null | undefined): string {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return shortDateFormatter.format(date);
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return dateTimeFormatter.format(date);
}

export function formatRelative(value: string | null | undefined): string {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';

  const diffSeconds = (date.getTime() - Date.now()) / 1000;
  const absolute = Math.abs(diffSeconds);
  if (absolute < 60) return 'только что';
  if (absolute < 3600) return relativeFormatter.format(Math.round(diffSeconds / 60), 'minute');
  if (absolute < 86400) return relativeFormatter.format(Math.round(diffSeconds / 3600), 'hour');
  if (absolute < 86400 * 30) return relativeFormatter.format(Math.round(diffSeconds / 86400), 'day');
  if (absolute < 86400 * 365) return relativeFormatter.format(Math.round(diffSeconds / (86400 * 30)), 'month');
  return relativeFormatter.format(Math.round(diffSeconds / (86400 * 365)), 'year');
}

export function pluralRu(value: number, one: string, few: string, many: string): string {
  const absolute = Math.abs(value) % 100;
  const last = absolute % 10;
  if (absolute > 10 && absolute < 20) return many;
  if (last > 1 && last < 5) return few;
  if (last === 1) return one;
  return many;
}

export function chaptersLabel(count: number | null | undefined): string {
  const value = count ?? 0;
  return `${formatInt(value)} ${pluralRu(value, 'глава', 'главы', 'глав')}`;
}

export function pagesLabel(count: number | null | undefined): string {
  const value = count ?? 0;
  return `${formatInt(value)} ${pluralRu(value, 'страница', 'страницы', 'страниц')}`;
}

export function sourceLabel(code: string): string {
  return SOURCE_LABELS[code] ?? code;
}

export function statusLabel(status: string | null | undefined): string {
  if (!status) return 'Неизвестно';
  const normalized = status.trim().toLowerCase();
  return STATUS_LABELS[normalized] ?? status;
}

export function contentTypeLabel(contentType: string | null | undefined): string {
  if (!contentType) return 'Манга';
  const normalized = contentType.trim().toLowerCase();
  return CONTENT_TYPE_LABELS[normalized] ?? contentType;
}

export function chapterHeading(chapter: {
  volume: string | null;
  number: string;
  title?: string;
}): string {
  const parts: string[] = [];
  if (chapter.volume) parts.push(`Том ${chapter.volume}`);
  if (chapter.number) parts.push(`Глава ${chapter.number}`);
  return parts.join(' · ') || chapter.title || 'Глава';
}

export function chapterSecondaryTitle(chapter: {
  number: string;
  title: string;
}): string {
  const title = chapter.title?.trim();
  if (!title) return '';
  const normalizedTitle = title.toLowerCase();
  const normalizedNumber = chapter.number.toLowerCase();
  if (normalizedTitle === normalizedNumber) return '';
  if (normalizedTitle.startsWith(`глава ${normalizedNumber}`)) return '';
  if (normalizedTitle.includes(CHAPTER_TITLE_PREFIX)) return '';
  return title;
}

const CHAPTER_TITLE_PREFIX = 'том ';

export function initials(name: string | null | undefined): string {
  if (!name) return 'Г';
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return 'Г';
  if (parts.length === 1) return parts[0].slice(0, 1).toUpperCase();
  return `${parts[0].slice(0, 1)}${parts[1].slice(0, 1)}`.toUpperCase();
}

export function normalizePage(value: string | null, total: number): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return 1;
  return Math.min(Math.max(1, Math.trunc(parsed)), Math.max(1, total));
}

export function progressPercent(page: number, total: number): number {
  if (!total || total < 1) return 0;
  return Math.min(100, Math.max(0, Math.round((page / total) * 100)));
}

export function safeNextPath(raw: string | null, fallback = '/'): string {
  if (!raw) return fallback;
  if (!raw.startsWith('/') || raw.startsWith('//') || raw.startsWith('/\\')) return fallback;
  try {
    const url = new URL(raw, window.location.origin);
    if (url.origin !== window.location.origin) return fallback;
    return `${url.pathname}${url.search}${url.hash}`;
  } catch {
    return fallback;
  }
}

export function truncate(value: string, maxLength: number): string {
  if (value.length <= maxLength) return value;
  return `${value.slice(0, Math.max(0, maxLength - 1)).trimEnd()}…`;
}

export function capitalize(value: string): string {
  if (!value) return value;
  return value.slice(0, 1).toUpperCase() + value.slice(1);
}
