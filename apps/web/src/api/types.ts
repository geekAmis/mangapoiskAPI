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

export interface CoverOut {
  id: UUID | null;
  source: string;
  source_id: string;
  url: string;
  rating: number | null;
  quality: number | null;
  chapters_count: number;
  updated_at: string | null;
  is_primary: boolean;
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
  description_missing?: boolean;
  description_fallback?: string | null;
  year: number | null;
  status: string | null;
  content_type: string | null;
  rating: number | null;
  rating_count: number | null;
  poster_url: string | null;
  adult: boolean;
  genres: string[];
  genre_slugs?: string[];
  covers?: CoverOut[];
  /** Public page of the title on its source, when known. */
  url?: string | null;
  chapters_count: number;
  last_chapter_at: string | null;
  last_synced_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface MangaDetailOut extends MangaOut {
  chapters: ChapterOut[];
}

export interface HomeUpdateOut {
  manga_id: UUID;
  manga_title: string;
  poster_url: string | null;
  source: string;
  chapter_id: UUID;
  chapter_number: string;
  chapter_volume: string | null;
  chapter_title: string;
  published_at: string | null;
  added_at: string | null;
}

export interface HomeUpdatesOut {
  items: HomeUpdateOut[];
  total: number;
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

export type SearchSuggestionReason = 'title' | 'alternative' | 'genre' | 'description';

/** Instant local suggestion; no upstream/parser request is involved. */
export interface SearchSuggestionOut {
  id: UUID;
  title: string;
  title_en: string | null;
  poster_url: string | null;
  year: number | null;
  source: string;
  reason: SearchSuggestionReason;
}

export interface SuggestResponse {
  query: string;
  items: SearchSuggestionOut[];
  total: number;
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

export interface ProgressMergeItem {
  manga_id: UUID;
  chapter_id: UUID;
  page: number;
  total_pages: number;
  read_at: string;
}

export interface ProgressMergeOut {
  merged: number;
  unchanged: number;
  ignored: number;
}

export interface StreakOut {
  current: number;
  longest: number;
  read_today: boolean;
  timezone: string;
  last_read_on: string | null;
  days: string[];
}

export type ProfileEventKind = 'chapter_read' | 'title_finished' | 'achievement';

export interface RankOut {
  code: string;
  label: string;
  min_level: number;
}

export interface ProfilePrivacyOut {
  is_private: boolean;
  show_stats: boolean;
  show_events: boolean;
  show_achievements: boolean;
  indexable: boolean;
}

export interface AchievementOut {
  code: string;
  title: string;
  description: string;
  icon: string;
  unlocked: boolean;
  /** Owner-only exact unlock moment. Guests receive only `unlocked_on`. */
  unlocked_at: string | null;
  unlocked_on: string | null;
  progress: number;
  target: number;
}

export interface ProfileStatsOut {
  chapters_read: number;
  titles_read: number;
  finished_titles: number;
  reading_days: number;
  current_streak: number;
  longest_streak: number;
}

export interface GenreCountOut {
  genre: string;
  count: number;
}

export interface ProfileEventOut {
  id: UUID;
  kind: ProfileEventKind;
  title: string;
  subtitle: string | null;
  manga_id: UUID | null;
  chapter_id: UUID | null;
  poster_url: string | null;
  achievement_code: string | null;
  /** Date-only on public cards; exact `created_at` is owner-only. */
  occurred_on: string;
  created_at: string | null;
}

export interface PublicProfileOut {
  username: string;
  display_name: string;
  bio: string;
  joined_at: string;
  level: number;
  xp: number;
  xp_into_level: number;
  xp_for_next_level: number;
  level_progress: number;
  rank: RankOut;
  next_rank: RankOut | null;
  avatar_initials: string;
  privacy: ProfilePrivacyOut;
  indexable: boolean;
  is_owner: boolean;
  stats: ProfileStatsOut | null;
  favorite_genres: GenreCountOut[];
  achievements: AchievementOut[];
  achievements_unlocked: number;
  achievements_total: number;
  achievements_hidden: boolean;
  events: ProfileEventOut[];
  events_hidden: boolean;
}

export interface MyProfileOut extends PublicProfileOut {}

export interface ProfileUpdate {
  display_name?: string;
  username?: string;
  bio?: string;
  is_private?: boolean;
  show_stats?: boolean;
  show_events?: boolean;
  show_achievements?: boolean;
  indexable?: boolean;
}

export interface ProfileReportOut {
  id: UUID;
  status: string;
  created_at: string;
  message: string;
}

export interface RecommendationListOut {
  items: MangaOut[];
  strategy: 'personalized' | 'popular' | 'related';
}

export interface RelatedMangaOut {
  series: MangaOut[];
  related: MangaOut[];
  /** Heuristic shelf: genres, rating, year, type and chapter-count closeness. */
  similar: MangaOut[];
}

export type CollectionKind = 'smart' | 'manual';
export type CollectionRule = 'weekly_best' | 'beginners' | 'completed' | 'short' | 'new';

export interface CollectionOut {
  id: UUID;
  slug: string;
  title: string;
  description: string;
  kind: CollectionKind;
  rule: CollectionRule | null;
  enabled: boolean;
  position: number;
  limit: number;
  item_count: number;
  items: MangaOut[];
  created_at: string | null;
  updated_at: string | null;
}

export interface CollectionListOut {
  items: CollectionOut[];
  total: number;
}

export interface CollectionAuditOut {
  id: UUID;
  action: string;
  collection_id: UUID | null;
  details: Record<string, unknown>;
  created_at: string | null;
}

export interface AnalyticsSurfaceOut {
  surface: string;
  impressions: number;
  clicks: number;
  ctr: number;
}

export interface AnalyticsSurfacesOut {
  days: number;
  generated_at: string;
  items: AnalyticsSurfaceOut[];
}

export type AnalyticsEventName =
  | 'impression'
  | 'click'
  | 'read_start'
  | 'read_complete'
  | 'finish';

export interface AnalyticsEventIn {
  event: AnalyticsEventName;
  dedupe_key: string;
  client_id: string;
  surface: string;
  manga_id?: UUID | null;
  chapter_id?: UUID | null;
}

export interface AnalyticsEventsIn {
  events: AnalyticsEventIn[];
}

export interface AnalyticsIngestOut {
  accepted: number;
  duplicates: number;
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
  genres?: string;
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
