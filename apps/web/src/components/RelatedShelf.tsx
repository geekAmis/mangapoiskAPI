import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import { useLocalProgress } from '../lib/useReading';
import { useAuthStore } from '../stores/auth';
import { MangaShelf } from './RecommendationShelf';

export function RelatedShelf({ mangaId }: { mangaId: string }) {
  const user = useAuthStore((state) => state.user);
  const local = useLocalProgress(user?.id ?? null);
  const historyIds = useMemo(
    () => Array.from(new Set(local.map((item) => item.manga_id))).slice(0, 100),
    [local],
  );
  const query = useQuery({
    queryKey: ['manga', mangaId, 'related', user?.id ?? 'anon', historyIds.join(',')],
    queryFn: ({ signal }) =>
      api.getMangaRelated(mangaId, historyIds, signal, 12, Boolean(user)),
    staleTime: 10 * 60_000,
    retry: false,
  });
  const series = query.data?.series ?? [];
  const linked = query.data?.related ?? [];
  const similar = query.data?.similar ?? [];
  if (series.length === 0 && linked.length === 0 && similar.length === 0) return null;

  return (
    <div className="related-shelves">
      {series.length > 0 ? (
        <MangaShelf
          title="Серия"
          subtitle="Связанные части цикла — порядок проверен вручную"
          items={series}
          surface="manga_series"
          seedMangaId={mangaId}
        />
      ) : null}
      {linked.length > 0 ? (
        <MangaShelf
          title="Связанное"
          subtitle="Проверенные вручную связи между тайтлами"
          items={linked}
          surface="manga_links"
          seedMangaId={mangaId}
        />
      ) : null}
      {similar.length > 0 ? (
        <MangaShelf
          title="Похожее"
          subtitle="По жанрам, рейтингу, году, типу и числу глав"
          items={similar}
          surface="manga_related"
          seedMangaId={mangaId}
        />
      ) : null}
    </div>
  );
}
