import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { api } from '../api/client';
import { MangaShelf } from './RecommendationShelf';

const PREVIEW_LIMIT = 8;

const PLACEHOLDERS = [
  { slug: 'weekly-best', title: 'Лучшее за неделю' },
  { slug: 'beginners', title: 'Для новичков' },
  { slug: 'completed', title: 'Завершённые' },
  { slug: 'short', title: 'Короткие' },
  { slug: 'new', title: 'Новые' },
];

function surfaceFor(slug: string): string {
  return `collection_${slug}`.slice(0, 32);
}

export function CollectionsShelves() {
  const query = useQuery({
    queryKey: ['collections', 'home', PREVIEW_LIMIT],
    queryFn: ({ signal }) => api.getCollections(PREVIEW_LIMIT, signal),
    staleTime: 5 * 60_000,
    gcTime: 15 * 60_000,
  });

  if (query.isError) return null;

  if (query.isLoading) {
    return (
      <div className="collection-shelves" aria-busy="true">
        {PLACEHOLDERS.map((collection) => (
          <MangaShelf
            key={collection.slug}
            title={collection.title}
            items={[]}
            surface={surfaceFor(collection.slug)}
            loading
            skeletonCount={PREVIEW_LIMIT}
          />
        ))}
      </div>
    );
  }

  const collections = query.data?.items ?? [];
  if (collections.length === 0) return null;

  return (
    <div className="collection-shelves">
      {collections.map((collection) => (
        <MangaShelf
          key={collection.id}
          title={collection.title}
          subtitle={collection.description || undefined}
          items={collection.items}
          surface={surfaceFor(collection.slug)}
          action={
            <Link to={`/collections/${encodeURIComponent(collection.slug)}`}>
              Все тайтлы
            </Link>
          }
        />
      ))}
    </div>
  );
}
