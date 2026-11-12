import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
  type TouchEvent as ReactTouchEvent,
} from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { ErrorState } from '../components/ErrorState';
import { Icon } from '../components/Icon';
import { Modal } from '../components/Modal';
import { SearchBox } from '../components/SearchBox';
import { Skeleton } from '../components/Skeleton';
import { useReaderZoom } from '../components/ReaderZoom';
import { ThemePicker } from '../components/ThemeSwitcher';
import {
  chapterHeading,
  chapterSecondaryTitle,
  formatInt,
  formatRelative,
  normalizePage,
  pagesLabel,
  progressPercent,
} from '../lib/format';
import { useDocumentTitle, useReducedMotion } from '../lib/hooks';
import { useOfflineTitle } from '../lib/offlineHooks';
import { getOfflinePageUrl, getOfflineProgress, saveOfflineProgress } from '../lib/offlineStorage';
import {
  type PageFit,
  type ReaderGap,
  type ReaderMode,
  useReaderStore,
} from '../stores/reader';
import { toast } from '../stores/toast';
import '../styles/offline-reader.css';
import {
  sortOfflineChapters,
  type OfflineChapter,
  type OfflinePage,
} from '../lib/offlineTypes';

const OFFLINE_PAGE_PREFIX = 'offline-reader-page-';
const FOCUSABLE_SKIP = new Set(['INPUT', 'TEXTAREA', 'SELECT']);
const TAP_AFTER_CLOSE_GUARD_MS = 420;

const TALL_PAGE_RATIO = 2.2;

function pageRatio(page: OfflinePage): string {
  if (page.width && page.height) return `${page.width} / ${page.height}`;
  return '2 / 3';
}

