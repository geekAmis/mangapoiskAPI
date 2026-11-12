import { API_BASE } from './client';

export const ADMIN_TOKEN_KEY = 'mp-admin-token';
export const ADMIN_UNAUTHORIZED_EVENT = 'mp-admin-unauthorized';

export type AdminServiceCode =
  | 'parser'
  | 'catalog'
  | 'library'
  | 'media'
  | 'control'
  | 'gateway'
  | 'notifier'
  | 'replica'
  | 'comments'
  | 'scheduler';

export const ADMIN_SERVICES: Array<{ code: AdminServiceCode; label: string; defaultPort: number; http: boolean }> = [
  { code: 'parser', label: 'Parser', defaultPort: 8101, http: true },
  { code: 'catalog', label: 'Catalog', defaultPort: 8102, http: true },
  { code: 'library', label: 'Library', defaultPort: 8103, http: true },
  { code: 'media', label: 'Media', defaultPort: 8104, http: true },
  { code: 'control', label: 'Control', defaultPort: 8005, http: true },
  { code: 'gateway', label: 'Gateway', defaultPort: 8100, http: true },
  { code: 'notifier', label: 'Notifier', defaultPort: 8106, http: true },
  { code: 'replica', label: 'Replica', defaultPort: 8108, http: true },
  { code: 'comments', label: 'Comments', defaultPort: 8109, http: true },
  { code: 'scheduler', label: 'Scheduler', defaultPort: 8107, http: false },
];

export interface AdminTokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  username: string;
}

export interface AdminMe {
  username: string;
  role: string;
}

export interface AdminServiceSpec {
  code: AdminServiceCode;
  port: number;
}

export interface AdminServiceHealth {
  code: string;
  port: number;
  healthy: boolean;
  checked_at: string | null;
  last_error: string | null;
}

export interface AdminServer {
  id: string;
  name: string;
  host: string;
  public_host: string | null;
  ssh_port: number;
  username: string;
  jump_server_id: string | null;
  jump_server_name: string | null;
  bind_host: string;
  priority: number;
  is_fallback: boolean;
  is_jump: boolean;
  enabled: boolean;
  notes: string | null;
  services: AdminServiceHealth[];
  created_at: string | null;
  updated_at: string | null;
}

export interface AdminServerCreate {
  name: string;
  host: string;
  public_host?: string | null;
  ssh_port: number;
  username: string;
  password: string;
  jump_server_id?: string | null;
  bind_host: string;
  priority: number;
  is_fallback: boolean;
  is_jump: boolean;
  notes?: string | null;
  services: AdminServiceSpec[];
}

export interface AdminServerUpdate {
  name?: string;
  host?: string;
  public_host?: string | null;
  ssh_port?: number;
  username?: string;
  password?: string;
  jump_server_id?: string | null;
  bind_host?: string;
  priority?: number;
  is_fallback?: boolean;
  is_jump?: boolean;
  enabled?: boolean;
  notes?: string | null;
  services?: AdminServiceSpec[];
}

export interface AdminDeployRequest {
  services?: AdminServiceSpec[];
  update: boolean;
}

export interface AdminDeployResponse {
  job_id: string;
  status: string;
}

