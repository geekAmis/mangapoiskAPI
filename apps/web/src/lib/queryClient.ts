import { QueryClient } from '@tanstack/react-query';
import { isApiError } from '../api/client';

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      gcTime: 15 * 60_000,
      refetchOnWindowFocus: false,
      retry: (failureCount, error) => {
        if (isApiError(error)) {
          if (error.status === 0) return failureCount < 1;
          if (error.status >= 400 && error.status < 500) return false;
        }
        return failureCount < 1;
      },
    },
    mutations: {
      retry: 0,
    },
  },
});

export const queryKeys = {
  sources: ['sources'] as const,
  manga: (id: string) => ['manga', id] as const,
  mangaList: (params: unknown) => ['manga', 'list', params] as const,
  chapter: (id: string) => ['chapter', id] as const,
  bookmarks: ['library', 'bookmarks'] as const,
  progress: ['library', 'progress'] as const,
  history: (limit: number) => ['library', 'history', limit] as const,
  settings: (userId: string) => ['library', 'settings', userId] as const,
  exportJob: (id: string) => ['export', id] as const,
};
