import { useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useSearchParams } from 'react-router-dom';
import { api, listItems } from '../api/client';
import type { ProgressOut } from '../api/types';
import { EmptyState } from '../components/EmptyState';
import { ErrorState } from '../components/ErrorState';
import { Icon } from '../components/Icon';
import { MangaCard } from '../components/MangaCard';
import { MangaGridSkeleton, Skeleton } from '../components/Skeleton';
import { Modal } from '../components/Modal';
import { Poster } from '../components/Poster';
import {
  cancelDownload,
  preparePercent,
  retryDownload,
  useDownloadJobs,
} from '../lib/downloadManager';
import { humanizeError } from '../lib/errors';
import { useOfflineTitles } from '../lib/offlineHooks';
import { deleteOfflineTitle } from '../lib/offlineStorage';
import {
  formatBytes,
  jobPercent,
  offlineTitleStats,
  type OfflineTitle,
} from '../lib/offlineTypes';
import {
  chapterHeading,
  chaptersLabel,
  formatDateTime,
  formatInt,
  formatRelative,
  pagesLabel,
  progressPercent,
  sourceLabel,
} from '../lib/format';
import { useSeo } from '../lib/seo';
import { queryKeys } from '../lib/queryClient';
import { useAuthStore } from '../stores/auth';
import { toast } from '../stores/toast';

type LibraryTab = 'reading' | 'bookmarks' | 'history' | 'downloads';

const TABS: Array<{
  id: LibraryTab;
  label: string;
  icon: 'book' | 'bookmark' | 'clock' | 'download';
}> = [
  { id: 'reading', label: 'Продолжить', icon: 'book' },
  { id: 'bookmarks', label: 'Закладки', icon: 'bookmark' },
  { id: 'history', label: 'История', icon: 'clock' },
  { id: 'downloads', label: 'Скачано', icon: 'download' },
];

function parseTab(value: string | null): LibraryTab {
  return value === 'bookmarks' ||
    value === 'history' ||
    value === 'downloads' ||
    value === 'reading'
    ? value
    : 'reading';
}

