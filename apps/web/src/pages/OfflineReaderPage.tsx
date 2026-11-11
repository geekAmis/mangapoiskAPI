import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { ErrorState } from '../components/ErrorState';
import { Icon } from '../components/Icon';
import { Skeleton } from '../components/Skeleton';
import { chapterHeading, chapterSecondaryTitle, formatInt, normalizePage, progressPercent } from '../lib/format';
import { useDocumentTitle } from '../lib/hooks';
import { useOfflineTitle } from '../lib/offlineHooks';
import { getOfflinePageUrl, getOfflineProgress, saveOfflineProgress } from '../lib/offlineStorage';
import '../styles/offline-reader.css';
import {
  sortOfflineChapters,
  type OfflineChapter,
  type OfflinePage,
} from '../lib/offlineTypes';

export default function OfflineReaderPage() {
  const { mangaId = '', chapterId = '' } = useParams();
  const [searchParams] = useSearchParams();
  const { title, loading, error } = useOfflineTitle(mangaId);

  const chapters = useMemo(() => (title ? sortOfflineChapters(title.chapters) : []), [title]);
  const chapter = chapters.find((item) => item.id === chapterId) ?? null;
  const chapterIndex = chapters.findIndex((item) => item.id === chapterId);
  const prevChapter = chapterIndex > 0 ? chapters[chapterIndex - 1] : null;
  const nextChapter =
    chapterIndex >= 0 && chapterIndex < chapters.length - 1 ? chapters[chapterIndex + 1] : null;

  useDocumentTitle(
    chapter && title
      ? `${chapterHeading(chapter)} — ${title.title} | офлайн`
      : 'Офлайн-читалка — MangaPoisk Reborn',
  );

  if (loading) {
    return (
      <div className="offline-reader offline-reader--loading">
        <Skeleton width="200px" height="16px" />
        <Skeleton width="100%" height="70vh" style={{ marginTop: 24 }} />
      </div>
    );
  }

  if (!title || !chapter) {
    return (
      <div className="offline-reader offline-reader--message">
        <ErrorState
          title={error ? 'Не удалось открыть офлайн-главу' : 'Глава не найдена на устройстве'}
          message={
            error ??
            'Эта глава не скачана или была удалена. Откройте скачанный тайтл и выберите доступную главу.'
          }
          action={
            <Link to={`/offline/manga/${mangaId}`} className="btn btn--primary btn--sm">
              <Icon name="arrow-left" size={15} />
              К тайтлу
            </Link>
          }
        />
      </div>
    );
  }

  return (
    <OfflineReader
      mangaId={mangaId}
      title={title.title}
      chapter={chapter}
      totalInManga={chapters.length}
      chapterPosition={chapterIndex + 1}
      prevChapter={prevChapter}
      nextChapter={nextChapter}
      initialPage={searchParams.get('page')}
    />
  );
}

interface OfflineReaderProps {
  mangaId: string;
  title: string;
  chapter: OfflineChapter;
  totalInManga: number;
  chapterPosition: number;
  prevChapter: OfflineChapter | null;
  nextChapter: OfflineChapter | null;
  initialPage: string | null;
}

