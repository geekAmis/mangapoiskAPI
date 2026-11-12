import { useAuthStore } from '../stores/auth';
import type {
  ApiErrorBody,
  BookmarkOut,
  ChapterDetailOut,
  ChapterListParams,
  ChapterOut,
  HealthOut,
  ImportMangaRequest,
  ImportMangaResponse,
  ItemList,
  LoginRequest,
  MangaDetailOut,
  MangaListParams,
  MangaOut,
  MangaSearchParams,
  MangaVariantsOut,
  OkResponse,
  PageOut,
  Paginated,
  ProgressOut,
  ProgressUpsert,
  ReaderSettings,
  RegisterRequest,
  SearchResponse,
  SourceOut,
  TokenPair,
  UserOut,
} from './types';

const configuredBase = import.meta.env.VITE_API_BASE?.trim();
export const API_BASE = (configuredBase || '/api/v1').replace(/\/+$/, '');

type QueryValue = string | number | boolean | null | undefined;

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  body?: unknown;
  query?: Record<string, QueryValue>;
  auth?: boolean;
  skipRefresh?: boolean;
  signal?: AbortSignal;
  headers?: Record<string, string>;
  /** Служебный флаг: повтор после обновления access-токена уже был. */
  retried?: boolean;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: unknown;

  constructor(status: number, code: string, message: string, details: unknown = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export function isApiError(value: unknown): value is ApiError {
  return value instanceof ApiError;
}

/* ------------------------------------------------------------------ */
/* Подготовка глав на сервере                                          */
/* ------------------------------------------------------------------ */

export type PrepareChapterStatus = 'done' | 'pending' | 'error';

export interface PrepareChapterState {
  id: string;
  status: PrepareChapterStatus;
  page_count: number;
  error: string | null;
}

export interface PrepareStatusOut {
  manga_id: string;
  total: number;
  prepared: number;
  pending: number;
  failed: number;
  /** Первые до пяти подготовленных глав — информационное поле. */
  batch: string[];
  chapters: PrepareChapterState[];
  job_id?: string | null;
  error?: string | null;
}

export interface PrepareStartOut {
  job_id: string;
  total: number;
  chapter_ids: string[];
}

function buildUrl(path: string, query?: Record<string, QueryValue>): string {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  const base = `${API_BASE}${normalizedPath}`;
  if (!query) return base;

  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === '') continue;
    params.set(key, String(value));
  }
  const queryString = params.toString();
  return queryString ? `${base}?${queryString}` : base;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function isApiErrorBody(value: unknown): value is ApiErrorBody {
  if (!isRecord(value) || !isRecord(value.error)) return false;
  return typeof value.error.code === 'string' && typeof value.error.message === 'string';
}

async function readBody(response: Response): Promise<unknown> {
  if (response.status === 204) return null;
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}

function errorFromResponse(response: Response, body: unknown): ApiError {
  if (isApiErrorBody(body)) {
    return new ApiError(response.status, body.error.code, body.error.message, body.error.details);
  }
  const fallback = response.statusText || `Ошибка запроса (${response.status})`;
  return new ApiError(response.status, 'http_error', fallback, null);
}

let refreshPromise: Promise<TokenPair> | null = null;