export interface AdminJob {
  id: string;
  server_id: string;
  status: string;
  requested: Record<string, unknown>;
  log: string;
  error: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface AdminServerHealth {
  server_id: string;
  name: string;
  host: string;
  healthy: boolean;
  services: AdminServiceHealth[];
}

export interface AdminRegistryEndpoint {
  server_id: string;
  server_name: string;
  host: string;
  port: number;
  url: string;
  healthy: boolean;
  is_fallback: boolean;
  priority?: number;
  is_jump?: boolean;
  checked_at: string | null;
  last_error: string | null;
}

export interface AdminRegistry {
  services: Record<string, AdminRegistryEndpoint[]>;
}

export interface AdminRegistrySyncResponse {
  updated: Record<string, string>;
  registry: AdminRegistry;
}

export interface AdminSourceCookie {
  source: string;
  configured: boolean;
  supported: boolean;
  updated_at: string | null;
}

export interface AdminComment {
  id: string;
  manga_id: string;
  user_id: string;
  user_name: string;
  body: string;
  spoiler: boolean;
  status: string;
  report_count: number;
  created_at: string;
}

export interface AdminCommentPage {
  items: AdminComment[];
  total: number;
  page: number;
  limit: number;
  has_next: boolean;
}

export interface AdminCommentReport {
  id: string;
  comment_id: string;
  reporter_id: string;
  reason: string;
  status: string;
  created_at: string;
  comment: AdminComment | null;
}

export interface AdminCatalogueState {
  source: string;
  mode: string;
  page: number;
  status: string;
  last_error: string | null;
  next_run_at: string | null;
  last_success_at: string | null;
  failure_count: number;
  failure_kind: string | null;
}

export interface AdminCatalogueHealth {
  stats: {
    manga: number;
    chapters: number;
    pending_enrichment: number;
    retrying_enrichment: number;
    sources: Array<{ source: string; manga: number; chapters: number }>;
  };
  enrichment: {
    total: number;
    pending: number;
    retrying: number;
    failed: number;
    oldest_pending_at: string | null;
    last_success_at: string | null;
    estimated_seconds: number;
    sources: Array<{
      source: string;
      total: number;
      pending: number;
      retrying: number;
      failed: number;
      last_success_at: string | null;
    }>;
  };
  crawl_states: AdminCatalogueState[];
}

export interface AdminAuditEntry {
  id: string;
  action: string;
  server_id: string | null;
  details: Record<string, unknown>;
  created_at: string | null;
}

export interface AdminCrawlState {
  source: string;
  mode: 'full' | 'incremental';
  status: 'pending' | 'running' | 'completed' | 'failed' | string;
  page: number;
  total_pages: number | null;
  items_seen: number;
  items_imported: number;
  eta_seconds: number | null;
  last_error: string | null;
  last_run_at: string | null;
  next_run_at: string | null;
}

export interface AdminCrawlerSource {
  source: string;
  manga: number;
  chapters: number;
  pending: number;
  full: AdminCrawlState | null;
  incremental: AdminCrawlState | null;
  progress_percent: number | null;
  eta_seconds: number | null;
}

export interface AdminCrawlerArchive {
  total: number;
  done: number;
  failed: number;
  pending: number;
  done_bytes: number;
  db_bytes: number;
  cap_bytes: number;
  usage_percent: number;
}

export interface AdminCrawlerStatus {
  generated_at: string;
  catalog_manga: number;
  catalog_chapters: number;
  enrichment_pending: number;
  sources: AdminCrawlerSource[];
  archive: AdminCrawlerArchive;
  image_cache_bytes: number;
  image_cache_files: number;
  warnings: string[];
}

export type AdminStorageLevel = 'ok' | 'warning' | 'critical' | 'unbounded';

export interface AdminImageCacheStats {
  used_bytes: number;
  cap_bytes: number;
  files: number;
  evictions: number;
  last_pruned_at: string | null;
  usage_percent: number;
  level: AdminStorageLevel;
}

export interface AdminArchiveStats {
  total: number;
  done: number;
  failed: number;
  pending: number;
  done_bytes: number;
  db_bytes: number;
  cap_bytes: number;
  evictions: number;
  last_pruned_at: string | null;
  usage_percent: number;
  level: AdminStorageLevel;
}

export interface AdminMediaStats {
  generated_at: string;
  image_cache: AdminImageCacheStats;
  archives: AdminArchiveStats;
  warnings: string[];
}

export type AdProviderType =
  | 'yandex'
  | 'adfox'
  | 'google'
  | 'custom_html'
  | 'custom_script';

export type AdPlacement =
  | 'header'
  | 'sidebar'
  | 'in-feed'
  | 'post-chapter'
  | 'mobile-sticky';

export type AdAudience = 'guest' | 'authenticated' | 'both';

export interface AdminAdSecret {
  name: string;
  configured: boolean;
  hint: string;
  updated_at: string | null;
}

export interface AdminAdProvider {
  id: string;
  name: string;
  type: AdProviderType;
  enabled: boolean;
  priority: number;
  placement: AdPlacement;
  audience: AdAudience;
  frequency_cap: number;
  format: string;
  width: number | null;
  height: number | null;
  schedule_days: number[];
  schedule_start: string;
  schedule_end: string;
  timezone: string;
  config: Record<string, unknown>;
  custom_html: string;
  custom_script: string;
  exclude_adult: boolean;
  hide_for_donors: boolean;
  require_consent: boolean;
  secrets: AdminAdSecret[];
  created_at: string | null;
  updated_at: string | null;
}

export interface AdminAdProviderInput {
  name: string;
  type: AdProviderType;
  enabled: boolean;
  priority: number;
  placement: AdPlacement;
  audience: AdAudience;
  frequency_cap: number;
  format: string;
  width: number | null;
  height: number | null;
  schedule_days: number[];
  schedule_start: string;
  schedule_end: string;
  timezone: string;
  config: Record<string, unknown>;
  custom_html: string;
  custom_script: string;
  exclude_adult: boolean;
  hide_for_donors: boolean;
  require_consent: boolean;
}
export class AdminApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: unknown;

