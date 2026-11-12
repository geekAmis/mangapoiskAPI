import {
  useEffect,
  useMemo,
  useRef,
  type ReactNode,
  type RefObject,
} from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { api } from '../api/client';
import type { MangaOut } from '../api/types';
import { trackEvent } from '../lib/analytics';
import { MangaCard } from './MangaCard';
import { MangaGridSkeleton } from './Skeleton';
import { useAuthStore } from '../stores/auth';
import { useLocalProgress } from '../lib/useReading';

function useImpression(
  surface: string,
  seedMangaId: string | undefined,
): RefObject<HTMLElement | null> {
  const ref = useRef<HTMLElement | null>(null);
  const seen = useRef(false);
  useEffect(() => {
    const element = ref.current;
    if (!element || seen.current) return;
    if (!('IntersectionObserver' in window)) {
      seen.current = true;
      trackEvent('impression', { surface, mangaId: seedMangaId });
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (!seen.current && entries.some((entry) => entry.isIntersecting)) {
          seen.current = true;
          trackEvent('impression', { surface, mangaId: seedMangaId });
          observer.disconnect();
        }
      },
      { rootMargin: '0px 0px -15% 0px', threshold: 0.15 },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [surface, seedMangaId]);
  return ref;
}

export function MangaShelf({
  title,
  subtitle,
  items,
  surface,
  seedMangaId,
  action,
  loading = false,
}: {
  title: string;
  subtitle?: string;
  items: MangaOut[];
  surface: string;
  seedMangaId?: string;
  action?: ReactNode;
  loading?: boolean;
}) {
  const ref = useImpression(surface, seedMangaId);
  const id = `shelf-${surface.replace(/[^a-z0-9_-]/gi, '-')}`;
  if (!loading && items.length === 0) return null;
  return (
    <section className="ml-panel recommendation-shelf" aria-labelledby={id} ref={ref}>
      <header className="ml-panel__head">
        <div>
          <h2 id={id}>{title}</h2>
          {subtitle ? <p className="recommendation-shelf__hint">{subtitle}</p> : null}
        </div>
        {action}
      </header>
      {loading ? (
        <MangaGridSkeleton count={6} />
      ) : (
        <div className="ml-grid">
          {items.map((manga) => (
            <div
              key={manga.id}
              onClick={() =>
                trackEvent('click', { surface, mangaId: manga.id, chapterId: null })
              }
            >
              <MangaCard manga={manga} compact />
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

export function RecommendationShelf({
  title = 'Для вас',
  surface = 'home_recommendations',
  limit = 12,
  seedMangaId,
  excludeIds = [],
  className,
}: {
  title?: string;
  surface?: string;
  limit?: number;
  seedMangaId?: string;
  excludeIds?: string[];
  className?: string;
}) {
  const user = useAuthStore((state) => state.user);
  const local = useLocalProgress(user?.id ?? null);
  const seedIds = useMemo(() => local.map((item) => item.manga_id), [local]);
  const excluded = useMemo(
    () => Array.from(new Set([...excludeIds, ...seedIds])),
    [excludeIds, seedIds],
  );
  const query = useQuery({
    queryKey: [
      'recommendations',
      surface,
      user?.id ?? 'anon',
      seedMangaId ?? '',
      seedIds.join(','),
      excluded.join(','),
      limit,
    ],
    queryFn: ({ signal }) =>
      api.getRecommendations(
        { limit, seedMangaId, seedIds, excludeIds: excluded },
        Boolean(user),
        signal,
      ),
    staleTime: 5 * 60_000,
    gcTime: 10 * 60_000,
  });

  const subtitle = query.data
    ? {
        personalized: 'По вашей истории, закладкам и жанрам',
        related: 'Похожее на этот тайтл',
        popular: user ? 'Популярное в каталоге' : 'Популярное — начните с любого',
      }[query.data.strategy]
    : undefined;

  return (
    <div className={className}>
      <MangaShelf
        title={title}
        subtitle={subtitle}
        items={query.data?.items ?? []}
        surface={surface}
        seedMangaId={seedMangaId}
        loading={query.isLoading}
        action={
          <Link to="/catalogue?sort=rating">
            Весь каталог
          </Link>
        }
      />
    </div>
  );
}