export default function LibraryPage() {
  useSeo({
    title: 'Моя библиотека — MangaPoisk Reborn',
    description:
      'Личная библиотека MangaPoisk Reborn: закладки, история чтения, прогресс и скачанные главы на этом устройстве.',
    canonical: null,
    robots: 'noindex,nofollow',
  });
  const user = useAuthStore((state) => state.user);
  const [searchParams, setSearchParams] = useSearchParams();
  const tab = parseTab(searchParams.get('tab'));
  const queryClient = useQueryClient();
  const {
    titles: offlineTitles,
    loading: offlineLoading,
    error: offlineError,
    refresh: refreshOffline,
  } = useOfflineTitles();
  const downloadJobs = useDownloadJobs();
  const [deleteTarget, setDeleteTarget] = useState<OfflineTitle | null>(null);
  const [deletingOffline, setDeletingOffline] = useState(false);
  const tabsRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = tabsRef.current;
    const active = container?.querySelector<HTMLElement>('.tabs__item.is-active');
    if (!container || !active) return;
    const containerRect = container.getBoundingClientRect();
    const activeRect = active.getBoundingClientRect();
    const left = activeRect.left - containerRect.left + container.scrollLeft;
    const right = left + activeRect.width;
    if (left < container.scrollLeft) {
      container.scrollTo({ left: Math.max(0, left - 4), behavior: 'smooth' });
    } else if (right > container.scrollLeft + container.clientWidth) {
      container.scrollTo({
        left: right - container.clientWidth + 4,
        behavior: 'smooth',
      });
    }
  }, [tab, offlineTitles.length]);

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
    downloads: offlineTitles.length,
  };

  const confirmOfflineDelete = async () => {
    if (!deleteTarget) return;
    setDeletingOffline(true);
    try {
      const job = downloadJobs.find(
        (item) =>
          item.mangaId === deleteTarget.id &&
          (item.status === 'queued' || item.status === 'running'),
      );
      if (job) await cancelDownload(job.id);
      await deleteOfflineTitle(deleteTarget.id);
      setDeleteTarget(null);
      toast.success('Тайтл удалён с устройства');
    } catch (error: unknown) {
      toast.error(
        error instanceof Error ? error.message : 'Не удалось удалить тайтл с устройства',
      );
    } finally {
      setDeletingOffline(false);
    }
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

      <div
        ref={tabsRef}
        className="tabs library-tabs"
        role="tablist"
        aria-label="Разделы библиотеки"
      >
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

        {tab === 'downloads' ? (
          offlineLoading ? (
            <div className="download-list" aria-hidden="true">
              {Array.from({ length: 4 }, (_, index) => (
                <div className="download-card download-card--skeleton" key={index}>
                  <Skeleton width="92px" height="138px" />
                  <div className="download-card__body">
                    <Skeleton width="70%" height="22px" />
                    <Skeleton width="48%" height="15px" />
                    <Skeleton width="100%" height="38px" />
                  </div>
                </div>
              ))}
            </div>
          ) : offlineError ? (
            <ErrorState
              title="Не удалось прочитать скачанное"
              message={offlineError}
              onRetry={() => void refreshOffline()}
            />
          ) : offlineTitles.length > 0 ? (
            <div className="download-list">
              {offlineTitles.map((offlineTitle) => {
                const stats = offlineTitleStats(offlineTitle);
                const job =
                  downloadJobs.find(
                    (item) =>
                      item.mangaId === offlineTitle.id &&
                      item.mode === 'title' &&
                      (item.status === 'queued' ||
                        item.status === 'running' ||
                        item.status === 'error' ||
                        item.status === 'cancelled'),
                  ) ??
                  downloadJobs.find(
                    (item) =>
                      item.mangaId === offlineTitle.id &&
                      (item.status === 'queued' ||
                        item.status === 'running' ||
                        item.status === 'error' ||
                        item.status === 'cancelled'),
                  );
                const activeJob =
                  job && (job.status === 'queued' || job.status === 'running') ? job : null;
                return (
                  <article className="download-card" key={offlineTitle.id}>
                    <Link
                      to={`/offline/manga/${offlineTitle.id}`}
                      className="download-card__poster"
                      aria-label={`Открыть скачанный тайтл «${offlineTitle.title}»`}
                    >
                      <Poster src={offlineTitle.poster} alt="" />
                    </Link>
                    <div className="download-card__body">
                      <div className="download-card__head">
                        <Link
                          to={`/offline/manga/${offlineTitle.id}`}
                          className="download-card__title"
                        >
                          {offlineTitle.title}
                        </Link>
                        <span className="download-card__badge">
                          <Icon name="download" size={12} />
                          {formatBytes(stats.bytes)}
                        </span>
                      </div>
                      <span className="download-card__meta">
                        {chaptersLabel(stats.chapters)} · {pagesLabel(stats.pages)}
                      </span>
                      <span className="download-card__source">
                        {sourceLabel(offlineTitle.source)} · скачано{' '}
                        {formatRelative(offlineTitle.downloadedAt)}
                      </span>

                      {job ? (
                        <>
                          <div className="download-card__progress">
                            {job.mode === 'title' ? (
                              <>
                                <div className="download-card__progress-text">
                                  <span>
                                    Подготовка на сервере{' '}
                                    {formatInt(job.prepare.prepared)} из{' '}
                                    {formatInt(job.chapters.length)}
                                  </span>
                                  <span>{preparePercent(job)}%</span>
                                </div>
                                <div className="progress">
                                  <div
                                    className="progress__bar"
                                    style={{ width: `${preparePercent(job)}%` }}
                                  />
                                </div>
                              </>
                            ) : null}
                            <div className="download-card__progress-text">
                              <span>
                                Скачано на устройство {formatInt(job.completedChapters)} из{' '}
                                {formatInt(job.chapters.length)} глав
                                {job.currentPage ? ` · стр. ${formatInt(job.currentPage)}` : ''}
                              </span>
                              <span>{jobPercent(job)}%</span>
                            </div>
                            <div className="progress">
                              <div
                                className="progress__bar"
                                style={{ width: `${jobPercent(job)}%` }}
                              />
                            </div>
                            {job.mode === 'title' && job.prepare.failed > 0 ? (
                              <span className="download-card__source">
                                Ошибок подготовки: {formatInt(job.prepare.failed)} — повторите,
                                готовое будет пропущено
                              </span>
                            ) : null}
                          </div>
                          {!activeJob && (job.status === 'error' || job.status === 'cancelled') ? (
                            <div className="download-card__status download-card__status--error">
                              <Icon name="alert" size={14} />
                              <span>
                                {job.status === 'cancelled'
                                  ? 'Загрузка отменена — можно продолжить'
                                  : (job.error ?? 'Загрузка остановилась')}
                              </span>
                            </div>
                          ) : null}
                        </>
                      ) : (
                        <div className="download-card__status">
                          <Icon name="check" size={14} />
                          <span>Готово к чтению без интернета</span>
                        </div>
                      )}

                      <div className="download-card__actions">
                        <Link
                          to={`/offline/manga/${offlineTitle.id}`}
                          className="btn btn--primary btn--sm"
                        >
                          <Icon name="book" size={15} />
                          Открыть
                        </Link>
                        {activeJob ? (
                          <button
                            type="button"
                            className="btn btn--ghost btn--sm"
                            onClick={() => void cancelDownload(activeJob.id)}
                          >
                            <Icon name="close" size={14} />
                            Отменить
                          </button>
                        ) : job?.status === 'error' || job?.status === 'cancelled' ? (
                          <button
                            type="button"
                            className="btn btn--outline btn--sm"
                            onClick={() => void retryDownload(job.id)}
                          >
                            <Icon name="refresh" size={14} />
                            Повторить
                          </button>
                        ) : null}
                        <button
                          type="button"
                          className="btn btn--ghost btn--sm download-card__delete"
                          onClick={() => setDeleteTarget(offlineTitle)}
                          aria-label={`Удалить «${offlineTitle.title}» с устройства`}
                        >
                          <Icon name="trash" size={15} />
                          Удалить
                        </button>
                      </div>
                    </div>
                  </article>
                );
              })}
            </div>
          ) : (
            <EmptyState
              icon="download"
              title="На устройстве пока ничего нет"
              description="Откройте тайтл и нажмите «Скачать всё на устройство» — главы будут доступны без интернета. Загрузку можно свернуть: прогресс сохранится."
              action={
                <Link to="/catalogue" className="btn btn--primary">
                  Выбрать мангу
                </Link>
              }
              secondaryAction={
                <Link to="/library" className="btn btn--outline">
                  К продолжению чтения
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

      <Modal
        open={Boolean(deleteTarget)}
        onClose={() => (deletingOffline ? undefined : setDeleteTarget(null))}
        title="Удалить тайтл с устройства?"
        description={
          deleteTarget
            ? `Все скачанные главы и страницы «${deleteTarget.title}» будут удалены с устройства. Тайтл останется в онлайн-каталоге.`
            : undefined
        }
        size="sm"
        footer={
          <>
            <button
              type="button"
              className="btn btn--ghost"
              onClick={() => setDeleteTarget(null)}
              disabled={deletingOffline}
            >
              Отмена
            </button>
            <button
              type="button"
              className="btn btn--primary"
              onClick={() => void confirmOfflineDelete()}
              disabled={deletingOffline}
            >
              {deletingOffline ? 'Удаляем…' : 'Удалить'}
            </button>
          </>
        }
      >
        <p className="field__hint">Скачать заново можно в любой момент со страницы тайтла.</p>
      </Modal>
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
