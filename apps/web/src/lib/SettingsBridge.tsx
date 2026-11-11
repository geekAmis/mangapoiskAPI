import { useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import { useAuthStore } from '../stores/auth';
import { useReaderStore, type ReaderPreferences } from '../stores/reader';
import { useThemeStore } from '../stores/theme';
import { queryClient } from './queryClient';
import { applySettingsToStores, settingsEqual, settingsFromStores } from './settings';

/**
 * Связывает локальные настройки (тема, читалка) с профилем:
 * - при входе подтягивает серверные настройки один раз;
 * - изменения после этого отправляются на сервер с задержкой.
 * Если сервер недоступен, локальные настройки продолжают работать.
 */
export function SettingsBridge() {
  const userId = useAuthStore((state) => state.user?.id ?? null);
  const theme = useThemeStore((state) => state.theme);
  const mode = useReaderStore((state) => state.mode);
  const pageFit = useReaderStore((state) => state.pageFit);
  const autoScroll = useReaderStore((state) => state.autoScroll);
  const autoScrollSpeed = useReaderStore((state) => state.autoScrollSpeed);
  const showPageNumbers = useReaderStore((state) => state.showPageNumbers);
  const blurAdultPosters = useReaderStore((state) => state.blurAdultPosters);

  const settingsQuery = useQuery({
    queryKey: ['library', 'settings', userId ?? 'guest'],
    queryFn: ({ signal }) => api.getSettings(signal),
    enabled: Boolean(userId),
    staleTime: Infinity,
    gcTime: 60 * 60_000,
    retry: 1,
  });

  const appliedFor = useRef<string | null>(null);

  useEffect(() => {
    if (!userId) {
      appliedFor.current = null;
      return;
    }
    if (settingsQuery.data && appliedFor.current !== userId) {
      appliedFor.current = userId;
      applySettingsToStores(settingsQuery.data);
    }
  }, [userId, settingsQuery.data]);

  useEffect(() => {
    if (!userId || !settingsQuery.isSuccess || appliedFor.current !== userId) return;

    const prefs: ReaderPreferences = {
      mode,
      pageFit,
      gap: 8,
      autoScroll,
      autoScrollSpeed,
      showPageNumbers,
      blurAdultPosters,
    };
    const payload = settingsFromStores(theme, prefs);
    if (settingsQuery.data && settingsEqual(payload, settingsQuery.data)) return;

    const timer = window.setTimeout(() => {
      api
        .putSettings(payload)
        .then((saved) => {
          queryClient.setQueryData(['library', 'settings', userId], saved);
        })
        .catch(() => {
          /* настройки уже сохранены локально; синхронизация повторится при изменении */
        });
    }, 900);

    return () => window.clearTimeout(timer);
  }, [
    userId,
    theme,
    mode,
    pageFit,
    autoScroll,
    autoScrollSpeed,
    showPageNumbers,
    blurAdultPosters,
    settingsQuery.isSuccess,
    settingsQuery.data,
  ]);

  return null;
}
