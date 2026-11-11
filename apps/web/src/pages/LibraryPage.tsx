import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useSearchParams } from 'react-router-dom';
import { api, listItems } from '../api/client';
import type { ProgressOut } from '../api/types';
import { EmptyState } from '../components/EmptyState';
import { ErrorState } from '../components/ErrorState';
import { Icon } from '../components/Icon';
import { MangaCard } from '../components/MangaCard';
import { MangaGridSkeleton, Skeleton } from '../components/Skeleton';
import { Poster } from '../components/Poster';
import { humanizeError } from '../lib/errors';
import {
  chapterHeading,
  formatDateTime,
  formatInt,
  formatRelative,
  progressPercent,
} from '../lib/format';
import { useDocumentTitle } from '../lib/hooks';
import { queryKeys } from '../lib/queryClient';
import { useAuthStore } from '../stores/auth';
import { toast } from '../stores/toast';

type LibraryTab = 'reading' | 'bookmarks' | 'history';

const TABS: Array<{ id: LibraryTab; label: string; icon: 'book' | 'bookmark' | 'clock' }> = [
  { id: 'reading', label: 'Продолжить', icon: 'book' },
  { id: 'bookmarks', label: 'Закладки', icon: 'bookmark' },
  { id: 'history', label: 'История', icon: 'clock' },
];

function parseTab(value: string | null): LibraryTab {
  return value === 'bookmarks' || value === 'history' || value === 'reading' ? value : 'reading';
}

