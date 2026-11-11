import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { api, listItems } from '../api/client';
import { useDocumentTitle } from '../lib/hooks';
import { humanizeError } from '../lib/errors';
import {
  chapterHeading,
  chaptersLabel,
  formatInt,
  formatRelative,
  progressPercent,
  statusLabel,
} from '../lib/format';
import { useAuthStore } from '../stores/auth';
import { getThemeMeta, useThemeStore } from '../stores/theme';
import { toast } from '../stores/toast';
import { EmptyState } from '../components/EmptyState';
import { ErrorState, InlineError } from '../components/ErrorState';
import { Icon } from '../components/Icon';
import { MangaCard } from '../components/MangaCard';
import { MangaGridSkeleton, Skeleton } from '../components/Skeleton';
import { Poster } from '../components/Poster';
import { Rating } from '../components/Rating';

const POPULAR_PARAMS = { sort: 'popular', limit: 12, page: 1 } as const;
const LATEST_PARAMS = { sort: 'updated', limit: 12, page: 1 } as const;

export default function HomePage() {
  useDocumentTitle('MangaPoisk Reborn — читалка манги и манхвы');
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  const user = useAuthStore((state) => state.user);
  const theme = useThemeStore((state) => state.theme);
  const themeMeta = getThemeMeta(theme);

  const popularQuery = useQuery({
    queryKey: ['manga', 'list', POPULAR_PARAMS],
    queryFn: ({ signal }) => api.listManga(POPULAR_PARAMS, signal),
  });

  const latestQuery = useQuery({
    queryKey: ['manga', 'list', LATEST_PARAMS],
    queryFn: ({ signal }) => api.listManga(LATEST_PARAMS, signal),
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

  const bookmarksQuery = useQuery({
    queryKey: ['library', 'bookmarks'],
    queryFn: ({ signal }) => api.getBookmarks(signal),
    enabled: Boolean(user),
  });

  const featured = popularQuery.data?.items[0];
  const isBookmarked = Boolean(
    featured && listItems(bookmarksQuery.data).some((bookmark) => bookmark.manga_id === featured.id),
  );
  const sources = sourcesQuery.data?.filter((source) => source.enabled) ?? [];
  const continueItems = listItems(progressQuery.data).filter((item) => item.manga);

  const bookmarkMutation = useMutation({
    mutationFn: async () => {
      if (!featured) return;
      if (isBookmarked) await api.removeBookmark(featured.id);
      else await api.addBookmark(featured.id);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['library', 'bookmarks'] });
      toast.success(isBookmarked ? 'Убрано из закладок' : 'Добавлено в библиотеку');
    },
    onError: (error: unknown) => toast.error(humanizeError(error, 'Не удалось обновить закладку')),
  });

  const toggleBookmark = () => {
    if (!featured) return;
    if (!user) {
      navigate(`/login?next=${encodeURIComponent(location.pathname)}`);
      return;
    }
    bookmarkMutation.mutate();
  };

  return (
    <>
      <section className="home-hero" aria-labelledby="hero-title">
        <div className="container">
          <div className="home-hero__panel">
            <div className="home-hero__copy">
              <span className="eyebrow">
                <span className="eyebrow__rule" aria-hidden="true" />
                {featured
                  ? `Выбор редакции${featured.genres[0] ? ` · ${featured.genres[0].toLowerCase()}` : ''}`
                  : 'Русская манга · тихая роскошь чтения'}
              </span>

              {popularQuery.isLoading ? (
                <div className="home-hero__skeleton" aria-hidden="true">
                  <Skeleton width="82%" height="62px" />
                  <Skeleton width="46%" height="14px" />
                  <Skeleton width="64%" height="14px" style={{ marginTop: 8 }} />
                  <Skeleton width="92%" height="72px" style={{ marginTop: 8 }} />
                  <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                    <Skeleton width="148px" height="52px" />
                    <Skeleton width="168px" height="52px" />
                  </div>
                </div>
              ) : featured ? (
                <>
                  <h1 className="home-hero__title" id="hero-title">
                    {featured.title}
                  </h1>
                  {featured.title_en || featured.title_alt ? (
                    <p className="home-hero__alt">
                      {[featured.title_en, featured.title_alt]
                        .filter((title): title is string => Boolean(title))
                        .filter((title, index, list) => list.indexOf(title) === index)
                        .join(' · ')}
                    </p>
                  ) : null}
                  <div className="home-hero__meta">
                    <Rating value={featured.rating} compact />
                    {featured.year ? (
                      <>
                        <span className="meta-dot" aria-hidden="true" />
                        <span>{featured.year}</span>
                      </>
                    ) : null}
                    <span className="meta-dot" aria-hidden="true" />
                    <span>{statusLabel(featured.status)}</span>
                    <span className="meta-dot" aria-hidden="true" />
                    <span>{chaptersLabel(featured.chapters_count)}</span>
                  </div>
                  <p className="home-hero__lead">
                    {featured.description ??
                      'Откройте каталог MangaPoisk Reborn: русская манга и манхва, удобная читалка и экспорт глав.'}
                  </p>
                  {featured.genres.length > 0 ? (
                    <div className="home-hero__tags">
                      {featured.genres.slice(0, 4).map((genre) => (
                        <span className="chip" key={genre}>
                          {genre}
                        </span>
                      ))}
                    </div>
                  ) : null}
                  <div className="home-hero__actions">
                    <Link to={`/manga/${featured.id}`} className="btn btn--primary btn--lg">
                      <Icon name="play" size={18} />
                      Читать
                    </Link>
                    <button
                      type="button"
                      className="btn btn--outline btn--lg"
                      onClick={toggleBookmark}
                      aria-pressed={isBookmarked}
                      disabled={bookmarkMutation.isPending}
                    >
                      <Icon name="bookmark" size={18} />
                      {isBookmarked ? 'В библиотеке' : 'В библиотеку'}
                    </button>
                  </div>
                  <div className="home-hero__social">
                    <Icon name="star" size={14} />
                    <span>
                      <strong>{formatInt(featured.rating_count)}</strong> оценок читателей
                    </span>
                  </div>
                </>
              ) : (
                <>
                  <h1 className="home-hero__title" id="hero-title">
                    Истории, которые <em>стоит читать</em>
                  </h1>
                  <p className="home-hero__lead">
                    Каталог манги и манхвы, читалка без отвлекающих деталей и офлайн-экспорт
                    глав. Выберите настроение — остальное уже готово.
                  </p>
                  <div className="home-hero__actions">
                    <Link to="/catalogue" className="btn btn--primary btn--lg">
                      <Icon name="compass" size={18} />
                      Открыть каталог
                    </Link>
                    <Link to="/sources" className="btn btn--outline btn--lg">
                      <Icon name="link" size={18} />
                      Источники
                    </Link>
                  </div>
                </>
              )}

              <span className="home-hero__glyph" aria-hidden="true">
                {themeMeta.glyph}
              </span>
            </div>

            <div className="home-hero__visual" aria-hidden="true">
              <img src={`/themes/${theme}.webp`} alt="" loading="eager" decoding="async" />
            </div>
          </div>
        </div>
      </section>

      {sources.length > 0 ? (
        <div className="source-strip">
          <div className="container source-strip__inner">
            <span className="source-strip__label">Источники</span>
            <div className="chip-scroll source-strip__chips">
              {sources.map((source) => (
                <Link
                  key={source.code}
                  to={`/catalogue?source=${encodeURIComponent(source.code)}`}
                  className="chip"
                >
                  <Icon name="compass" size={13} />
                  {source.name}
                </Link>
              ))}
            </div>
            <Link to="/sources" className="source-strip__all">
              Все <Icon name="chevron-right" size={14} />
            </Link>
          </div>
        </div>
      ) : null}

      <div className="container">
        {user ? (
          <section className="home-section" aria-labelledby="continue-title">
            <div className="section-head">
              <div>
                <h2 className="section-head__title" id="continue-title">
                  Продолжить чтение
                </h2>
                <p className="section-head__sub">С того места, где вы остановились</p>
              </div>
              <Link to="/library?tab=reading" className="section-head__link">
                Вся библиотека <Icon name="chevron-right" size={15} />
              </Link>
            </div>
            {progressQuery.isLoading ? (
              <div className="continue-row" aria-hidden="true">
                {Array.from({ length: 3 }, (_, index) => (
                  <Skeleton key={index} width="318px" height="126px" />
                ))}
              </div>
            ) : progressQuery.isError ? (
              <InlineError
                message={humanizeError(progressQuery.error, 'Не удалось загрузить прогресс чтения.')}
                onRetry={() => void progressQuery.refetch()}
              />
            ) : continueItems.length > 0 ? (
              <div className="continue-row">
                {continueItems.slice(0, 8).map((item) => {
                  const manga = item.manga;
                  if (!manga) return null;
                  const percent = progressPercent(item.page, item.total_pages);
                  return (
                    <Link className="continue-card" key={item.manga_id} to={`/reader/${item.chapter_id}`}>
                      <div className="continue-card__poster">
                        <Poster src={manga.poster_url} alt="" />
                      </div>
                      <div className="continue-card__body">
                        <span className="continue-card__title">{manga.title}</span>
                        <span className="continue-card__chapter">
                          {item.chapter ? chapterHeading(item.chapter) : 'Глава'} · стр. {item.page}
                        </span>
                        <span className="continue-card__chapter">{formatRelative(item.updated_at)}</span>
                        <div className="continue-card__progress">
                          <div className="continue-card__progress-text">
                            <span>Прочитано</span>
                            <strong>{percent}%</strong>
                          </div>
                          <div className="progress">
                            <div className="progress__bar" style={{ width: `${percent}%` }} />
                          </div>
                        </div>
                      </div>
                    </Link>
                  );
                })}
              </div>
            ) : (
              <EmptyState
                compact
                icon="book"
                title="Пока ничего не читали"
                description="Откройте каталог, выберите историю — прогресс появится здесь автоматически."
                action={
                  <Link to="/catalogue" className="btn btn--primary btn--sm">
                    В каталог
                  </Link>
                }
              />
            )}
          </section>
        ) : null}

        <section className="home-section" aria-labelledby="popular-title">
          <div className="section-head">
            <div>
              <h2 className="section-head__title" id="popular-title">
                Популярное
              </h2>
              <p className="section-head__sub">Что читают чаще всего прямо сейчас</p>
            </div>
            <Link to="/catalogue?sort=popular" className="section-head__link">
              Весь каталог <Icon name="chevron-right" size={15} />
            </Link>
          </div>
          {popularQuery.isLoading ? (
            <MangaGridSkeleton count={6} />
          ) : popularQuery.isError ? (
            <ErrorState
              compact
              title="Не удалось загрузить популярное"
              message={humanizeError(popularQuery.error)}
              onRetry={() => void popularQuery.refetch()}
            />
          ) : popularQuery.data && popularQuery.data.items.length > 0 ? (
            <div className="manga-grid">
              {popularQuery.data.items.map((manga, index) => (
                <MangaCard key={manga.id} manga={manga} eager={index < 6} />
              ))}
            </div>
          ) : (
            <EmptyState
              icon="compass"
              title="Каталог пока пуст"
              description="Подключите источник в разделе «Источники» и импортируйте первую мангу — она появится здесь."
              action={
                <Link to="/sources" className="btn btn--primary">
                  Открыть источники
                </Link>
              }
              secondaryAction={
                <Link to="/catalogue" className="btn btn--outline">
                  Импорт по ссылке
                </Link>
              }
            />
          )}
        </section>

        <section className="home-section home-section--last" aria-labelledby="latest-title">
          <div className="section-head">
            <div>
              <h2 className="section-head__title" id="latest-title">
                Обновления
              </h2>
              <p className="section-head__sub">Свежие главы из всех источников</p>
            </div>
            <Link to="/catalogue?sort=updated" className="section-head__link">
              Все обновления <Icon name="chevron-right" size={15} />
            </Link>
          </div>
          {latestQuery.isLoading ? (
            <MangaGridSkeleton count={6} />
          ) : latestQuery.isError ? (
            <ErrorState
              compact
              title="Не удалось загрузить обновления"
              message={humanizeError(latestQuery.error)}
              onRetry={() => void latestQuery.refetch()}
            />
          ) : latestQuery.data && latestQuery.data.items.length > 0 ? (
            <div className="manga-grid">
              {latestQuery.data.items.map((manga) => (
                <MangaCard key={manga.id} manga={manga} />
              ))}
            </div>
          ) : (
            <EmptyState
              compact
              icon="clock"
              title="Обновлений пока нет"
              description="Как только источники принесут новые главы, они появятся в этом разделе."
              action={
                <Link to="/sources" className="btn btn--outline btn--sm">
                  Проверить источники
                </Link>
              }
            />
          )}
        </section>
      </div>
    </>
  );
}