function OfflineReader({
  mangaId,
  title,
  chapter,
  totalInManga,
  chapterPosition,
  prevChapter,
  nextChapter,
  initialPage,
}: OfflineReaderProps) {
  const navigate = useNavigate();
  const pages = useMemo(
    () => [...chapter.pages].sort((a, b) => a.number - b.number),
    [chapter.pages],
  );
  const totalPages = pages.length;
  const [currentPage, setCurrentPage] = useState(1);
  const [resumePage, setResumePage] = useState<number | null>(null);
  const [progressLoaded, setProgressLoaded] = useState(false);
  const initialScrollDone = useRef(false);
  const savedPageRef = useRef(1);
  const currentPageRef = useRef(1);

  useEffect(() => {
    currentPageRef.current = currentPage;
  }, [currentPage]);

  useEffect(() => {
    let alive = true;
    initialScrollDone.current = false;
    setCurrentPage(1);
    savedPageRef.current = 1;
    setResumePage(null);
    setProgressLoaded(false);

    void getOfflineProgress(mangaId, chapter.id)
      .then((progress) => {
        if (!alive) return;
        if (progress && progress.page > 1 && progress.page <= totalPages) {
          setResumePage(progress.page);
        }
        setProgressLoaded(true);
      })
      .catch(() => {
        if (alive) setProgressLoaded(true);
      });

    return () => {
      alive = false;
    };
  }, [mangaId, chapter.id, totalPages]);

  useEffect(() => {
    if (initialScrollDone.current || totalPages === 0 || !progressLoaded) return;
    const requested = normalizePage(initialPage, totalPages);
    const target = initialPage ? requested : resumePage && resumePage <= totalPages ? resumePage : 1;
    initialScrollDone.current = true;
    setCurrentPage(target);
    savedPageRef.current = target;
    const timer = window.setTimeout(() => scrollToPage(target), 60);
    return () => window.clearTimeout(timer);
  }, [initialPage, resumePage, totalPages, progressLoaded]);

  useEffect(() => {
    let frame = 0;
    const update = () => {
      frame = 0;
      const elements = Array.from(
        document.querySelectorAll<HTMLElement>('[data-offline-page]'),
      );
      if (elements.length === 0) return;
      const viewportCenter = window.innerHeight / 2;
      let bestPage = currentPageRef.current;
      let bestDistance = Number.POSITIVE_INFINITY;
      for (const element of elements) {
        const rect = element.getBoundingClientRect();
        if (rect.bottom < 0 || rect.top > window.innerHeight) continue;
        const center = rect.top + rect.height / 2;
        const distance = Math.abs(center - viewportCenter);
        if (distance < bestDistance) {
          bestDistance = distance;
          const value = Number(element.dataset.offlinePage);
          if (Number.isFinite(value) && value > 0) bestPage = value;
        }
      }
      setCurrentPage((previous) => (previous === bestPage ? previous : bestPage));
    };
    const onScroll = () => {
      if (frame) return;
      frame = window.requestAnimationFrame(update);
    };
    window.addEventListener('scroll', onScroll, { passive: true });
    update();
    return () => {
      window.removeEventListener('scroll', onScroll);
      if (frame) window.cancelAnimationFrame(frame);
    };
  }, [chapter.id, totalPages]);

  useEffect(() => {
    if (totalPages === 0 || currentPage < 1) return;
    const timer = window.setTimeout(() => {
      if (savedPageRef.current === currentPage) return;
      savedPageRef.current = currentPage;
      void saveOfflineProgress({
        mangaId,
        chapterId: chapter.id,
        page: currentPage,
        totalPages,
        updatedAt: new Date().toISOString(),
      });
    }, 700);
    return () => window.clearTimeout(timer);
  }, [mangaId, chapter.id, currentPage, totalPages]);

  useEffect(
    () => () => {
      if (totalPages === 0) return;
      void saveOfflineProgress({
        mangaId,
        chapterId: chapter.id,
        page: currentPageRef.current,
        totalPages,
        updatedAt: new Date().toISOString(),
      });
    },
    [mangaId, chapter.id, totalPages],
  );

  const scrollToPage = (page: number) => {
    const target = Math.min(Math.max(1, page), totalPages || 1);
    setCurrentPage(target);
    document.getElementById(`offline-reader-page-${target}`)?.scrollIntoView({
      block: 'start',
      behavior: 'auto',
    });
  };

  const goChapter = (target: OfflineChapter | null) => {
    if (target) {
      navigate(`/offline/read/${mangaId}/${target.id}`);
    }
  };

  return (
    <div className="offline-reader">
      <header className="offline-reader__header">
        <Link
          to={`/offline/manga/${mangaId}`}
          className="offline-reader__back"
          aria-label="К оглавлению скачанного тайтла"
          title="К оглавлению"
        >
          <Icon name="arrow-left" size={20} />
        </Link>
        <div className="offline-reader__titles">
          <Link to={`/offline/manga/${mangaId}`} className="offline-reader__manga">
            {title}
          </Link>
          <span className="offline-reader__chapter">
            {chapterHeading(chapter)}
            {chapterSecondaryTitle(chapter) ? ` · ${chapterSecondaryTitle(chapter)}` : ''}
          </span>
          <span className="offline-reader__meta">
            Офлайн · глава {Math.max(1, chapterPosition)} из {formatInt(totalInManga)} скачанных
          </span>
        </div>
        <span className="offline-reader__counter" aria-hidden="true">
          <strong>{currentPage}</strong> / {totalPages}
        </span>
      </header>

      <div className="offline-reader__header-progress" aria-hidden="true">
        <span style={{ width: `${progressPercent(currentPage, totalPages)}%` }} />
      </div>

      <span className="sr-only" aria-live="polite">
        Страница {currentPage} из {totalPages}
      </span>

      <main className="offline-reader__main">
        {pages.length > 0 ? (
          <div className="offline-reader__pages">
            {pages.map((page) => (
              <OfflinePageImage
                key={`${chapter.id}-${page.number}`}
                page={page}
                totalPages={totalPages}
                title={title}
              />
            ))}
          </div>
        ) : (
          <div className="offline-reader__empty">
            <Icon name="alert" size={28} />
            <h2>Страницы не найдены</h2>
            <p>В манифесте главы нет сохранённых изображений. Скачайте главу заново.</p>
          </div>
        )}
      </main>

      <footer className="offline-reader__footer">
        <div className="offline-reader__footer-inner">
          <ChapterNav direction="prev" chapter={prevChapter} onNavigate={goChapter} />
          <div className="offline-reader__progress">
            <div className="offline-reader__progress-text">
              <span>
                <strong>{currentPage}</strong> / {totalPages}
              </span>
              <span>{progressPercent(currentPage, totalPages)}%</span>
            </div>
            <input
              className="offline-reader__range"
              type="range"
              min={1}
              max={Math.max(1, totalPages)}
              step={1}
              value={currentPage}
              onChange={(event) => scrollToPage(Number(event.target.value))}
              aria-label="Перейти к странице"
            />
          </div>
          <ChapterNav direction="next" chapter={nextChapter} onNavigate={goChapter} />
        </div>
      </footer>
    </div>
  );
}