export default function LibraryPage() {
  useDocumentTitle('Моя библиотека — MangaPoisk Reborn');
  const user = useAuthStore((state) => state.user);
  const [searchParams, setSearchParams] = useSearchParams();
  const tab = parseTab(searchParams.get('tab'));
  const queryClient = useQueryClient();

  const bookmarksQuery = useQuery({
    queryKey: queryKeys.bookmarks,
    queryFn: ({ signal }) => api.getBookmarks(signal),
    enabled: Boolean(user),
  });

  const progressQuery = useQuery({
    queryKey: queryKeys.progress,
    queryFn: ({ signal }) => api.getProgress(signal),
    enabled: Boolean(user),
  });

  const historyQuery = useQuery({
    queryKey: queryKeys.history(50),
    queryFn: ({ signal }) => api.getHistory(50, signal),
    enabled: Boolean(user) && tab === 'history',
  });

  const bookmarks = listItems(bookmarksQuery.data);
  const progressItems = listItems(progressQuery.data).filter((item) => item.manga);
  const historyItems = [...listItems(historyQuery.data)].sort(
    (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
  );

  const removeBookmark = useMutation({
    mutationFn: (mangaId: string) => api.removeBookmark(mangaId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['library', 'bookmarks'] });
      toast.success('Убрано из закладок');
    },
    onError: (error: unknown) => toast.error(humanizeError(error, 'Не удалось убрать закладку')),
  });

  const resetProgress = useMutation({
    mutationFn: (mangaId: string) => api.resetProgress(mangaId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['library', 'progress'] });
      void queryClient.invalidateQueries({ queryKey: ['library', 'history'] });
      toast.info('Прогресс чтения сброшен');
    },
    onError: (error: unknown) => toast.error(humanizeError(error, 'Не удалось сбросить прогресс')),
  });

  const setTab = (nextTab: LibraryTab) => {
    const next = new URLSearchParams(searchParams);
    if (nextTab === 'reading') next.delete('tab');
    else next.set('tab', nextTab);
    setSearchParams(next);
  };

  const counts: Partial<Record<LibraryTab, number>> = {
    bookmarks: bookmarks.length,
    reading: progressItems.length,
  };

  return (
    <div className="page container">
      <div className="page-head">
        <div className="page-head__main">
          <span className="eyebrow">Личное пространство</span>
          <h1 className="page-title">Библиотека</h1>
          <p className="page-subtitle">
            Продолжайте с сохранённой страницы, храните закладки и возвращайтесь к истории чтения.
          </p>
        </div>
        <div className="page-head__actions">
          <Link to="/catalogue" className="btn btn--outline">
            <Icon name="compass" size={17} />
            Найти новое
          </Link>
        </div>
      </div>

      <div className="tabs library-tabs" role="tablist" aria-label="Разделы библиотеки">
        {TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            id={`library-tab-${item.id}`}
            aria-selected={tab === item.id}
            aria-controls="library-panel"
            className={`tabs__item${tab === item.id ? ' is-active' : ''}`}
            onClick={() => setTab(item.id)}
          >
            <Icon name={item.icon} size={16} />
            {item.label}
            {counts[item.id] !== undefined ? (
              <span className="tabs__count">{formatInt(counts[item.id] ?? 0)}</span>
            ) : null}
          </button>
        ))}
      </div>

      <div
        id="library-panel"
        role="tabpanel"
        aria-labelledby={`library-tab-${tab}`}
        className="library-panel"
      >
        {tab === 'reading' ? (
          progressQuery.isLoading ? (
            <div className="reading-grid" aria-hidden="true">
              {Array.from({ length: 4 }, (_, index) => (
                <Skeleton key={index} height="140px" />
              ))}
            </div>
          ) : progressQuery.isError ? (
            <ErrorState
              title="Не удалось загрузить продолжение"
              message={humanizeError(progressQuery.error)}
              onRetry={() => void progressQuery.refetch()}
            />
          ) : progressItems.length > 0 ? (
            <div className="reading-grid">
              {progressItems.map((item) => {
                const manga = item.manga;
                if (!manga) return null;
                const percent = progressPercent(item.page, item.total_pages);
                return (
                  <article className="reading-card" key={item.manga_id}>
                    <Link to={`/manga/${manga.id}`} className="reading-card__poster">
                      <Poster src={manga.poster_url} alt="" />
                    </Link>
                    <div className="reading-card__body">
                      <Link to={`/manga/${manga.id}`} className="reading-card__title">
                        {manga.title}
                      </Link>
                      <span className="reading-card__chapter">
                        {item.chapter ? chapterHeading(item.chapter) : 'Глава'} · стр. {item.page}
                      </span>
                      <span className="reading-card__meta">{formatRelative(item.updated_at)}</span>
                      <div className="reading-card__progress">
                        <div className="reading-card__progress-text">
                          <span>
                            Страница {formatInt(item.page)} из {formatInt(item.total_pages || item.chapter?.page_count || 0)}
                          </span>
                          <span>{percent}%</span>
                        </div>
                        <div className="progress">
                          <div className="progress__bar" style={{ width: `${percent}%` }} />
                        </div>
                      </div>
                      <div className="reading-card__actions">
                        <Link to={`/reader/${item.chapter_id}?page=${item.page}`} className="btn btn--primary">
                          <Icon name="play" size={13} />
                          Продолжить
                        </Link>
                        <button
                          type="button"
                          className="reading-card__reset"
                          onClick={() => resetProgress.mutate(item.manga_id)}
                          disabled={resetProgress.isPending}
                          aria-label={`Сбросить прогресс «${manga.title}»`}
                          title="Сбросить прогресс"
                        >
                          <Icon name="trash" size={15} />
                        </button>
                      </div>
                    </div>
                  </article>
                );
              })}
            </div>
          ) : (
            <EmptyState
              icon="book"
              title="Вы ещё ничего не читали"
              description="Откройте любую мангу и начните читать — позиция автоматически сохранится здесь."
              action={
                <Link to="/catalogue" className="btn btn--primary">
                  Перейти в каталог
                </Link>
              }
              secondaryAction={
                <Link to="/" className="btn btn--outline">
                  На главную
                </Link>
              }
            />
          )
        ) : null}

        {tab === 'bookmarks' ? (
          bookmarksQuery.isLoading ? (
            <MangaGridSkeleton count={10} />
          ) : bookmarksQuery.isError ? (
            <ErrorState
              title="Не удалось загрузить закладки"
              message={humanizeError(bookmarksQuery.error)}
              onRetry={() => void bookmarksQuery.refetch()}
            />
          ) : bookmarks.length > 0 ? (
            <div className="manga-grid">
              {bookmarks.map((bookmark) => {
                const manga = bookmark.manga;
                if (!manga) return null;
                return (
                  <div key={bookmark.id} style={{ position: 'relative' }}>
                    <MangaCard
                      manga={manga}
                      action={
                        <button
                          type="button"
                          className="icon-action is-danger"
                          onClick={() => removeBookmark.mutate(bookmark.manga_id)}
                          disabled={removeBookmark.isPending}
                          aria-label={`Удалить «${manga.title}» из закладок`}
                          title="Удалить из закладок"
                        >
                          <Icon name="trash" size={16} />
                        </button>
                      }
                    />
                  </div>
                );
              })}
            </div>
          ) : (
            <EmptyState
              icon="bookmark"
              title="Закладок пока нет"
              description="Нажмите «В закладки» на странице тайтла, чтобы вернуться к нему в любой момент."
              action={
                <Link to="/catalogue" className="btn btn--primary">
                  Найти мангу
                </Link>
              }
            />
          )
        ) : null}

        {tab === 'history' ? (
          historyQuery.isLoading ? (
            <div className="history-panel" aria-hidden="true">
              {Array.from({ length: 6 }, (_, index) => (
                <div key={index} style={{ padding: 12 }}>
                  <Skeleton height="44px" />
                </div>
              ))}
            </div>
          ) : historyQuery.isError ? (
            <ErrorState
              title="Не удалось загрузить историю"
              message={humanizeError(historyQuery.error)}
              onRetry={() => void historyQuery.refetch()}
            />
          ) : historyItems.length > 0 ? (
            <div className="history-panel">
              {historyItems.map((item) => (
                <HistoryRow key={`${item.manga_id}-${item.chapter_id}-${item.updated_at}`} item={item} />
              ))}
            </div>
          ) : (
            <EmptyState
              icon="clock"
              title="История пуста"
              description="Здесь появятся главы, которые вы открывали. История хранится в вашем аккаунте."
              action={
                <Link to="/catalogue" className="btn btn--primary">
                  Начать читать
                </Link>
              }
            />
          )
        ) : null}
      </div>
    </div>
  );
}

function HistoryRow({ item }: { item: ProgressOut }) {
  const manga = item.manga;
  if (!manga) return null;
  return (
    <div className="history-row">
      <Link to={`/manga/${manga.id}`} className="history-row__poster" tabIndex={-1} aria-hidden="true">
        <Poster src={manga.poster_url} alt="" />
      </Link>
      <div className="history-row__body">
        <Link to={`/manga/${manga.id}`} className="history-row__title">
          {manga.title}
        </Link>
        <div className="history-row__meta">
          {item.chapter ? chapterHeading(item.chapter) : 'Глава'} · страница {item.page} из{' '}
          {item.total_pages || '—'} · {formatDateTime(item.updated_at)}
        </div>
      </div>
      <div className="history-row__tail">
        <Link to={`/reader/${item.chapter_id}?page=${item.page}`} className="btn btn--outline btn--sm">
          <Icon name="book" size={14} />
          Продолжить
        </Link>
      </div>
    </div>
  );
}
