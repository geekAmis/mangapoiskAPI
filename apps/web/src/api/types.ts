/**
 * Типы публичного API v1.
 * Источник истины — docs/API.md и packages/manga_common/manga_common/schemas.py.
 * Имена полей намеренно повторяют snake_case контракт.
 */

export type UUID = string;

export type MangaSort = 'popular' | 'rating' | 'updated' | 'title';
export type MangaStatus = 'ongoing' | 'completed' | 'hiatus' | 'announced' | 'cancelled' | 'unknown';
export type ReaderMode = 'vertical' | 'horizontal' | 'webtoon';
export type PageFit = 'width' | 'height' | 'original';

export interface SourceOut {
  code: string;
  name: string;
  base_url: string;
  language: string;
  enabled: boolean;
  requires_cookies: boolean;
  capabilities: Record<string, boolean>;
}

export interface PageOut {
  number: number;
  url: string;
  width: number | null;
  height: number | null;
}

export interface ChapterOut {
  id: UUID;
  manga_id: UUID;
  source: string;
  source_id: string;
  volume: string | null;
  number: string;
  title: string;
  published_at: string | null;
  page_count: number;
  url: string | null;
  is_external: boolean;
  /** Перевод/команда, выпустившая главу. Может отсутствовать у старых ответов API. */
  translator?: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface ChapterDetailOut extends ChapterOut {
  pages: PageOut[];
  prev_chapter_id: UUID | null;
  next_chapter_id: UUID | null;
  is_horizontal: boolean;
}

export interface MangaOut {
  id: UUID;
  source: string;
  source_id: string;
  slug: string | null;
  title: string;
  title_en: string | null;
  title_alt: string | null;
  description: string | null;
  year: number | null;
  status: string | null;
  content_type: string | null;
  rating: number | null;
  rating_count: number | null;
  poster_url: string | null;
  adult: boolean;
  genres: string[];
  chapters_count: number;
  last_chapter_at: string | null;
  last_synced_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface MangaDetailOut extends MangaOut {
  chapters: ChapterOut[];
}

export interface TranslatorOut {
  name: string;
  count: number;
}

/**
 * Второй (и далее) каталожный источник для того же тайтла.
 * `/manga/{id}/variants` склеивает записи разных источников в одну группу.
 */
export interface MangaVariantOut {
  id: UUID;
  title: string;
  source: string;
  source_id: string;
  chapters_count: number;
  poster_url: string | null;
  rating: number | null;
  translators: TranslatorOut[];
}

export interface MangaVariantsOut {
  primary_id: UUID;
  items: MangaVariantOut[];
}

export interface Paginated<T> {
  items: T[];
  total: number;
  page: number;
  limit: number;
  has_next: boolean;
}

export interface SearchResponse extends Paginated<MangaOut> {
  live: boolean;
}

export interface ImportMangaRequest {
  source: string;
  url?: string;
  source_id?: string;
  refresh?: boolean;
}

export interface ImportMangaResponse {
  manga: MangaDetailOut;
  imported_chapters: number;
  imported_pages: number;
  source: string;
}

export interface UserOut {
  id: UUID;
  email: string;
  display_name: string;
  role: string;
  created_at: string | null;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  user: UserOut;
}

export interface RegisterRequest {
  email: string;
  password: string;
  display_name: string;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface BookmarkOut {
  id: UUID;
  manga_id: UUID;
  created_at: string;
  manga: MangaOut | null;
}

export interface BookmarkCreate {
  manga_id: UUID;
}

export interface ProgressOut {
  manga_id: UUID;
  chapter_id: UUID;
  page: number;
  total_pages: number;
  updated_at: string;
  manga: MangaOut | null;
  chapter: ChapterOut | null;
}

export type HistoryItem = ProgressOut;

export interface ProgressUpsert {
  manga_id: UUID;
  chapter_id: UUID;
  page: number;
  total_pages: number;
}

export interface ReaderSettings {
  theme: string;
  reader_mode: ReaderMode;
  page_fit: string;
  auto_scroll: boolean;
  auto_scroll_speed: number;
  show_page_numbers: boolean;
  blur_adult_posters: boolean;
}

export interface HealthOut {
  status: string;
  service: string;
  version: string;
  checks: Record<string, unknown>;
}

export interface OkResponse {
  ok: boolean;
  message: string | null;
}

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details: unknown;
  };
}

export interface MangaListParams {
  query?: string;
  source?: string;
  genre?: string;
  year?: number;
  status?: string;
  sort?: MangaSort;
  page?: number;
  limit?: number;
}

export interface MangaSearchParams {
  q: string;
  source?: string;
  live?: boolean;
  page?: number;
  limit?: number;
}

export interface ChapterListParams {
  page?: number;
  limit?: number;
}

/**
 * Часть эндпоинтов библиотеки в контракте описана как «list», без явной
 * обёртки Paginated. Клиент принимает оба варианта, чтобы одинаково работать
 * с gateway-реализацией и прямым ответом library-сервиса.
 */
export type ItemList<T> = T[] | Paginated<T>;