/** Tall webtoon strips get a full-width, vertically scrollable paged view. */
function isTallPage(page: OfflinePage | null | undefined): boolean {
  if (!page?.width || !page?.height) return false;
  return page.height / page.width > TALL_PAGE_RATIO;
}

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

  useLayoutEffect(() => {
    const root = document.documentElement;
    const previous = root.dataset.reader;
    root.dataset.reader = 'true';
    return () => {
      if (previous) root.dataset.reader = previous;
      else delete root.dataset.reader;
    };
  }, []);

  useDocumentTitle(
    chapter && title
      ? `${chapterHeading(chapter)} — ${title.title} | офлайн`
      : 'Офлайн-читалка — MangaPoisk Reborn',
  );

  if (loading) {
    return (
      <div className="reader offline-reader offline-reader--boot" aria-busy="true">
        <div className="offline-reader__boot-card">
          <Skeleton width="min(260px, 62vw)" height="12px" />
          <Skeleton width="min(320px, 76vw)" height="22px" />
          <Skeleton width="min(180px, 46vw)" height="12px" />
          <Skeleton
            width="min(100% - 32px, 780px)"
            height="62dvh"
            style={{ marginTop: 18, borderRadius: 8 }}
          />
        </div>
      </div>
    );
  }

  if (!title || !chapter) {
    return (
      <div className="reader offline-reader offline-reader--message">
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
      chapters={chapters}
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
  chapters: OfflineChapter[];
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
  chapters,
  chapter,
  totalInManga,
  chapterPosition,
  prevChapter,
  nextChapter,
  initialPage,
}: OfflineReaderProps) {
  const navigate = useNavigate();
  const reducedMotion = useReducedMotion();

  const mode = useReaderStore((state) => state.mode);
  const pageFit = useReaderStore((state) => state.pageFit);
  const gap = useReaderStore((state) => state.gap);
  const autoScroll = useReaderStore((state) => state.autoScroll);
  const autoScrollSpeed = useReaderStore((state) => state.autoScrollSpeed);
  const showPageNumbers = useReaderStore((state) => state.showPageNumbers);
  const updatePrefs = useReaderStore((state) => state.update);
  const resetPrefs = useReaderStore((state) => state.reset);

  const pages = useMemo(
    () => [...chapter.pages].sort((a, b) => a.number - b.number),
    [chapter.pages],
  );
  const totalPages = pages.length;

  const [currentPage, setCurrentPage] = useState(1);
  const [resumePage, setResumePage] = useState<number | null>(null);
  const [progressLoaded, setProgressLoaded] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [chaptersOpen, setChaptersOpen] = useState(false);
  const [chapterFilter, setChapterFilter] = useState('');
  const [chromeHidden, setChromeHidden] = useState(false);
  const [chromeVisible, setChromeVisible] = useState(true);
  const [autoPaused, setAutoPaused] = useState(false);

  const initialScrollDone = useRef(false);
  const progressChapterRef = useRef<string | null>(null);
  const savedPageRef = useRef(1);
  const currentPageRef = useRef(1);
  const lastSwipeAtRef = useRef(0);
  const touchStartRef = useRef<{ x: number; y: number } | null>(null);
  const pagedMultiTouchRef = useRef(false);
  const tapTimerRef = useRef<number | null>(null);
  const closedChromeAtRef = useRef(0);
  const autoPausedBeforeSettingsRef = useRef(false);

  const cancelPendingTap = useCallback(() => {
    if (tapTimerRef.current !== null) {
      window.clearTimeout(tapTimerRef.current);
      tapTimerRef.current = null;
    }
  }, []);

  const zoom = useReaderZoom({
    mode,
    resetKey: chapter.id,
    rootKey: `${chapter.id}:${mode}`,
    onDoubleTap: cancelPendingTap,
    onGestureStart: cancelPendingTap,
  });

  useEffect(() => {
    currentPageRef.current = currentPage;
  }, [currentPage]);

  useEffect(() => {
    let alive = true;
    initialScrollDone.current = false;
    progressChapterRef.current = null;
    setCurrentPage(1);
    savedPageRef.current = 1;
    setResumePage(null);
    setProgressLoaded(false);
    setSettingsOpen(false);
    setChaptersOpen(false);
    setChapterFilter('');
    setChromeHidden(false);
    setChromeVisible(true);
    setAutoPaused(false);
    cancelPendingTap();
    window.scrollTo({ top: 0, left: 0, behavior: 'auto' });

    void getOfflineProgress(mangaId, chapter.id)
      .then((progress) => {
        if (!alive) return;
        if (progress && progress.page > 1 && progress.page <= totalPages) {
          setResumePage(progress.page);
        }
        progressChapterRef.current = chapter.id;
        setProgressLoaded(true);
      })
      .catch(() => {
        if (!alive) return;
        progressChapterRef.current = chapter.id;
        setProgressLoaded(true);
      });

    return () => {
      alive = false;
      cancelPendingTap();
    };
  }, [mangaId, chapter.id, totalPages, cancelPendingTap]);

  const scrollToPage = useCallback(
    (page: number, smooth = true) => {
      const target = Math.min(Math.max(1, page), totalPages || 1);
      setCurrentPage(target);
      if (mode === 'vertical') {
        document.getElementById(`${OFFLINE_PAGE_PREFIX}${target}`)?.scrollIntoView({
          block: 'start',
          behavior: smooth && !reducedMotion ? 'smooth' : 'auto',
        });
      }
    },
    [mode, reducedMotion, totalPages],
  );

  useEffect(() => {
    if (initialScrollDone.current || totalPages === 0 || !progressLoaded) return;
    // Guard against the render where the previous chapter's resume state is
    // still in memory: only the progress record of this chapter may position
    // the first scroll.
    if (progressChapterRef.current !== chapter.id) return;
    const requested = initialPage ? normalizePage(initialPage, totalPages) : null;
    const target =
      requested ?? (resumePage && resumePage > 1 && resumePage <= totalPages ? resumePage : 1);
    initialScrollDone.current = true;
    setCurrentPage(target);
    savedPageRef.current = target;
    if (mode !== 'vertical') return;
    const timer = window.setTimeout(() => {
      document.getElementById(`${OFFLINE_PAGE_PREFIX}${target}`)?.scrollIntoView({
        block: 'start',
        behavior: 'auto',
      });
    }, 60);
    return () => window.clearTimeout(timer);
  }, [chapter.id, initialPage, resumePage, totalPages, progressLoaded, mode]);

  useEffect(() => {
    if (mode !== 'vertical' || totalPages === 0) return;
    let frame = 0;
    const update = () => {
      frame = 0;
      const elements = Array.from(document.querySelectorAll<HTMLElement>('[data-offline-page]'));
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
  }, [mode, chapter.id, totalPages]);

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

  useEffect(() => {
    if (mode !== 'vertical') {
      setChromeHidden(false);
      return;
    }
    let lastY = window.scrollY;
    const onScroll = () => {
      const y = window.scrollY;
      if (y < 80) setChromeHidden(false);
      else if (y > lastY + 8) setChromeHidden(true);
      else if (y < lastY - 8) setChromeHidden(false);
      lastY = y;
    };
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, [mode]);

  const autoScrollActive = autoScroll && mode === 'vertical' && !reducedMotion && totalPages > 0;

  useEffect(() => {
    if (!autoScrollActive || autoPaused) return;
    let frame = 0;
    let last = performance.now();
    const tick = (now: number) => {
      const delta = Math.min(0.06, (now - last) / 1000);
      last = now;
      const atBottom =
        window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 6;
      if (atBottom) {
        updatePrefs({ autoScroll: false });
        setAutoPaused(false);
        toast.success('Глава дочитана');
        return;
      }
      window.scrollBy(0, autoScrollSpeed * delta);
      frame = window.requestAnimationFrame(tick);
    };
    frame = window.requestAnimationFrame(tick);
    return () => window.cancelAnimationFrame(frame);
  }, [autoScrollActive, autoPaused, autoScrollSpeed, updatePrefs]);

  useEffect(() => {
    if (!chaptersOpen) return;
    const timer = window.setTimeout(() => {
      document.getElementById('offline-reader-chapter-current')?.scrollIntoView({ block: 'center' });
    }, 90);
    return () => window.clearTimeout(timer);
  }, [chaptersOpen, chapters]);

  const closeSettings = useCallback(() => {
    closedChromeAtRef.current = Date.now();
    setSettingsOpen(false);
    if (!autoPausedBeforeSettingsRef.current) setAutoPaused(false);
  }, []);

  const closeChapters = useCallback(() => {
    setChaptersOpen(false);
  }, []);

  const openSettings = useCallback(() => {
    autoPausedBeforeSettingsRef.current = autoPaused;
    setAutoPaused(true);
    setChromeHidden(false);
    setChromeVisible(true);
    setSettingsOpen(true);
  }, [autoPaused]);

  const openChapters = useCallback(() => {
    setAutoPaused(true);
    setChromeHidden(false);
    setChromeVisible(true);
    setChaptersOpen(true);
  }, []);

  const pauseAutoScroll = useCallback(() => {
    if (autoScrollActive && !autoPaused) setAutoPaused(true);
  }, [autoScrollActive, autoPaused]);

  const goToPage = (page: number) => {
    if (totalPages === 0) return;
    scrollToPage(page, true);
  };

  const goPrevPage = useCallback(() => {
    if (currentPage > 1) {
      if (mode === 'vertical') scrollToPage(currentPage - 1, false);
      else setCurrentPage(currentPage - 1);
    }
    pauseAutoScroll();
  }, [currentPage, pauseAutoScroll, mode, scrollToPage]);

  const goNextPage = useCallback(() => {
    if (currentPage < totalPages) {
      if (mode === 'vertical') scrollToPage(currentPage + 1, false);
      else setCurrentPage(currentPage + 1);
    }
    pauseAutoScroll();
  }, [currentPage, pauseAutoScroll, mode, scrollToPage, totalPages]);

  const goChapter = useCallback(
    (direction: 'prev' | 'next') => {
      const target = direction === 'prev' ? prevChapter : nextChapter;
      if (!target) {
        toast.info(direction === 'prev' ? 'Это первая скачанная глава' : 'Это последняя скачанная глава');
        return;
      }
      navigate(`/offline/read/${mangaId}/${target.id}`);
    },
    [mangaId, navigate, nextChapter, prevChapter],
  );

  const changeMode = (nextMode: ReaderMode) => {
    updatePrefs({ mode: nextMode });
    if (nextMode === 'vertical') {
      window.setTimeout(() => {
        document
          .getElementById(`${OFFLINE_PAGE_PREFIX}${currentPageRef.current}`)
          ?.scrollIntoView({ block: 'start' });
      }, 80);
    }
  };

  const toggleFullscreen = async () => {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await document.documentElement.requestFullscreen();
    } catch {
      toast.info('Полноэкранный режим недоступен в этом браузере');
    }
  };

  const handleTap = (action: () => void) => {
    if (Date.now() - closedChromeAtRef.current < TAP_AFTER_CLOSE_GUARD_MS) return;
    if (Date.now() - lastSwipeAtRef.current < 450) return;
    pauseAutoScroll();
    action();
  };

  const runTap = (action: () => void, event: ReactMouseEvent<HTMLElement>) => {
    if (zoom.shouldSuppressClick()) return;
    if (Date.now() - closedChromeAtRef.current < TAP_AFTER_CLOSE_GUARD_MS) return;
    const pointerType = (event.nativeEvent as PointerEvent).pointerType;
    const touchDriven = pointerType === 'touch' || pointerType === 'pen';
    if (!zoom.enabled || !touchDriven) {
      handleTap(action);
      return;
    }
    if (tapTimerRef.current !== null) {
      cancelPendingTap();
      return;
    }
    tapTimerRef.current = window.setTimeout(() => {
      tapTimerRef.current = null;
      handleTap(action);
    }, 230);
  };

  const toggleChrome = () => {
    setChromeHidden(false);
    setChromeVisible((value) => !value);
  };

  const onVerticalClick = (event: ReactMouseEvent<HTMLElement>) => {
    const target = event.target as HTMLElement;
    if (target.tagName !== 'IMG') return;
    if (zoom.isZoomedRef.current) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const x = event.clientX - rect.left;
    if (x > rect.width * 0.3 && x < rect.width * 0.7) {
      runTap(toggleChrome, event);
    }
  };

  const onPagedClick = (event: ReactMouseEvent<HTMLElement>) => {
    const target = event.target as HTMLElement;
    if (target.closest('button, a, input, select, textarea')) return;
    if (zoom.isZoomedRef.current) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const x = event.clientX - rect.left;
    if (x < rect.width * 0.3) runTap(goPrevPage, event);
    else if (x > rect.width * 0.7) runTap(goNextPage, event);
    else runTap(toggleChrome, event);
  };

  const onPagedTouchStart = (event: ReactTouchEvent<HTMLDivElement>) => {
    if (event.touches.length > 1) {
      pagedMultiTouchRef.current = true;
      touchStartRef.current = null;
      return;
    }
    if (zoom.isZoomedRef.current) {
      touchStartRef.current = null;
      return;
    }
    const touch = event.touches[0];
    touchStartRef.current = { x: touch.clientX, y: touch.clientY };
    if (autoScrollActive && !autoPaused) setAutoPaused(true);
  };

  const onPagedTouchEnd = (event: ReactTouchEvent<HTMLDivElement>) => {
    if (pagedMultiTouchRef.current) {
      if (event.touches.length === 0) pagedMultiTouchRef.current = false;
      touchStartRef.current = null;
      return;
    }
    if (zoom.isZoomedRef.current) {
      touchStartRef.current = null;
      return;
    }
    const start = touchStartRef.current;
    touchStartRef.current = null;
    if (!start) return;
    const touch = event.changedTouches[0];
    const deltaX = touch.clientX - start.x;
    const deltaY = touch.clientY - start.y;
    if (Math.abs(deltaX) > 52 && Math.abs(deltaX) > Math.abs(deltaY) * 1.3) {
      lastSwipeAtRef.current = Date.now();
      pauseAutoScroll();
      if (deltaX < 0) {
        if (currentPage < totalPages) setCurrentPage((page) => Math.min(totalPages, page + 1));
      } else if (currentPage > 1) {
        setCurrentPage((page) => Math.max(1, page - 1));
      }
    }
  };

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && (FOCUSABLE_SKIP.has(target.tagName) || target.isContentEditable)) return;
      if (settingsOpen || chaptersOpen) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;

      switch (event.key) {
        case 'ArrowLeft':
          event.preventDefault();
          if (mode === 'horizontal' && !event.shiftKey) goPrevPage();
          else goChapter('prev');
          break;
        case 'ArrowRight':
          event.preventDefault();
          if (mode === 'horizontal' && !event.shiftKey) goNextPage();
          else goChapter('next');
          break;
        case 'ArrowDown':
        case 'ArrowUp':
          if (autoScrollActive && !autoPaused) setAutoPaused(true);
          break;
        case ' ':
          if (mode === 'horizontal') {
            event.preventDefault();
            if (event.shiftKey) goPrevPage();
            else goNextPage();
          }
          break;
        case 'Home':
          if (mode === 'horizontal') {
            event.preventDefault();
            goToPage(1);
          }
          break;
        case 'End':
          if (mode === 'horizontal') {
            event.preventDefault();
            goToPage(totalPages);
          }
          break;
        case 'f':
        case 'F':
          event.preventDefault();
          void toggleFullscreen();
          break;
        case 's':
        case 'S':
          event.preventDefault();
          openSettings();
          break;
        case 'Escape':
          closeSettings();
          closeChapters();
          break;
        default:
          break;
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  });

  useEffect(() => {
    if (mode !== 'horizontal') return;
    const container = zoom.rootRef.current;
    if (container) container.scrollTop = 0;
  }, [currentPage, mode, chapter.id, zoom.rootRef]);

  const currentPageData = pages[currentPage - 1];
  const currentPageIsTall = isTallPage(currentPageData);

  const chaptersForSheet = useMemo(() => {
    const query = chapterFilter.trim().toLowerCase();
    if (!query) return chapters;
    return chapters.filter((item) =>
      `${chapterHeading(item)} ${item.title} ${item.number} ${item.volume ?? ''}`
        .toLowerCase()
        .includes(query),
    );
  }, [chapters, chapterFilter]);

  const headerHidden = !chromeVisible || (mode === 'vertical' && chromeHidden);
  const readerClass = `reader reader--${mode} offline-reader${!chromeVisible ? ' is-chrome-hidden' : ''}`;
  const secondary = chapterSecondaryTitle(chapter);

  const resetSettings = () => {
    const wasHorizontal = mode === 'horizontal';
    resetPrefs();
    setAutoPaused(false);
    if (wasHorizontal) {
      window.setTimeout(() => {
        document
          .getElementById(`${OFFLINE_PAGE_PREFIX}${currentPageRef.current}`)
          ?.scrollIntoView({ block: 'start' });
      }, 80);
    }
    toast.info('Настройки читалки сброшены');
  };

  return (
    <div className={readerClass} style={{ ['--reader-gap' as string]: `${gap}px` }}>
      <header className={`reader-header${headerHidden ? ' is-hidden' : ''}`}>
        <div className="reader-header__inner">
          <Link
            to={`/offline/manga/${mangaId}`}
            className="reader-header__titles"
            aria-label={`К оглавлению «${title}»`}
            title="К оглавлению"
          >
            <span className="reader-header__manga">{title}</span>
            <span className="reader-header__chapter" title={chapterHeading(chapter)}>
              {chapterHeading(chapter)}
              {secondary ? ` · ${secondary}` : ''}
            </span>
            <span className="reader-header__meta">
              <span className="reader-header__offline">
                <Icon name="download" size={10} />
                Офлайн
              </span>
              <span aria-hidden="true">·</span>
              <span>
                {Math.max(1, chapterPosition)} из {formatInt(totalInManga)}
              </span>
              <span aria-hidden="true">·</span>
              <span>{formatInt(totalPages)} стр.</span>
            </span>
          </Link>

          <span className="reader-header__counter" aria-hidden="true">
            <strong>{currentPage}</strong> / {totalPages}
          </span>

          <div className="reader-header__actions">
            <span
              className="reader-header__offline-badge"
              role="img"
              aria-label="Глава доступна без сети"
              title="Глава доступна без сети"
            >
              <Icon name="check" size={17} />
            </span>
            <button
              type="button"
              className="btn btn--ghost btn--icon"
              onClick={openSettings}
              aria-label="Настройки чтения"
              aria-haspopup="dialog"
              aria-expanded={settingsOpen}
              title="Настройки (S)"
            >
              <Icon name="settings" size={19} />
            </button>
            <Link
              to={`/offline/manga/${mangaId}`}
              className="btn btn--ghost btn--icon reader-header__close"
              aria-label="Закрыть читалку"
              title="Закрыть читалку"
            >
              <Icon name="close" size={20} />
            </Link>
          </div>
        </div>
        <div
          className="reader-progress"
          role="progressbar"
          aria-label="Прогресс главы"
          aria-valuemin={1}
          aria-valuemax={Math.max(1, totalPages)}
          aria-valuenow={currentPage}
        >
          <div
            className="reader-progress__bar"
            style={{ width: `${progressPercent(currentPage, totalPages)}%` }}
          />
        </div>
      </header>

      <span className="sr-only" aria-live="polite">
        Страница {currentPage} из {totalPages}
      </span>

      {pages.length === 0 ? (
        <main className="reader-main reader-main--vertical">
          <div className="offline-reader__empty">
            <Icon name="alert" size={28} />
            <h2>Страницы не найдены</h2>
            <p>В манифесте главы нет сохранённых изображений. Скачайте главу заново.</p>
            <Link to={`/offline/manga/${mangaId}`} className="btn btn--outline btn--sm">
              <Icon name="arrow-left" size={15} />
              К оглавлению
            </Link>
          </div>
        </main>
      ) : mode === 'vertical' ? (
        <main
          ref={zoom.rootRef}
          className="reader-main reader-main--vertical"
          onWheel={() => {
            if (autoScrollActive && !autoPaused) setAutoPaused(true);
          }}
          onTouchStart={() => {
            if (autoScrollActive && !autoPaused) setAutoPaused(true);
          }}
          onClick={onVerticalClick}
        >
          <div className="reader-pages">
            {pages.map((page, index) => (
              <OfflinePageImage
                key={`${chapter.id}-${page.number}-${index}`}
                page={page}
                index={index + 1}
                fit={pageFit}
                showLabel={showPageNumbers}
                eager={index < 2}
                title={title}
              />
            ))}
          </div>
        </main>
      ) : (
        <main
          ref={zoom.rootRef}
          className={`reader-paged${currentPageIsTall ? ' reader-paged--tall' : ''}`}
          onTouchStart={onPagedTouchStart}
          onTouchEnd={onPagedTouchEnd}
          onClick={onPagedClick}
        >
          <div className="reader-paged__stage">
            {currentPageData ? (
              <OfflinePagedImage
                key={`${chapter.id}-${currentPageData.number}`}
                page={currentPageData}
                index={currentPage}
                fit={pageFit}
                tall={currentPageIsTall}
                title={title}
              />
            ) : null}
          </div>

          <button
            type="button"
            className="reader-paged__arrow reader-paged__arrow--left"
            aria-label="Предыдущая страница"
            onClick={() => handleTap(goPrevPage)}
            disabled={currentPage <= 1}
          >
            <Icon name="chevron-left" size={22} />
          </button>
          <button
            type="button"
            className="reader-paged__arrow reader-paged__arrow--right"
            aria-label="Следующая страница"
            onClick={() => handleTap(goNextPage)}
            disabled={currentPage >= totalPages}
          >
            <Icon name="chevron-right" size={22} />
          </button>
        </main>
      )}

      {zoom.enabled && zoom.isZoomed ? (
        <button
          type="button"
          className="reader-zoom-reset"
          onClick={zoom.reset}
          aria-label="Сбросить масштаб"
        >
          <Icon name="maximize" size={14} />
          <strong>{zoom.scale.toFixed(1)}×</strong>
          <span>Сброс</span>
        </button>
      ) : null}

      {autoScrollActive ? (
        <div className={`reader-autoscroll${autoPaused ? ' is-paused' : ''}`} role="status">
          <Icon name={autoPaused ? 'pause' : 'scroll'} size={16} />
          <span className="reader-autoscroll__label">
            {autoPaused ? 'Пауза' : 'Автопрокрутка'} · <strong>{autoScrollSpeed} px/с</strong>
          </span>
          <button
            type="button"
            className="reader-autoscroll__btn"
            onClick={() => setAutoPaused((paused) => !paused)}
          >
            <Icon name={autoPaused ? 'play' : 'pause'} size={13} />
            {autoPaused ? 'Продолжить' : 'Пауза'}
          </button>
          <button
            type="button"
            className="reader-autoscroll__btn"
            onClick={() => {
              updatePrefs({ autoScroll: false });
              setAutoPaused(false);
            }}
            aria-label="Выключить автопрокрутку"
          >
            <Icon name="close" size={13} />
          </button>
        </div>
      ) : null}

      <footer className="reader-footer">
        <div className="reader-footer__inner">
          <div className="reader-footer__side">
            <button
              type="button"
              className="reader-footer__chapter-btn"
              onClick={() => goChapter('prev')}
              disabled={!prevChapter}
              title={prevChapter ? `Предыдущая: ${chapterHeading(prevChapter)}` : 'Первая скачанная глава'}
              aria-label={
                prevChapter ? `Предыдущая глава: ${chapterHeading(prevChapter)}` : 'Первая скачанная глава'
              }
            >
              <Icon name="chevron-left" size={18} />
              <span>Глава</span>
            </button>
          </div>

          <div className="reader-footer__center">
            <button
              type="button"
              className="reader-footer__counter"
              onClick={openChapters}
              aria-label={`Выбрать скачанную главу · страница ${currentPage} из ${totalPages}`}
              aria-haspopup="dialog"
              aria-expanded={chaptersOpen}
              title="Скачанные главы"
            >
              <strong>{currentPage}</strong> / {totalPages}
              <Icon name="chevron-down" size={13} />
            </button>
            <input
              className="reader-slider"
              type="range"
              min={1}
              max={Math.max(1, totalPages)}
              step={1}
              value={currentPage}
              onChange={(event) => goToPage(Number(event.target.value))}
              aria-label="Перейти к странице"
              disabled={totalPages <= 1}
            />
            <div className="reader-footer__mode" role="group" aria-label="Режим чтения">
              <button
                type="button"
                className={mode === 'vertical' ? 'is-active' : ''}
                onClick={() => changeMode('vertical')}
                aria-label="Непрерывный режим"
                aria-pressed={mode === 'vertical'}
                title="Непрерывный режим (вебтун)"
              >
                <Icon name="scroll" size={16} />
              </button>
              <button
                type="button"
                className={mode === 'horizontal' ? 'is-active' : ''}
                onClick={() => changeMode('horizontal')}
                aria-label="Постраничный режим"
                aria-pressed={mode === 'horizontal'}
                title="Постраничный режим"
              >
                <Icon name="columns" size={16} />
              </button>
            </div>
          </div>

          <div className="reader-footer__side reader-footer__side--next">
            <button
              type="button"
              className="reader-footer__chapter-btn"
              onClick={() => goChapter('next')}
              disabled={!nextChapter}
              title={nextChapter ? `Следующая: ${chapterHeading(nextChapter)}` : 'Последняя скачанная глава'}
              aria-label={
                nextChapter ? `Следующая глава: ${chapterHeading(nextChapter)}` : 'Последняя скачанная глава'
              }
            >
              <span>Глава</span>
              <Icon name="chevron-right" size={18} />
            </button>
          </div>
        </div>
      </footer>

      <Modal
        open={settingsOpen}
        onClose={closeSettings}
        title="Настройки чтения"
        description="Изменения применяются сразу и сохраняются на этом устройстве."
        variant="sheet"
        footer={
          <>
            <button type="button" className="btn btn--ghost" onClick={resetSettings}>
              Сбросить
            </button>
            <button type="button" className="btn btn--primary" onClick={closeSettings}>
              Готово
            </button>
          </>
        }
      >
        <div className="reader-settings">
          <section className="reader-settings__group">
            <h3 className="reader-settings__title">
              <Icon name="palette" size={14} /> Тема
            </h3>
            <ThemePicker compact />
          </section>

          <section className="reader-settings__group">
            <h3 className="reader-settings__title">
              <Icon name="columns" size={14} /> Режим чтения
            </h3>
            <div className="reader-settings__options" role="radiogroup" aria-label="Режим чтения">
              <button
                type="button"
                className={`reader-settings__option${mode === 'vertical' ? ' is-active' : ''}`}
                role="radio"
                aria-checked={mode === 'vertical'}
                onClick={() => changeMode('vertical')}
              >
                <strong>
                  <Icon name="scroll" size={15} /> Непрерывный
                </strong>
                <span>Вебтун и длинные страницы</span>
              </button>
              <button
                type="button"
                className={`reader-settings__option${mode === 'horizontal' ? ' is-active' : ''}`}
                role="radio"
                aria-checked={mode === 'horizontal'}
                onClick={() => changeMode('horizontal')}
              >
                <strong>
                  <Icon name="columns" size={15} /> Постраничный
                </strong>
                <span>Одна страница за раз</span>
              </button>
            </div>
          </section>

          <section className="reader-settings__group">
            <h3 className="reader-settings__title">
              <Icon name="maximize" size={14} /> Вписывание
            </h3>
            <div
              className="reader-settings__options reader-settings__options--three"
              role="radiogroup"
              aria-label="Вписывание страницы"
            >
              {(
                [
                  { value: 'width', label: 'Ширина' },
                  { value: 'height', label: 'Высота' },
                  { value: 'original', label: 'Оригинал' },
                ] as Array<{ value: PageFit; label: string }>
              ).map((fit) => (
                <button
                  key={fit.value}
                  type="button"
                  className={`reader-settings__option${pageFit === fit.value ? ' is-active' : ''}`}
                  role="radio"
                  aria-checked={pageFit === fit.value}
                  onClick={() => updatePrefs({ pageFit: fit.value })}
                >
                  <strong>{fit.label}</strong>
                </button>
              ))}
            </div>
          </section>

          <section className="reader-settings__group">
            <h3 className="reader-settings__title">
              <Icon name="scroll" size={14} /> Отступ между страницами
            </h3>
            <div
              className="reader-settings__options"
              role="radiogroup"
              aria-label="Отступ между страницами"
            >
              {([0, 8, 16, 24, 32] as ReaderGap[]).map((value) => (
                <button
                  key={value}
                  type="button"
                  className={`reader-settings__option${gap === value ? ' is-active' : ''}`}
                  role="radio"
                  aria-checked={gap === value}
                  onClick={() => updatePrefs({ gap: value })}
                >
                  <strong>{value} px</strong>
                  <span>{value === 0 ? 'Без промежутка' : 'Промежуток'}</span>
                </button>
              ))}
            </div>
          </section>

          <section className="reader-settings__group">
            <h3 className="reader-settings__title">
              <Icon name="play" size={14} /> Автопрокрутка
            </h3>
            <div className="setting-row" style={{ paddingTop: 0 }}>
              <div className="setting-row__main">
                <span className="setting-row__label" id="offline-autoscroll-toggle-label">
                  Прокручивать автоматически
                </span>
                <span className="setting-row__desc">
                  {reducedMotion
                    ? 'Недоступно: в системе включено уменьшение движения'
                    : 'Работает в непрерывном режиме. Пауза — при касании или колесе.'}
                </span>
              </div>
              <div className="setting-row__control">
                <label
                  className={`switch${reducedMotion || mode !== 'vertical' ? ' switch--disabled' : ''}`}
                >
                  <input
                    className="switch__input"
                    type="checkbox"
                    checked={autoScroll}
                    disabled={reducedMotion || mode !== 'vertical'}
                    aria-labelledby="offline-autoscroll-toggle-label"
                    onChange={(event) => {
                      updatePrefs({ autoScroll: event.target.checked });
                      setAutoPaused(false);
                    }}
                  />
                  <span className="switch__track">
                    <span className="switch__thumb" />
                  </span>
                </label>
              </div>
            </div>
            {autoScroll && !reducedMotion && mode === 'vertical' ? (
              <div className="reader-settings__slider">
                <div className="reader-settings__slider-head">
                  <span>Скорость</span>
                  <output>{autoScrollSpeed} px/с</output>
                </div>
                <input
                  className="range"
                  type="range"
                  min={5}
                  max={200}
                  step={5}
                  value={autoScrollSpeed}
                  onChange={(event) =>
                    updatePrefs({
                      autoScrollSpeed: Math.min(200, Math.max(5, Math.round(Number(event.target.value)))),
                    })
                  }
                  aria-label="Скорость автопрокрутки"
                />
              </div>
            ) : null}
          </section>

          <section className="reader-settings__group">
            <h3 className="reader-settings__title">
              <Icon name="settings" size={14} /> Отображение
            </h3>
            <div className="setting-row" style={{ paddingTop: 0 }}>
              <div className="setting-row__main">
                <span className="setting-row__label" id="offline-page-numbers-toggle-label">
                  Номера страниц
                </span>
                <span className="setting-row__desc">Подписи поверх страниц</span>
              </div>
              <div className="setting-row__control">
                <label className="switch">
                  <input
                    className="switch__input"
                    type="checkbox"
                    checked={showPageNumbers}
                    aria-labelledby="offline-page-numbers-toggle-label"
                    onChange={(event) => updatePrefs({ showPageNumbers: event.target.checked })}
                  />
                  <span className="switch__track">
                    <span className="switch__thumb" />
                  </span>
                </label>
              </div>
            </div>
          </section>

          {zoom.enabled ? (
            <section className="reader-settings__group">
              <h3 className="reader-settings__title">
                <Icon name="maximize" size={14} /> Масштаб
              </h3>
              <p className="field__hint" style={{ margin: 0 }}>
                Сведите или разведите два пальца на странице. Двойной тап увеличивает и сбрасывает
                масштаб. При смене главы или режима масштаб сбрасывается.
              </p>
            </section>
          ) : null}

          <section className="reader-settings__group">
            <h3 className="reader-settings__title">
              <Icon name="info" size={14} /> Горячие клавиши
            </h3>
            <div className="reader-settings__shortcuts">
              <div className="reader-settings__shortcut">
                <span>
                  {mode === 'horizontal'
                    ? 'Предыдущая / следующая страница'
                    : 'Предыдущая / следующая глава'}
                </span>
                <span>
                  <kbd>←</kbd>
                  <kbd>→</kbd>
                </span>
              </div>
              {mode === 'horizontal' ? (
                <div className="reader-settings__shortcut">
                  <span>Глава (с Shift)</span>
                  <span>
                    <kbd>Shift</kbd> + <kbd>←</kbd>
                    <kbd>→</kbd>
                  </span>
                </div>
              ) : null}
              <div className="reader-settings__shortcut">
                <span>Полный экран</span>
                <kbd>F</kbd>
              </div>
              <div className="reader-settings__shortcut">
                <span>Настройки</span>
                <kbd>S</kbd>
              </div>
              <div className="reader-settings__shortcut">
                <span>Закрыть настройки</span>
                <kbd>Esc</kbd>
              </div>
            </div>
          </section>
        </div>
      </Modal>

      <Modal
        open={chaptersOpen}
        onClose={closeChapters}
        title="Скачанные главы"
        description={title}
        variant="sheet"
        footer={
          <>
            <span className="field__hint" style={{ marginRight: 'auto' }}>
              {formatInt(chaptersForSheet.length)} из {formatInt(chapters.length)}
            </span>
            <button type="button" className="btn btn--primary" onClick={closeChapters}>
              Готово
            </button>
          </>
        }
      >
        <div className="reader-chapters">
          <SearchBox
            value={chapterFilter}
            onChange={setChapterFilter}
            placeholder="Номер или название главы…"
            ariaLabel="Поиск по скачанным главам"
          />
          {chaptersForSheet.length > 0 ? (
            <div className="reader-chapters__list">
              {chaptersForSheet.map((item) => {
                const current = item.id === chapter.id;
                const itemSecondary = chapterSecondaryTitle(item);
                return (
                  <button
                    key={item.id}
                    id={current ? 'offline-reader-chapter-current' : undefined}
                    type="button"
                    className={`reader-chapter-item${current ? ' is-current' : ''}`}
                    aria-current={current ? 'page' : undefined}
                    onClick={() => {
                      closeChapters();
                      if (!current) navigate(`/offline/read/${mangaId}/${item.id}`);
                    }}
                  >
                    <span className="reader-chapter-item__number">{item.number || '•'}</span>
                    <span className="reader-chapter-item__body">
                      <span className="reader-chapter-item__title">
                        {chapterHeading(item)}
                        {itemSecondary ? ` · ${itemSecondary}` : ''}
                      </span>
                      <span className="reader-chapter-item__meta">
                        {pagesLabel(item.pages.length)} · скачано {formatRelative(item.downloadedAt)}
                      </span>
                    </span>
                    <span className="reader-chapter-item__tail">
                      {current ? <Icon name="check" size={16} /> : <Icon name="chevron-right" size={16} />}
                    </span>
                  </button>
                );
              })}
            </div>
          ) : (
            <p className="field__hint">Ничего не найдено. Измените запрос.</p>
          )}
          <div className="reader-chapters__footer">
            <span>Текущая: {chapterHeading(chapter)}</span>
            <span>{formatInt(totalPages)} стр.</span>
          </div>
        </div>
      </Modal>
    </div>
  );
}

