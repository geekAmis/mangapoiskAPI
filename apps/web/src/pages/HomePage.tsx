import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { api, listItems } from '../api/client';
import { EmptyState } from '../components/EmptyState';
import { ErrorState, InlineError } from '../components/ErrorState';
import { Icon } from '../components/Icon';
import { MangaCard } from '../components/MangaCard';
import { MangaGridSkeleton, Skeleton } from '../components/Skeleton';
import { Poster } from '../components/Poster';
import { humanizeError } from '../lib/errors';
import {
  chapterHeading,
  chaptersLabel,
  formatRelative,
  progressPercent,
  sourceLabel,
} from '../lib/format';
import { useDocumentTitle } from '../lib/hooks';
import { useAuthStore } from '../stores/auth';
import '../styles/mangalib-home.css';

const UPDATES_PARAMS = { sort: 'updated', limit: 24, page: 1 } as const;
const POPULAR_PARAMS = { sort: 'popular', limit: 12, page: 1 } as const;

function RankedList({
  title,
  items,
  loading,
}: {
  title: string;
  items: Array<{ id: string; title: string; poster_url: string | null; source: string; chapters_count: number }>;
  loading: boolean;
}) {
  return (
    <div className="ml-rank">
      <h3>{title}</h3>
      {loading ? (
        <div className="ml-rank__list">
          {Array.from({ length: 5 }, (_, index) => (
            <Skeleton key={index} height="58px" />
          ))}
        </div>
      ) : items.length > 0 ? (
        <ol className="ml-rank__list">
          {items.slice(0, 6).map((item, index) => (
            <li key={item.id}>
              <Link to={`/manga/${item.id}`} className="ml-rank__row">
                <span className="ml-rank__index">{index + 1}</span>
                <span className="ml-rank__poster">
                  <Poster src={item.poster_url} alt="" />
                </span>
                <span className="ml-rank__body">
                  <span className="ml-rank__title">{item.title}</span>
                  <span className="ml-rank__meta">
                    {sourceLabel(item.source)} · {chaptersLabel(item.chapters_count)}
                  </span>
                </span>
              </Link>
            </li>
          ))}
        </ol>
      ) : (
        <p className="muted small">Пока пусто</p>
      )}
    </div>
  );
}