  constructor(status: number, code: string, message: string, details: unknown = null) {
    super(message);
    this.name = 'AdminApiError';
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export function getAdminToken(): string | null {
  try {
    return window.sessionStorage.getItem(ADMIN_TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setAdminToken(token: string | null): void {
  try {
    if (token) window.sessionStorage.setItem(ADMIN_TOKEN_KEY, token);
    else window.sessionStorage.removeItem(ADMIN_TOKEN_KEY);
  } catch {
    /* приватный режим: токен останется только в состоянии вкладки */
  }
}

let unauthorizedDispatchedAt = 0;

function unauthorized(message = 'Сессия администратора истекла. Войдите снова.') {
  setAdminToken(null);
  const now = Date.now();
  if (now - unauthorizedDispatchedAt > 1500) {
    unauthorizedDispatchedAt = now;
    window.dispatchEvent(new CustomEvent(ADMIN_UNAUTHORIZED_EVENT, { detail: message }));
  }
  return new AdminApiError(401, 'unauthorized', message, null);
}

function buildAdminUrl(path: string): string {
  const normalized = path.startsWith('/') ? path : `/${path}`;
  return `${API_BASE}/admin${normalized}`;
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

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function errorFromResponse(response: Response, body: unknown): AdminApiError {
  if (isRecord(body) && isRecord(body.error) && typeof body.error.code === 'string') {
    const message = typeof body.error.message === 'string' ? body.error.message : `Ошибка ${response.status}`;
    return new AdminApiError(response.status, body.error.code, message, body.error.details);
  }
  return new AdminApiError(response.status, 'http_error', `Ошибка запроса (${response.status})`, null);
}

async function adminRequest<T>(
  path: string,
  options: {
    method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
    body?: unknown;
    formData?: FormData;
    auth?: boolean;
    signal?: AbortSignal;
  } = {},
): Promise<T> {
  const { method = 'GET', body, formData, auth = true, signal } = options;
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (body !== undefined && !formData) headers['Content-Type'] = 'application/json';

  let requestToken: string | null = null;
  if (auth) {
    requestToken = getAdminToken();
    if (!requestToken) throw unauthorized('Требуется вход в панель администратора.');
    headers.Authorization = `Bearer ${requestToken}`;
  }

  let response: Response;
  try {
    response = await fetch(buildAdminUrl(path), {
      method,
      body: formData ?? (body === undefined ? undefined : JSON.stringify(body)),
      headers,
      credentials: 'same-origin',
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new AdminApiError(0, 'network', 'Нет соединения с сервером.', null);
  }

  const data = await readBody(response);

  if (response.status === 401 && auth) {
    const currentToken = getAdminToken();
    if (!requestToken || !currentToken || currentToken === requestToken) {
      throw unauthorized();
    }
    throw errorFromResponse(response, data);
  }
  if (!response.ok) {
    throw errorFromResponse(response, data);
  }
  return data as T;
}

export const adminApi = {
  login: (username: string, password: string) =>
    adminRequest<AdminTokenResponse>('/login', {
      method: 'POST',
      body: { username, password },
      auth: false,
    }),

  me: (signal?: AbortSignal) => adminRequest<AdminMe>('/me', { signal }),

  getMediaStats: (signal?: AbortSignal) =>
    adminRequest<AdminMediaStats>('/media/stats', { signal }),
  getCrawlerStatus: (signal?: AbortSignal) =>
    adminRequest<AdminCrawlerStatus>('/crawl', { signal }),

  listServers: (signal?: AbortSignal) => adminRequest<AdminServer[]>('/servers', { signal }),

  createServer: (payload: AdminServerCreate) =>
    adminRequest<AdminServer>('/servers', { method: 'POST', body: payload }),

  updateServer: (id: string, payload: AdminServerUpdate) =>
    adminRequest<AdminServer>(`/servers/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      body: payload,
    }),

  deleteServer: (id: string) =>
    adminRequest<{ ok: boolean }>(`/servers/${encodeURIComponent(id)}`, { method: 'DELETE' }),

  deployServer: (id: string, payload: AdminDeployRequest) =>
    adminRequest<AdminDeployResponse>(`/servers/${encodeURIComponent(id)}/deploy`, {
      method: 'POST',
      body: payload,
    }),

  getJob: (id: string, signal?: AbortSignal) =>
    adminRequest<AdminJob>(`/jobs/${encodeURIComponent(id)}`, { signal }),

  getServerHealth: (id: string, signal?: AbortSignal) =>
    adminRequest<AdminServerHealth>(`/servers/${encodeURIComponent(id)}/health`, { signal }),

  promoteReplica: (id: string) =>
    adminRequest<{ ok: boolean; log: string }>(`/servers/${encodeURIComponent(id)}/replica/promote`, {
      method: 'POST',
    }),

  bootstrapReplica: (id: string, sourceServerId: string) =>
    adminRequest<{ ok: boolean; log: string }>(`/servers/${encodeURIComponent(id)}/replica/bootstrap`, {
      method: 'POST',
      body: { source_server_id: sourceServerId },
    }),

  getRegistry: (signal?: AbortSignal) => adminRequest<AdminRegistry>('/registry', { signal }),

  getCatalogueHealth: (signal?: AbortSignal) =>
    adminRequest<AdminCatalogueHealth>('/catalogue', { signal }),

  getSourceCookie: (code: string, signal?: AbortSignal) =>
    adminRequest<AdminSourceCookie>(`/sources/${encodeURIComponent(code)}/cookie`, { signal }),

  setSourceCookie: (code: string, cookie: string) =>
    adminRequest<AdminSourceCookie>(`/sources/${encodeURIComponent(code)}/cookie`, {
      method: 'PUT',
      body: { cookie },
    }),

  importSourceCookieHar: (code: string, file: File) => {
    const form = new FormData();
    form.append('file', file, file.name);
    return adminRequest<AdminSourceCookie>(
      `/sources/${encodeURIComponent(code)}/cookie/har`,
      { method: 'POST', formData: form },
    );
  },

  getReportedComments: (signal?: AbortSignal) =>
    adminRequest<AdminCommentPage>('/comments?reported=true&limit=50', { signal }),

  moderateComment: (id: string, action: 'hide' | 'restore') =>
    adminRequest<AdminComment>(`/comments/${encodeURIComponent(id)}/${action}`, { method: 'POST' }),

  getCommentReports: (status: 'open' | 'resolved' | 'dismissed' = 'open', signal?: AbortSignal) =>
    adminRequest<{ items: AdminCommentReport[]; total: number }>(
      `/comment-reports?status=${status}&limit=50`,
      { signal },
    ),

  resolveCommentReport: (id: string, status: 'resolved' | 'dismissed') =>
    adminRequest<AdminCommentReport>(`/comment-reports/${encodeURIComponent(id)}/resolve`, {
      method: 'POST',
      body: { status },
    }),

  syncRegistry: () =>
    adminRequest<AdminRegistrySyncResponse>('/registry/sync', { method: 'POST' }),

  failover: () => adminRequest<AdminRegistrySyncResponse>('/failover', { method: 'POST' }),

  getAudit: (limit = 100, signal?: AbortSignal) =>
    adminRequest<AdminAuditEntry[]>(`/audit?limit=${encodeURIComponent(String(limit))}`, { signal }),

  listAds: (signal?: AbortSignal) => adminRequest<AdminAdProvider[]>('/ads', { signal }),

  createAd: (payload: AdminAdProviderInput) =>
    adminRequest<AdminAdProvider>('/ads', { method: 'POST', body: payload }),

  updateAd: (id: string, payload: Partial<AdminAdProviderInput>) =>
    adminRequest<AdminAdProvider>(`/ads/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      body: payload,
    }),

  deleteAd: (id: string) =>
    adminRequest<{ ok: boolean }>(`/ads/${encodeURIComponent(id)}`, { method: 'DELETE' }),

  setAdSecret: (id: string, name: string, value: string) =>
    adminRequest<AdminAdSecret>(
      `/ads/${encodeURIComponent(id)}/secrets/${encodeURIComponent(name)}`,
      { method: 'PUT', body: { value } },
    ),

  deleteAdSecret: (id: string, name: string) =>
    adminRequest<{ ok: boolean }>(
      `/ads/${encodeURIComponent(id)}/secrets/${encodeURIComponent(name)}`,
      { method: 'DELETE' },
    ),
};

export function adminErrorMessage(error: unknown, fallback = 'Не удалось выполнить действие.'): string {
  if (!(error instanceof AdminApiError)) return fallback;
  const adminError = error;

  if (adminError.status === 0) return 'Нет соединения с сервером. Проверьте сеть и повторите.';
  if (adminError.status === 401) return 'Сессия администратора истекла. Войдите снова.';
  if (adminError.status === 403) return 'Недостаточно прав для этого действия.';
  if (adminError.status === 404) return 'Сервер или задача не найдены.';
  if (adminError.status === 409) return 'Конфликт данных: проверьте имя, хост и порты.';
  if (adminError.status === 422) return 'Проверьте заполнение полей: сервер отклонил данные.';
  if (adminError.status === 429) return 'Слишком много запросов. Подождите немного.';
  if (adminError.status >= 500) return 'Control-сервис временно недоступен. Повторите позже.';
  if (adminError.code === 'admin_invalid') return 'Неверный логин или пароль.';
  return fallback;
}

export function isAdminUnauthorized(error: unknown): boolean {
  return error instanceof AdminApiError && error.status === 401;
}

/** Приводит технический last_error health-check к короткой русской формулировке. */
export function healthErrorText(error: string | null): string {
  if (!error) return '';
  const normalized = error.toLowerCase();
  if (normalized.includes('all connection attempts failed') || normalized.includes('connection refused')) {
    return 'Нет соединения с сервисом';
  }
  if (normalized.includes('timed out') || normalized.includes('timeout')) {
    return 'Сервис не ответил вовремя';
  }
  if (normalized.includes('unauthorized') || normalized.includes('401')) {
    return 'Сервис требует авторизации';
  }
  if (normalized.includes('not found') || normalized.includes('404')) {
    return 'Health endpoint не найден';
  }
  return error.length > 120 ? `${error.slice(0, 119)}…` : error;
}