function OfflinePageImage({
  page,
  index,
  fit,
  showLabel,
  eager,
  title,
}: {
  page: OfflinePage;
  index: number;
  fit: PageFit;
  showLabel: boolean;
  eager: boolean;
  title: string;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let alive = true;
    setUrl(null);
    setLoaded(false);
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
  }, [page, attempt]);

  return (
    <section
      className="reader-page"
      id={`${OFFLINE_PAGE_PREFIX}${index}`}
      data-offline-page={index}
      aria-label={`Страница ${index}`}
    >
      <div
        className={`reader-page__frame${loaded ? ' is-loaded' : ''}`}
        style={!loaded ? { aspectRatio: pageRatio(page) } : undefined}
      >
        {!loaded && !failed ? <div className="reader-page__skeleton" /> : null}
        {failed ? (
          <div className="reader-page__error">
            <Icon name="alert" size={24} />
            <span>Страница {index} не найдена на устройстве</span>
            <button
              type="button"
              className="btn btn--outline btn--sm"
              onClick={() => {
                setFailed(false);
                setAttempt((value) => value + 1);
              }}
            >
              <Icon name="refresh" size={14} />
              Повторить
            </button>
          </div>
        ) : url ? (
          <img
            key={attempt}
            className={`reader-page__image fit-${fit}${loaded ? ' is-loaded' : ''}`}
            src={url}
            alt={`Страница ${index} манги «${title}»`}
            width={page.width ?? undefined}
            height={page.height ?? undefined}
            loading={eager ? 'eager' : 'lazy'}
            decoding="async"
            draggable={false}
            onLoad={() => setLoaded(true)}
            onError={() => setFailed(true)}
          />
        ) : null}
        {showLabel ? <div className="reader-page__label">Страница {index}</div> : null}
      </div>
    </section>
  );
}