async function refreshSession(): Promise<TokenPair> {
  const refreshToken = useAuthStore.getState().refreshToken;
  if (!refreshToken) {
    throw new ApiError(401, 'unauthorized', 'Сессия истекла. Войдите снова.', null);
  }

  if (!refreshPromise) {
    refreshPromise = request<TokenPair>('/auth/refresh', {
      method: 'POST',
      body: { refresh_token: refreshToken },
      auth: false,
      skipRefresh: true,
    })
      .then((pair) => {
        useAuthStore.getState().setSession(pair);
        return pair;
      })
      .catch((error: unknown) => {
        if (error instanceof ApiError && error.status >= 400 && error.status < 500 && error.status !== 429) {
          useAuthStore.getState().clear();
        }
        throw error;
      })
      .finally(() => {
        refreshPromise = null;
      });
  }

  return refreshPromise;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const {
    method = 'GET',
    body,
    query,
    auth = true,
    skipRefresh = false,
    signal,
    headers = {},
    retried = false,
  } = options;

  const requestHeaders: Record<string, string> = {
    Accept: 'application/json',
    ...headers,
  };

  if (body !== undefined) {
    requestHeaders['Content-Type'] = 'application/json';
  }

  if (auth) {
    const token = useAuthStore.getState().accessToken;
    if (token) requestHeaders.Authorization = `Bearer ${token}`;
  }

  let response: Response;
  try {
    response = await fetch(buildUrl(path, query), {
      method,
      body: body === undefined ? undefined : JSON.stringify(body),
      headers: requestHeaders,
      signal,
      credentials: 'same-origin',
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new ApiError(
      0,
      'network',
      'Нет соединения с сервером. Проверьте интернет и попробуйте снова.',
      null,
    );
  }

  if (response.status === 401 && auth && !skipRefresh && !retried) {
    try {
      await refreshSession();
      return await request<T>(path, { ...options, retried: true });
    } catch (refreshError) {
      if (refreshError instanceof ApiError && refreshError.status === 0) throw refreshError;
      const originalBody = await readBody(response).catch(() => null);
      throw errorFromResponse(response, originalBody);
    }
  }

  const data = await readBody(response);

  if (!response.ok) {
    throw errorFromResponse(response, data);
  }

  return data as T;
}

/** Разворачивает список, который gateway может вернуть массивом или Paginated. */
export function listItems<T>(value: ItemList<T> | null | undefined): T[] {
  if (!value) return [];
  if (Array.isArray(value)) return value;
  return Array.isArray(value.items) ? value.items : [];
}

/** Приводит относительный URL из API к адресу, пригодному для ссылки/скачивания. */
export function resolveApiUrl(url: string): string {
  if (/^[a-z][a-z0-9+.-]*:/i.test(url) || url.startsWith('//')) return url;
  if (url.startsWith('/')) {
    if (/^https?:\/\//i.test(API_BASE)) {
      try {
        return new URL(url, API_BASE).toString();
      } catch {
        return url;
      }
    }
    return url;
  }
  return `${API_BASE}/${url.replace(/^\.?\//, '')}`;
}

export const api = {
  health: (signal?: AbortSignal) =>
    request<HealthOut>('/health', { auth: false, signal }),

  sources: (signal?: AbortSignal) =>
    request<SourceOut[]>('/sources', { auth: false, signal }),

  listManga: (params: MangaListParams, signal?: AbortSignal) =>
    request<Paginated<MangaOut>>('/manga', {
      query: {
        query: params.query,
        source: params.source,
        genre: params.genre,
        year: params.year,
        status: params.status,
        sort: params.sort,
        page: params.page,
        limit: params.limit,
      },
      auth: false,
      signal,
    }),

  searchManga: (params: MangaSearchParams, signal?: AbortSignal) =>
    request<SearchResponse>('/manga/search', {
      query: {
        q: params.q,
        source: params.source,
        live: params.live,
        page: params.page,
        limit: params.limit,
      },
      auth: false,
      signal,
    }),

  getManga: (id: string, signal?: AbortSignal) =>
    request<MangaDetailOut>(`/manga/${encodeURIComponent(id)}`, { auth: false, signal }),

  /** Группа каталожных записей одного тайтла из разных источников. */
  getMangaVariants: (id: string, signal?: AbortSignal) =>
    request<MangaVariantsOut>(`/manga/${encodeURIComponent(id)}/variants`, {
      auth: false,
      signal,
    }),

  getMangaChapters: (id: string, params: ChapterListParams = {}, signal?: AbortSignal) =>
    request<ItemList<ChapterOut>>(`/manga/${encodeURIComponent(id)}/chapters`, {
      query: { page: params.page, limit: params.limit },
      auth: false,
      signal,
    }),

  importManga: (body: ImportMangaRequest) =>
    request<ImportMangaResponse>('/manga/import', {
      method: 'POST',
      body,
      auth: false,
    }),

  getChapter: (id: string, signal?: AbortSignal) =>
    request<ChapterDetailOut>(`/chapters/${encodeURIComponent(id)}`, { auth: false, signal }),

  getChapterPages: (id: string, signal?: AbortSignal) =>
    request<PageOut[]>(`/chapters/${encodeURIComponent(id)}/pages`, { auth: false, signal }),

  chapterImageUrl: (chapterId: string, pageNumber: number) =>
    buildUrl(
      `/chapters/${encodeURIComponent(chapterId)}/images/${encodeURIComponent(String(pageNumber))}`,
    ),

  prepareManga: (mangaId: string) =>
    request<PrepareStartOut>(`/manga/${encodeURIComponent(mangaId)}/prepare`, {
      method: 'POST',
    }),

  getPrepareStatus: (mangaId: string, signal?: AbortSignal) =>
    request<PrepareStatusOut>(`/manga/${encodeURIComponent(mangaId)}/prepare`, { signal }),

  register: (body: RegisterRequest) =>
    request<TokenPair>('/auth/register', { method: 'POST', body, auth: false, skipRefresh: true }),

  login: (body: LoginRequest) =>
    request<TokenPair>('/auth/login', { method: 'POST', body, auth: false, skipRefresh: true }),

  refresh: (refreshToken: string) =>
    request<TokenPair>('/auth/refresh', {
      method: 'POST',
      body: { refresh_token: refreshToken },
      auth: false,
      skipRefresh: true,
    }),

  logout: (refreshToken: string) =>
    request<OkResponse>('/auth/logout', {
      method: 'POST',
      body: { refresh_token: refreshToken },
      auth: false,
      skipRefresh: true,
    }),

  me: (signal?: AbortSignal) => request<UserOut>('/auth/me', { auth: true, signal }),

  getBookmarks: (signal?: AbortSignal) =>
    request<ItemList<BookmarkOut>>('/library/bookmarks', { auth: true, signal }),

  addBookmark: (mangaId: string) =>
    request<BookmarkOut>('/library/bookmarks', {
      method: 'POST',
      body: { manga_id: mangaId },
      auth: true,
    }),

  removeBookmark: (mangaId: string) =>
    request<OkResponse>(`/library/bookmarks/${encodeURIComponent(mangaId)}`, {
      method: 'DELETE',
      auth: true,
    }),

  getProgress: (signal?: AbortSignal) =>
    request<ItemList<ProgressOut>>('/library/progress', { auth: true, signal }),

  upsertProgress: (body: ProgressUpsert) =>
    request<ProgressOut>('/library/progress', { method: 'PUT', body, auth: true }),

  getHistory: (limit = 50, signal?: AbortSignal) =>
    request<ItemList<ProgressOut>>('/library/history', {
      query: { limit },
      auth: true,
      signal,
    }),

  resetProgress: (mangaId: string) =>
    request<OkResponse>(`/library/progress/${encodeURIComponent(mangaId)}`, {
      method: 'DELETE',
      auth: true,
    }),

  getSettings: (signal?: AbortSignal) =>
    request<ReaderSettings>('/library/settings', { auth: true, signal }),

  putSettings: (settings: ReaderSettings) =>
    request<ReaderSettings>('/library/settings', {
      method: 'PUT',
      body: settings,
      auth: true,
    }),
};