function ChapterNav({
  direction,
  chapter,
  onNavigate,
}: {
  direction: 'prev' | 'next';
  chapter: OfflineChapter | null;
  onNavigate: (chapter: OfflineChapter | null) => void;
}) {
  const isPrev = direction === 'prev';
  const label = isPrev ? 'Предыдущая глава' : 'Следующая глава';
  if (!chapter) {
    return (
      <span className="offline-reader__nav is-disabled" aria-disabled="true" title={`${label} недоступна`}>
        <Icon name={isPrev ? 'chevron-left' : 'chevron-right'} size={18} />
        <span>{isPrev ? 'Назад' : 'Вперёд'}</span>
      </span>
    );
  }
  return (
    <button
      type="button"
      className="offline-reader__nav"
      onClick={() => onNavigate(chapter)}
      title={`${label}: ${chapterHeading(chapter)}`}
      aria-label={`${label}: ${chapterHeading(chapter)}`}
    >
      {isPrev ? <Icon name="chevron-left" size={18} /> : null}
      <span>{isPrev ? 'Назад' : 'Вперёд'}</span>
      {isPrev ? null : <Icon name="chevron-right" size={18} />}
    </button>
  );
}

function OfflinePageImage({
  page,
  totalPages,
  title,
}: {
  page: OfflinePage;
  totalPages: number;
  title: string;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    setUrl(null);
    setFailed(false);
    void getOfflinePageUrl(page)
      .then((value) => {
        if (alive) setUrl(value);
      })
      .catch(() => {
        if (alive) setFailed(true);
      });
    return () => {
      alive = false;
    };
  }, [page]);

  const ratio = page.width && page.height ? `${page.width} / ${page.height}` : '2 / 3';

  return (
    <figure
      className="offline-reader__page"
      id={`offline-reader-page-${page.number}`}
      data-offline-page={page.number}
    >
      <div className="offline-reader__frame" style={{ aspectRatio: ratio }}>
        {url ? (
          <img
            src={url}
            alt={`Страница ${page.number} манги «${title}»`}
            loading={page.number <= 2 ? 'eager' : 'lazy'}
            decoding="async"
            draggable={false}
          />
        ) : failed ? (
          <div className="offline-reader__page-error">
            <Icon name="alert" size={24} />
            <span>Страница {page.number} не найдена на устройстве</span>
          </div>
        ) : (
          <div className="offline-reader__page-loading" aria-hidden="true">
            <span />
          </div>
        )}
      </div>
      <figcaption>
        {page.number} / {totalPages}
      </figcaption>
    </figure>
  );
}
