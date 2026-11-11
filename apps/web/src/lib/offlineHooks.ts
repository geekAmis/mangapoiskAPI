import { useCallback, useEffect, useState } from 'react';
import { getOfflineTitle, listOfflineTitles, subscribeOfflineTitles } from './offlineStorage';
import type { OfflineTitle } from './offlineTypes';

interface OfflineTitlesState {
  titles: OfflineTitle[];
  loading: boolean;
  error: string | null;
}

export function useOfflineTitles(): OfflineTitlesState & { refresh: () => Promise<void> } {
  const [state, setState] = useState<OfflineTitlesState>({
    titles: [],
    loading: true,
    error: null,
  });

  const load = useCallback(async () => {
    try {
      const titles = await listOfflineTitles();
      setState({ titles, loading: false, error: null });
    } catch (error: unknown) {
      setState((previous) => ({
        ...previous,
        loading: false,
        error: error instanceof Error ? error.message : 'Не удалось прочитать офлайн-библиотеку',
      }));
    }
  }, []);

  useEffect(() => {
    let alive = true;
    const run = () => {
      void load().then(() => {
        if (!alive) return;
      });
    };
    run();
    const unsubscribe = subscribeOfflineTitles(run);
    return () => {
      alive = false;
      unsubscribe();
    };
  }, [load]);

  return { ...state, refresh: load };
}

interface OfflineTitleState {
  title: OfflineTitle | null;
  loading: boolean;
  error: string | null;
}

export function useOfflineTitle(mangaId: string): OfflineTitleState & { refresh: () => Promise<void> } {
  const [state, setState] = useState<OfflineTitleState>({
    title: null,
    loading: true,
    error: null,
  });

  const load = useCallback(async () => {
    if (!mangaId) {
      setState({ title: null, loading: false, error: null });
      return;
    }
    try {
      const title = await getOfflineTitle(mangaId);
      setState({ title, loading: false, error: null });
    } catch (error: unknown) {
      setState({
        title: null,
        loading: false,
        error: error instanceof Error ? error.message : 'Не удалось прочитать манифест тайтла',
      });
    }
  }, [mangaId]);

  useEffect(() => {
    let alive = true;
    const run = () => {
      void load().then(() => {
        if (!alive) return;
      });
    };
    setState((previous) => ({ ...previous, loading: true }));
    run();
    const unsubscribe = subscribeOfflineTitles(run);
    return () => {
      alive = false;
      unsubscribe();
    };
  }, [load]);

  return { ...state, refresh: load };
}
