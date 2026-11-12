import { API_BASE } from './client';
import { useAuthStore } from '../stores/auth';

export interface CommentOut {
  id: string;
  manga_id: string;
  user_id: string;
  user_name: string;
  body: string;
  spoiler: boolean;
  parent_id: string | null;
  likes_count: number;
  replies_count: number;
  liked_by_me: boolean;
  is_own: boolean;
  can_edit: boolean;
  can_delete: boolean;
  edited_at: string | null;
  created_at: string;
  updated_at: string;
  replies?: CommentOut[];
}

export interface CommentsPage {
  items: CommentOut[];
  total: number;
  page: number;
  limit: number;
  has_next: boolean;
}

export interface NotificationComment {
  id: string;
  manga_id: string;
  user_id: string;
  user_name: string;
  body: string;
  spoiler: boolean;
  parent_id: string | null;
  status: string;
  created_at: string;
}

export interface NotificationChapter {
  manga_id: string;
  manga_title: string;
  chapter_id: string;
  chapter_label: string;
  url: string | null;
  source: string | null;
}

export interface CommentNotification {
  id: string;
  user_id: string;
  comment_id: string | null;
  type: string;
  read_at: string | null;
  created_at: string;
  comment: NotificationComment | null;
  chapter: NotificationChapter | null;
}

export interface NotificationsPage {
  items: CommentNotification[];
  total: number;
  page: number;
  limit: number;
  has_next: boolean;
  unread_count: number;
}

export class CommentsApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = 'CommentsApiError';
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
    throw new CommentsApiError(response.status, message);
  }
  return data as T;
}

export const commentsApi = {
  list: (mangaId: string, page = 1, sort: 'new' | 'top' = 'new') =>
    request<CommentsPage>(
      `/manga/${encodeURIComponent(mangaId)}/comments?page=${page}&limit=20&sort=${sort}`,
    ),
  replies: (commentId: string, page = 1) =>
    request<CommentsPage>(`/comments/${encodeURIComponent(commentId)}/replies?page=${page}&limit=20`),
  create: (mangaId: string, body: string, spoiler: boolean, parentId?: string | null) =>
    request<CommentOut>(`/manga/${encodeURIComponent(mangaId)}/comments`, {
      method: 'POST',
      body: JSON.stringify({ body, spoiler, parent_id: parentId ?? null }),
    }),
  update: (commentId: string, body: string, spoiler: boolean) =>
    request<CommentOut>(`/comments/${encodeURIComponent(commentId)}`, {
      method: 'PATCH',
      body: JSON.stringify({ body, spoiler }),
    }),
  remove: (commentId: string) =>
    request<{ ok: boolean }>(`/comments/${encodeURIComponent(commentId)}`, { method: 'DELETE' }),
  like: (commentId: string) =>
    request<{ liked: boolean; likes_count: number }>(
      `/comments/${encodeURIComponent(commentId)}/like`,
      { method: 'POST' },
    ),
  report: (commentId: string, reason: string) =>
    request<unknown>(`/comments/${encodeURIComponent(commentId)}/report`, {
      method: 'POST',
      body: JSON.stringify({ reason }),
    }),
  notifications: (page = 1, limit = 20) =>
    request<NotificationsPage>(`/notifications?page=${page}&limit=${limit}`),
  markNotificationsRead: (ids: string[]) =>
    request<{ updated: number }>('/notifications/read', {
      method: 'POST',
      body: JSON.stringify({ ids }),
    }),
};
