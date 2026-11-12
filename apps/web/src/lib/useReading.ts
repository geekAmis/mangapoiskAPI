import { useEffect, useMemo, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, listItems } from '../api/client';
import { useAuthStore } from '../stores/auth';
import { queryKeys } from './queryClient';
import {
  LOCAL_PROGRESS_EVENT,
  clearLocalReadingDays,
  computeLocalStreak,
  markLocalProgressSynced,
  mergeResumes,
  readLocalProgress,
  readLocalReadingDayTimestamps,
  resumeFromLocal,
  resumeFromProgress,
  type LocalProgressItem,
  type LocalStreak,
  type ReadingResume,
} from './progress';

function useLocalRevision(): number {
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const update = () => setRevision((value) => value + 1);
    window.addEventListener(LOCAL_PROGRESS_EVENT, update);
    window.addEventListener('storage', update);
    return () => {
      window.removeEventListener(LOCAL_PROGRESS_EVENT, update);
      window.removeEventListener('storage', update);
    };
  }, []);
  return revision;
}

export function useLocalProgress(ownerId: string | null): LocalProgressItem[] {
  const revision = useLocalRevision();
  return useMemo(
    () => readLocalProgress(ownerId),
    // The revision is the external store signal for localStorage.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [ownerId, revision],
  );
}

export function useReadingResume(): {
  items: ReadingResume[];
  isLoading: boolean;
  isReady: boolean;
  isError: boolean;
  error: unknown;
  refetch: () => void;
} {
  const user = useAuthStore((state) => state.user);
  const local = useLocalProgress(user?.id ?? null);
  const progressQuery = useQuery({
    queryKey: queryKeys.progress,
    queryFn: ({ signal }) => api.getProgress(signal),
    enabled: Boolean(user),
  });

  const items = useMemo(() => {
    const localItems = local.map(resumeFromLocal);
    const remoteItems = listItems(progressQuery.data)
      .map(resumeFromProgress)
      .filter((item): item is ReadingResume => item !== null);
    return mergeResumes(localItems, remoteItems);
  }, [local, progressQuery.data]);

  return {
    items,
    isLoading: Boolean(user) && progressQuery.isLoading && local.length === 0,
    isReady: !user || progressQuery.isSuccess || local.length > 0,
    isError: Boolean(user) && progressQuery.isError,
    error: progressQuery.error,
    refetch: () => void progressQuery.refetch(),
  };
}

export function useLocalStreak(): LocalStreak {
  const revision = useLocalRevision();
  return useMemo(
    () => computeLocalStreak(),
    // Recompute when local reading days change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [revision],
  );
}

/**
 * Merge anonymous/offline positions into the account once per unique local
 * revision.  The endpoint is idempotent and keeps the newest timestamp, so a
 * second device cannot rewind progress.
 */
export function useProgressSync(): void {
  const user = useAuthStore((state) => state.user);
  const local = useLocalProgress(user?.id ?? null);
  const queryClient = useQueryClient();
  const lastKey = useRef('');
  const inFlight = useRef(false);

  useEffect(() => {
    if (!user || inFlight.current) return;
    const readDays = readLocalReadingDayTimestamps();
    // Only anonymous positions need merging.  Account-owned local copies are
    // already written through upsertProgress on every reader page, so sending
    // them on every local revision would create needless write traffic.
    const pending = local.filter((item) => item.owner_id === null);
    if (pending.length === 0 && readDays.length === 0) return;
    const key = `${user.id}:${readDays.join(',')}:${pending
      .map((item) => `${item.manga_id}:${item.updated_at}`)
      .join('|')}`;
    if (key === lastKey.current) return;
    lastKey.current = key;
    inFlight.current = true;
    void api
      .mergeProgress(
        pending.map((item) => ({
          manga_id: item.manga_id,
          chapter_id: item.chapter_id,
          page: item.page,
          total_pages: item.total_pages,
          read_at: item.updated_at,
        })),
        readDays,
      )
      .then(() => {
        markLocalProgressSynced(user.id);
        clearLocalReadingDays();
        lastKey.current = `${user.id}::`;
        void queryClient.invalidateQueries({ queryKey: queryKeys.progress });
        void queryClient.invalidateQueries({ queryKey: ['library', 'history'] });
        void queryClient.invalidateQueries({ queryKey: ['streak'] });
      })
      .catch(() => {
        // Offline or a temporary backend error: the local copy stays intact and
        // the next unique revision retries the merge.
        lastKey.current = '';
      })
      .finally(() => {
        inFlight.current = false;
      });
  }, [user, local, queryClient]);
}