export default function HomePage() {
  useDocumentTitle('MangaPoisk Reborn — читалка манги и манхвы');
  const user = useAuthStore((state) => state.user);

  const updatesQuery = useQuery({
    queryKey: ['manga', 'list', UPDATES_PARAMS],
    queryFn: ({ signal }) => api.listManga(UPDATES_PARAMS, signal),
  });

  const popularQuery = useQuery({
    queryKey: ['manga', 'list', POPULAR_PARAMS],
    queryFn: ({ signal }) => api.listManga(POPULAR_PARAMS, signal),
  });

  const sourcesQuery = useQuery({
    queryKey: ['sources'],
    queryFn: ({ signal }) => api.sources(signal),
    staleTime: 10 * 60_000,
  });

  const progressQuery = useQuery({
    queryKey: ['library', 'progress'],
    queryFn: ({ signal }) => api.getProgress(signal),
    enabled: Boolean(user),
  });

  const updates = updatesQuery.data?.items ?? [];
  const popular = popularQuery.data?.items ?? [];
  const sources = sourcesQuery.data?.filter((source) => source.enabled) ?? [];
  const continueItems = listItems(progressQuery.data).filter((item) => item.manga);

  return (
    <>
      <section className="ml-home-intro">
        <div className="container ml-home-intro__inner">
          <div>
            <span className="ml-kicker">Онлайн-каталог</span>
            <h1>Манга и манхва на русском</h1>
            <p>Читайте онлайн, скачивайте главы в приложение и продолжайте с любого устройства.</p>
          </div>
          <div className="ml-home-intro__actions">
            <Link to="/catalogue" className="btn btn--primary">
              <Icon name="compass" size={17} />
              Открыть каталог
            </Link>
            <Link to="/library?tab=downloads" className="btn btn--outline">
              <Icon name="download" size={17} />
              Скачано
            </Link>
          </div>
        </div>
      </section>

      <div className="container ml-home">
        {sources.length > 0 ? (
          <div className="ml-source-strip" aria-label="Источники">
            {sources.map((source) => (
              <Link
                key={source.code}
                to={`/catalogue?source=${encodeURIComponent(source.code)}`}
                className="chip"
              >
                {source.name}
              </Link>
            ))}
          </div>
        ) : null}

        <section className="ml-panel" aria-labelledby="ml-updates-title">
          <header className="ml-panel__head">
            <h2 id="ml-updates-title">Обновления</h2>
            <Link to="/catalogue?sort=updated">
              Все обновления <Icon name="chevron-right" size={14} />
            </Link>
          </header>
          {updatesQuery.isLoading ? (
            <MangaGridSkeleton count={12} />
          ) : updatesQuery.isError ? (
            <ErrorState
              compact
              title="Не удалось загрузить обновления"
              message={humanizeError(updatesQuery.error)}
              onRetry={() => void updatesQuery.refetch()}
            />
          ) : updates.length > 0 ? (
            <div className="ml-grid ml-grid--updates">
              {updates.map((manga, index) => (
                <MangaCard key={manga.id} manga={manga} compact eager={index < 8} />
              ))}
            </div>
          ) : (
            <EmptyState
              compact
              icon="clock"
              title="Каталог наполняется"
              description="Автоматический импорт из источников уже запущен. Новые тайтлы появятся здесь без ручных ссылок."
              action={
                <Link to="/catalogue" className="btn btn--primary btn--sm">
                  Проверить каталог
                </Link>
              }
            />
          )}
        </section>

        {user ? (
          <section className="ml-panel" aria-labelledby="ml-continue-title">
            <header className="ml-panel__head">
              <h2 id="ml-continue-title">Продолжить чтение</h2>
              <Link to="/library?tab=reading">Вся библиотека</Link>
            </header>
            {progressQuery.isLoading ? (
              <div className="ml-continue" aria-hidden="true">
                {Array.from({ length: 3 }, (_, index) => (
                  <Skeleton key={index} height="84px" />
                ))}
              </div>
            ) : progressQuery.isError ? (
              <InlineError
                message={humanizeError(progressQuery.error, 'Не удалось загрузить прогресс.')}
                onRetry={() => void progressQuery.refetch()}
              />
            ) : continueItems.length > 0 ? (
              <div className="ml-continue">
                {continueItems.slice(0, 4).map((item) => {
                  const manga = item.manga;
                  if (!manga) return null;
                  const percent = progressPercent(item.page, item.total_pages);
                  return (
                    <Link className="ml-continue__row" key={item.manga_id} to={`/reader/${item.chapter_id}`}>
                      <span className="ml-continue__poster">
                        <Poster src={manga.poster_url} alt="" />
                      </span>
                      <span className="ml-continue__body">
                        <strong>{manga.title}</strong>
                        <span>
                          {item.chapter ? chapterHeading(item.chapter) : 'Глава'} · {formatRelative(item.updated_at)}
                        </span>
                        <span className="progress">
                          <span className="progress__bar" style={{ width: `${percent}%` }} />
                        </span>
                      </span>
                      <span className="ml-continue__percent">{percent}%</span>
                    </Link>
                  );
                })}
              </div>
            ) : (
              <EmptyState
                compact
                icon="book"
                title="Пока ничего не читали"
                description="Откройте каталог и выберите историю — прогресс появится здесь."
              />
            )}
          </section>
        ) : null}

        <section className="ml-panel" aria-labelledby="ml-hot-title">
          <header className="ml-panel__head">
            <h2 id="ml-hot-title">Горячие новинки</h2>
            <Link to="/catalogue?sort=popular">
              Весь каталог <Icon name="chevron-right" size={14} />
            </Link>
          </header>
          {popularQuery.isLoading ? (
            <MangaGridSkeleton count={8} />
          ) : popularQuery.isError ? (
            <ErrorState
              compact
              title="Не удалось загрузить популярное"
              message={humanizeError(popularQuery.error)}
              onRetry={() => void popularQuery.refetch()}
            />
          ) : popular.length > 0 ? (
            <div className="ml-grid">
              {popular.map((manga) => (
                <MangaCard key={manga.id} manga={manga} compact />
              ))}
            </div>
          ) : (
            <EmptyState compact icon="compass" title="Пока пусто" description="Каталог скоро наполнится." />
          )}
        </section>

        <section className="ml-panel ml-panel--reading" aria-labelledby="ml-reading-title">
          <header className="ml-panel__head">
            <h2 id="ml-reading-title">Сейчас читают</h2>
            <Link to="/catalogue?sort=popular">За неделю</Link>
          </header>
          <div className="ml-columns">
            <RankedList title="Популярное" items={popular} loading={popularQuery.isLoading} />
            <RankedList title="Обновления" items={updates} loading={updatesQuery.isLoading} />
            <RankedList title="Новинки" items={[...popular].reverse()} loading={popularQuery.isLoading} />
          </div>
        </section>
      </div>
    </>
  );
}
