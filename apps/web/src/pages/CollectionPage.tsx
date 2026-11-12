import { useQuery } from '@tanstack/react-query';
import { Link, useParams } from 'react-router-dom';
import { api } from '../api/client';
import { EmptyState } from '../components/EmptyState';
import { ErrorState } from '../components/ErrorState';
import { Icon } from '../components/Icon';
import { MangaCard } from '../components/MangaCard';
import { useSurfaceImpression } from '../components/RecommendationShelf';
import { MangaGridSkeleton } from '../components/Skeleton';
import { trackEvent } from '../lib/analytics';
import { humanizeError } from '../lib/errors';
import { absoluteUrl, useSeo } from '../lib/seo';

const COLLECTION_LIMIT = 48;

export default function CollectionPage() {
  const { slug = '' } = useParams();
  const surface = `collection_${slug}`.slice(0, 32);
  const query = useQuery({
    queryKey: ['collections', slug, COLLECTION_LIMIT],
    queryFn: ({ signal }) => api.getCollection(slug, COLLECTION_LIMIT, signal),
    enabled: Boolean(slug),
    staleTime: 5 * 60_000,
    retry: false,
  });
  const collection = query.data;
  const gridRef = useSurfaceImpression<HTMLDivElement>(
    surface,
    undefined,
    Boolean(collection && collection.items.length > 0),
  );

  useSeo({
    title: collection
      ? `${collection.title} — подборка MangaPoisk Reborn`
      : 'Подборка — MangaPoisk Reborn',
    description:
      collection?.description ||
      'Тематическая подборка манги и манхвы с обложками, рейтингами и числом глав.',
    canonical: absoluteUrl(`/collections/${slug}`) ?? undefined,
    robots: query.isError ? 'noindex,follow' : 'index,follow',
  });

  if (query.isLoading) {
    return (
      <div className="page container collection-page">
        <div className="section-head">
          <h1>Подборка</h1>
        </div>
        <MangaGridSkeleton count={12} />
      </div>
    );
  }

  if (query.isError || !collection) {
    return (
      <div className="page container collection-page">
        <ErrorState
          title="Подборка не найдена"
          message={humanizeError(query.error, 'Возможно, её скрыли или удалили.')}
          onRetry={() => void query.refetch()}
          action={
            <Link to="/" className="btn btn--outline btn--sm">
              На главную
            </Link>
          }
        />
      </div>
    );
  }

  return (
    <div className="page container collection-page">
      <nav className="breadcrumbs" aria-label="Хлебные крошки">
        <Link to="/">Главная</Link>
        <Icon name="chevron-right" size={13} />
        <span aria-current="page">{collection.title}</span>
      </nav>

      <header className="section-head collection-page__head">
        <div>
          <span className="ml-kicker">Подборка</span>
          <h1>{collection.title}</h1>
          {collection.description ? <p className="section-head__sub">{collection.description}</p> : null}
        </div>
        <span className="collection-page__count">{collection.item_count} тайтлов</span>
      </header>

      {collection.items.length === 0 ? (
        <EmptyState
          icon="compass"
          title="Подборка пока пуста"
          description="Редакторы уже готовят новые тайтлы. Загляните в каталог."
          action={
            <Link to="/catalogue" className="btn btn--primary btn--sm">
              Открыть каталог
            </Link>
          }
        />
      ) : (
        <div className="manga-grid collection-page__grid" ref={gridRef}>
          {collection.items.map((manga, index) => (
            <MangaCard
              key={manga.id}
              manga={manga}
              eager={index < 8}
              onClick={() =>
                trackEvent('click', { surface, mangaId: manga.id, chapterId: null })
              }
            />
          ))}
        </div>
      )}
    </div>
  );
}
