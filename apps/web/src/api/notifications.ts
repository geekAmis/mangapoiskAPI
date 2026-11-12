import { API_BASE } from './client';
import { useAuthStore } from '../stores/auth';

export interface TitleFollow {
  manga_id: string;
  manga_title: string;
  poster_url: string | null;
  source: string | null;
  created_at: string;
}

export interface FollowStatus {
  manga_id: string;
  following: boolean;
}

export interface NotificationSettings {
  in_app_enabled: boolean;
  web_push_enabled: boolean;
  max_pushes_per_hour: number;
  quiet_hours_start: number | null;
  quiet_hours_end: number | null;
  updated_at: string;
}

export interface PushConfig {
  enabled: boolean;
  public_key: string | null;
  reason: string | null;
}

export interface PushStatus {
  subscribed: boolean;
  count: number;
  endpoints: Array<{ host: string | null; created_at: string }>;
}

export class NotificationsApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = 'NotificationsApiError';
    this.status = status;
  }
}

function authHeaders(): Record<string, string> {
  const token = useAuthStore.getState().accessToken;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    Accept: 'application/json',
    ...(options.body ? { 'Content-Type': 'application/json' } : {}),
    ...authHeaders(),
    ...(options.headers as Record<string, string> | undefined),
  };
  const response = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (response.status === 204) return undefined as T;
  const data = (await response.json().catch(() => null)) as
    | { error?: { message?: string } }
    | T
    | null;
  if (!response.ok) {
    const message =
      data && typeof data === 'object' && 'error' in data && data.error?.message
        ? data.error.message
        : `Ошибка ${response.status}`;
    throw new NotificationsApiError(response.status, message);
  }
  return data as T;
}

export const notificationsApi = {
  follows: () => request<TitleFollow[]>('/notifications/follows'),
  follow: (mangaId: string, mangaTitle: string, posterUrl?: string | null, source?: string | null) =>
    request<TitleFollow>('/notifications/follows', {
      method: 'POST',
      body: JSON.stringify({
        manga_id: mangaId,
        manga_title: mangaTitle,
        poster_url: posterUrl ?? null,
        source: source ?? null,
      }),
    }),
  unfollow: (mangaId: string) =>
    request<{ message: string }>(`/notifications/follows/${encodeURIComponent(mangaId)}`, {
      method: 'DELETE',
    }),
  followStatus: (mangaId: string) =>
    request<FollowStatus>(`/notifications/follows/${encodeURIComponent(mangaId)}`),
  settings: () => request<NotificationSettings>('/notifications/settings'),
  saveSettings: (settings: Omit<NotificationSettings, 'updated_at'>) =>
    request<NotificationSettings>('/notifications/settings', {
      method: 'PUT',
      body: JSON.stringify(settings),
    }),
  pushConfig: () => request<PushConfig>('/notifications/push/config'),
  pushStatus: () => request<PushStatus>('/notifications/push/status'),
  subscribePush: (subscription: PushSubscriptionJSON) =>
    request<{ subscribed: boolean }>('/notifications/push/subscribe', {
      method: 'POST',
      body: JSON.stringify({
        endpoint: subscription.endpoint,
        keys: subscription.keys,
      }),
    }),
  unsubscribePush: (endpoint: string) =>
    request<{ unsubscribed: boolean }>('/notifications/push/subscribe', {
      method: 'DELETE',
      body: JSON.stringify({ endpoint }),
    }),
};