function OfflinePagedImage({
  page,
  index,
  fit,
  tall,
  title,
}: {
  page: OfflinePage;
  index: number;
  fit: PageFit;
  tall: boolean;
  title: string;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let alive = true;
    setUrl(null);
    setLoaded(false);
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
  }, [page, attempt]);

  if (failed) {
    return (
      <div className="reader-paged__error" role="alert">
        <Icon name="alert" size={28} />
        <span>Страница не найдена на устройстве. Попробуйте скачать главу заново.</span>
        <button
          type="button"
          className="btn btn--outline btn--sm"
          onClick={() => {
            setFailed(false);
            setAttempt((value) => value + 1);
          }}
        >
          <Icon name="refresh" size={14} />
          Повторить
        </button>
      </div>
    );
  }

  return (
    <>
      {!loaded ? <div className="reader-paged__skeleton" aria-hidden="true" /> : null}
      {url ? (
        <img
          key={attempt}
          className={`reader-paged__image fit-${fit}${tall ? ' is-tall' : ''}${loaded ? ' is-loaded' : ''}`}
          src={url}
          alt={`Страница ${index} манги «${title}»`}
          width={page.width ?? undefined}
          height={page.height ?? undefined}
          loading="eager"
          decoding="async"
          draggable={false}
          onLoad={() => setLoaded(true)}
          onError={() => setFailed(true)}
        />
      ) : null}
    </>
  );
}
