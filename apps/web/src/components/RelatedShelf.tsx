import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import { MangaShelf } from './RecommendationShelf';

export function RelatedShelf({ mangaId }: { mangaId: string }) {
  const query = useQuery({
    queryKey: ['manga', mangaId, 'related'],
    queryFn: ({ signal }) => api.getMangaRelated(mangaId, signal),
    staleTime: 10 * 60_000,
    retry: false,
  });
  const series = query.data?.series ?? [];
  const related = query.data?.related ?? [];
  if (series.length === 0 && related.length === 0) return null;

  return (
    <div className="related-shelves">
      <MangaShelf
        title="Серия"
        subtitle="Связанные части цикла — порядок проверен вручную"
        items={series}
        surface="manga_series"
        seedMangaId={mangaId}
      />
      <MangaShelf
        title="Похожее"
        subtitle="Что ещё может понравиться"
        items={related}
        surface="manga_related"
        seedMangaId={mangaId}
      />
    </div>
  );
}
