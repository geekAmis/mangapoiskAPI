import { useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { EmptyState } from '../components/EmptyState';
import { ErrorState } from '../components/ErrorState';
import { Icon } from '../components/Icon';
import { Modal } from '../components/Modal';
import { Poster } from '../components/Poster';
import { Skeleton } from '../components/Skeleton';
import {
  cancelDownload,
  retryDownload,
  useDownloadJobs,
} from '../lib/downloadManager';
import {
  chapterHeading,
  chapterSecondaryTitle,
  contentTypeLabel,
  formatDate,
  formatInt,
  formatRating,
  formatRelative,
  pagesLabel,
  pluralRu,
  sourceLabel,
  statusLabel,
} from '../lib/format';
import { useDocumentTitle } from '../lib/hooks';
import { useOfflineTitle } from '../lib/offlineHooks';
import { deleteOfflineChapter, deleteOfflineTitle } from '../lib/offlineStorage';
import {
  formatBytes,
  jobPercent,
  offlineTitleStats,
  sortOfflineChapters,
  type OfflineChapter,
} from '../lib/offlineTypes';
import { toast } from '../stores/toast';

type DeleteTarget =
  | { kind: 'title' }
  | { kind: 'chapter'; chapter: OfflineChapter };

export default function OfflineMangaPage() {
  const { mangaId = '' } = useParams();
  const navigate = useNavigate();
  const { title, loading, error } = useOfflineTitle(mangaId);
  const jobs = useDownloadJobs();
  const [deleteTarget, setDeleteTarget] = useState<DeleteTarget | null>(null);
  const [busy, setBusy] = useState(false);

  useDocumentTitle(
    title ? `${title.title} — офлайн | MangaPoisk Reborn` : 'Офлайн-тайтл — MangaPoisk Reborn',
  );

  const chapters = useMemo(() => (title ? sortOfflineChapters(title.chapters) : []), [title]);
  const stats = useMemo(() => (title ? offlineTitleStats(title) : null), [title]);
  const job = jobs.find(
    (item) => item.mangaId === mangaId && item.status !== 'done' && item.status !== 'cancelled',
  );
  const activeJob = job?.status === 'running' || job?.status === 'queued' ? job : null;

  if (loading) {
    return (
      <div className="page container manga-page offline-manga-page">
        <Skeleton width="260px" height="14px" />
        <div className="manga-hero" style={{ marginTop: 28 }}>
          <div className="manga-poster-column">
            <Skeleton height="420px" style={{ borderRadius: 14 }} />
            <Skeleton height="44px" />
          </div>
          <div className="manga-info" style={{ display: 'grid', gap: 14 }}>
            <Skeleton width="75%" height="46px" />
            <Skeleton width="50%" height="18px" />
            <Skeleton width="38%" height="18px" />
            <Skeleton height="120px" style={{ marginTop: 16, borderRadius: 14 }} />
          </div>
        </div>
      </div>
    );
  }

  if (!title || error) {
    return (
      <div className="page container manga-page offline-manga-page">
        <ErrorState
          title={error ? 'Не удалось открыть офлайн-тайтл' : 'Тайтл не найден на устройстве'}
          message={
            error ??
            'Возможно, он был удалён или ещё не скачан. Скачайте тайтл со страницы манги — он появится в разделе «Скачано».'
          }
          action={
            <Link to="/library?tab=downloads" className="btn btn--primary btn--sm">
              <Icon name="download" size={15} />
              К скачанному
            </Link>
          }
        />
      </div>
    );
  }

  const altTitles = [title.titleEn, title.titleAlt].filter(
    (value): value is string => Boolean(value && value.trim() && value.trim() !== title.title),
  );
  const firstChapter = chapters[0] ?? null;

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    setBusy(true);
    try {
      if (activeJob) await cancelDownload(activeJob.id);
      if (deleteTarget.kind === 'title') {
        await deleteOfflineTitle(title.id);
        toast.success('Тайтл удалён с устройства');
        navigate('/library?tab=downloads');
      } else {
        await deleteOfflineChapter(title.id, deleteTarget.chapter.id);
        toast.success('Глава удалена с устройства');
      }
      setDeleteTarget(null);
    } catch (deleteError: unknown) {
      toast.error(
        deleteError instanceof Error ? deleteError.message : 'Не удалось удалить данные с устройства',
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="page container manga-page offline-manga-page">
      <nav className="breadcrumbs" aria-label="Хлебные крошки">
        <Link to="/library?tab=downloads">Библиотека</Link>
        <Icon name="chevron-right" size={13} />
        <span>Скачано</span>
        <Icon name="chevron-right" size={13} />
        <span aria-current="page">{title.title}</span>
      </nav>

      {activeJob ? (
        <div className="offline-job-banner" role="status">
          <Icon name="download" size={18} />
          <div className="offline-job-banner__body">
            <strong>Скачиваем на устройство · {jobPercent(activeJob)}%</strong>
            <span>
              {formatInt(activeJob.completedChapters)} из {formatInt(activeJob.chapters.length)} глав ·{' '}
              {formatInt(activeJob.downloadedPages)} из {formatInt(activeJob.totalPages)} страниц
            </span>
            <div className="progress">
              <div className="progress__bar" style={{ width: `${jobPercent(activeJob)}%` }} />
            </div>
          </div>
          <button
            type="button"
            className="btn btn--ghost btn--sm"
            onClick={() => void cancelDownload(activeJob.id)}
          >
            Отменить
          </button>
        </div>
      ) : job?.status === 'error' ? (
        <div className="offline-job-banner offline-job-banner--error" role="status">
          <Icon name="alert" size={18} />
          <div className="offline-job-banner__body">
            <strong>Загрузка остановилась</strong>
            <span>{job.error ?? 'Не удалось скачать часть глав.'}</span>
          </div>
          <button type="button" className="btn btn--outline btn--sm" onClick={() => void retryDownload(job.id)}>
            <Icon name="refresh" size={15} />
            Повторить
          </button>
        </div>
      ) : null}

      <div className="manga-hero offline-manga-hero">
        <div className="manga-poster-column">
          <div className="manga-poster-frame">
            <Poster src={title.poster} alt={`Обложка «${title.title}»`} eager />
            <div className="offline-poster-badge">
              <Icon name="check" size={13} />
              На устройстве
            </div>
          </div>

          <div className="manga-side-actions">
            {firstChapter ? (
              <Link
                to={`/offline/read/${title.id}/${firstChapter.id}`}
                className="btn btn--primary btn--block"
              >
                <Icon name="book" size={17} />
                Читать офлайн
              </Link>
            ) : (
              <button type="button" className="btn btn--outline btn--block" disabled>
                <Icon name="book" size={17} />
                Глав нет
              </button>
            )}
            <button
              type="button"
              className="btn btn--ghost btn--block offline-delete-btn"
              onClick={() => setDeleteTarget({ kind: 'title' })}
            >
              <Icon name="trash" size={17} />
              Удалить с устройства
            </button>
          </div>
        </div>

        <div className="manga-info">
          <h1 className="manga-title">{title.title}</h1>
          {altTitles.length > 0 ? <p className="manga-alt-title">{altTitles.join(' · ')}</p> : null}

          <div className="manga-meta-line">
            {title.rating ? (
              <span className="offline-rating" title={`Рейтинг ${formatRating(title.rating)}`}>
                <Icon name="star" size={14} />
                {formatRating(title.rating)}
              </span>
            ) : null}
            <span>{sourceLabel(title.source)}</span>
            <span>Скачано {formatRelative(title.downloadedAt)}</span>
          </div>

          <div className="manga-facts">
            {title.year ? <span className="chip">{title.year}</span> : null}
            {title.status ? <span className="chip">{statusLabel(title.status)}</span> : null}
            {title.contentType ? <span className="chip">{contentTypeLabel(title.contentType)}</span> : null}
            {stats ? (
              <>
                <span className="chip">
                  {formatInt(stats.chapters)}{' '}
                  {pluralRu(stats.chapters, 'глава', 'главы', 'глав')}
                </span>
                <span className="chip">
                  {formatInt(stats.pages)} {pluralRu(stats.pages, 'страница', 'страницы', 'страниц')}
                </span>
                <span className="chip">{formatBytes(stats.bytes)}</span>
              </>
            ) : null}
            {title.adult ? <span className="badge badge--danger">18+</span> : null}
          </div>

          {title.genres.length > 0 ? (
            <div className="manga-genres">
              {title.genres.map((genre) => (
                <span key={genre} className="chip">
                  {genre}
                </span>
              ))}
            </div>
          ) : null}

          <div className="manga-description">
            <div className="manga-description__head">
              <h2>Описание</h2>
            </div>
            <p className="manga-description__text">
              {title.description || 'Описание не сохранилось на устройстве.'}
            </p>
          </div>
        </div>
      </div>

      <div className="manga-content">
        <section className="chapters-panel" aria-labelledby="offline-chapters-title">
          <div className="chapters-head">
            <div>
              <h2 className="chapters-head__title" id="offline-chapters-title">
                Скачанные главы{' '}
                <span className="chapters-head__count">{formatInt(chapters.length)}</span>
              </h2>
              <p className="section-head__sub">
                Только главы, сохранённые на этом устройстве. Доступны без интернета.
              </p>
            </div>
            {stats ? (
              <span className="offline-size-note">
                <Icon name="download" size={14} />
                {formatBytes(stats.bytes)}
              </span>
            ) : null}
          </div>

          {chapters.length > 0 ? (
            <div className="chapter-list">
              {chapters.map((chapter) => {
                const secondary = chapterSecondaryTitle(chapter);
                return (
                  <div className="chapter-row offline-chapter-row" key={chapter.id}>
                    <Link
                      className="chapter-row__main"
                      to={`/offline/read/${title.id}/${chapter.id}`}
                    >
                      <span className="chapter-row__index" aria-hidden="true">
                        <span>{chapter.number || '•'}</span>
                      </span>
                      <span className="chapter-row__info">
                        <span className="chapter-row__heading">{chapterHeading(chapter)}</span>
                        {secondary ? <span className="chapter-row__subtitle">{secondary}</span> : null}
                        <span className="chapter-row__meta">
                          <span>{pagesLabel(chapter.pages.length)}</span>
                          <span aria-hidden="true">·</span>
                          <span>скачано {formatRelative(chapter.downloadedAt)}</span>
                          {chapter.translator ? (
                            <>
                              <span aria-hidden="true">·</span>
                              <span className="chapter-row__translator" title={`Перевод: ${chapter.translator}`}>
                                {chapter.translator}
                              </span>
                            </>
                          ) : null}
                        </span>
                      </span>
                      <span className="chapter-row__tail" aria-hidden="true">
                        <Icon name="chevron-right" size={18} />
                      </span>
                    </Link>
                    <button
                      type="button"
                      className="btn btn--icon btn--ghost chapter-row__export"
                      onClick={() => setDeleteTarget({ kind: 'chapter', chapter })}
                      aria-label={`Удалить главу «${chapterHeading(chapter)}» с устройства`}
                      title="Удалить главу с устройства"
                    >
                      <Icon name="trash" size={17} />
                    </button>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="chapters-empty">
              <EmptyState
                compact
                icon="download"
                title="Скачанных глав пока нет"
                description="Загрузка могла быть отменена или ещё идёт. Вернитесь на страницу тайтла и нажмите «Скачать всё на устройство»."
                action={
                  <Link to={`/manga/${title.id}`} className="btn btn--primary btn--sm">
                    Открыть тайтл
                  </Link>
                }
              />
            </div>
          )}

          {title.lastChapterAt ? (
            <p className="chapter-list__hint">
              Последняя глава в источнике: {formatDate(title.lastChapterAt)}
            </p>
          ) : null}
        </section>
      </div>

      <Modal
        open={Boolean(deleteTarget)}
        onClose={() => (busy ? undefined : setDeleteTarget(null))}
        title={deleteTarget?.kind === 'title' ? 'Удалить тайтл с устройства?' : 'Удалить главу?'}
        description={
          deleteTarget?.kind === 'title'
            ? 'Все скачанные главы и страницы этого тайтла будут удалены с устройства. Он останется в онлайн-каталоге.'
            : deleteTarget?.kind === 'chapter'
              ? `Страницы главы «${chapterHeading(deleteTarget.chapter)}» будут удалены.`
              : undefined
        }
        size="sm"
        footer={
          <>
            <button
              type="button"
              className="btn btn--ghost"
              onClick={() => setDeleteTarget(null)}
              disabled={busy}
            >
              Отмена
            </button>
            <button
              type="button"
              className="btn btn--primary"
              onClick={() => void confirmDelete()}
              disabled={busy}
            >
              {busy ? 'Удаляем…' : 'Удалить'}
            </button>
          </>
        }
      >
        <p className="field__hint">
          Отменить удаление нельзя. Скачать заново можно со страницы тайтла.
        </p>
      </Modal>
    </div>
  );
}
