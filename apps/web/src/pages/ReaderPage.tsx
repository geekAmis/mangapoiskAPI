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
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { api, listItems, resolveApiUrl } from '../api/client';
import type { PageOut } from '../api/types';
import { AdSlot } from '../components/ads/AdSlot';
import { Icon } from '../components/Icon';
import { Modal } from '../components/Modal';
import { QueryCacheBridge } from '../components/QueryCacheBridge';
import { DancingLoader, DancingSpinner } from '../components/DancingLoader';
import { useReaderZoom } from '../components/ReaderZoom';
import { RecommendationShelf } from '../components/RecommendationShelf';
import { SearchBox } from '../components/SearchBox';
import { ThemePicker } from '../components/ThemeSwitcher';
import { trackEvent } from '../lib/analytics';
import { humanizeError } from '../lib/errors';
import {
  chapterHeading,
  chapterSecondaryTitle,
  formatInt,
  formatRelative,
  normalizePage,
  progressPercent,
  sourceLabel,
} from '../lib/format';
import { useDebouncedCallback, useReducedMotion } from '../lib/hooks';
import { mangaPath, mangaPathFromId } from '../lib/mangaRoute';
import { absoluteUrl, useSeo } from '../lib/seo';
import { recordLocalReadingDay, saveLocalProgress } from '../lib/progress';
import { queryKeys } from '../lib/queryClient';
import { useReadingResume } from '../lib/useReading';
import { useAuthStore } from '../stores/auth';
import {
  clampSpeed,
  useReaderStore,
  type PageFit,
  type ReaderGap,
  type ReaderMode,
} from '../stores/reader';
import { toast } from '../stores/toast';

const READER_PAGE_PREFIX = 'reader-page-';
const TAP_AFTER_CLOSE_GUARD_MS = 420;
const FOCUSABLE_SKIP = new Set(['INPUT', 'TEXTAREA', 'SELECT']);

const TALL_PAGE_RATIO = 2.2;

function pageRatio(page: PageOut): string {
  if (page.width && page.height) return `${page.width} / ${page.height}`;
  return '2 / 3';
}

/**
 * Tall webtoon strips must not be contain-fitted in the paged reader: a
 * 690×10000 page would becomes a few dozen pixels wide. They get their own
 * full-width, vertically scrollable presentation instead.
 */
function isTallPage(page: PageOut | null | undefined): boolean {
  if (!page?.width || !page?.height) return false;
  return page.height / page.width > TALL_PAGE_RATIO;
}

export default function ReaderPage() {
  const { chapterId = '' } = useParams();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const user = useAuthStore((state) => state.user);
  const reducedMotion = useReducedMotion();

  const mode = useReaderStore((state) => state.mode);
  const pageFit = useReaderStore((state) => state.pageFit);
  const gap = useReaderStore((state) => state.gap);
  const autoScroll = useReaderStore((state) => state.autoScroll);
  const autoScrollSpeed = useReaderStore((state) => state.autoScrollSpeed);
  const showPageNumbers = useReaderStore((state) => state.showPageNumbers);
  const blurAdultPosters = useReaderStore((state) => state.blurAdultPosters);
  const updatePrefs = useReaderStore((state) => state.update);
  const resetPrefs = useReaderStore((state) => state.reset);

  const [currentPage, setCurrentPage] = useState(1);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [chaptersOpen, setChaptersOpen] = useState(false);
  const [chapterFilter, setChapterFilter] = useState('');
  const [resumeDismissed, setResumeDismissed] = useState(false);
  const [progressEnabled, setProgressEnabled] = useState(false);
  const [chromeHidden, setChromeHidden] = useState(false);
  const [chromeVisible, setChromeVisible] = useState(true);
  const [autoPaused, setAutoPaused] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);

  const initialPageHandledRef = useRef<string | null>(null);
  const progressErrorShownRef = useRef(false);
  const lastReadingDayRef = useRef('');
  const readStartedRef = useRef('');
  const readCompletedRef = useRef('');
  const finishedRef = useRef('');
  const lastSwipeAtRef = useRef(0);
  const touchStartRef = useRef<{ x: number; y: number } | null>(null);
  const pagedMultiTouchRef = useRef(false);
  const tapTimerRef = useRef<number | null>(null);
  const closedSettingsAtRef = useRef(0);

  const cancelPendingTap = useCallback(() => {
    if (tapTimerRef.current !== null) {
      window.clearTimeout(tapTimerRef.current);
      tapTimerRef.current = null;
    }
  }, []);

  const autoPausedBeforeSettingsRef = useRef(false);
  const closeSettings = useCallback(() => {
    closedSettingsAtRef.current = Date.now();
    setSettingsOpen(false);
    if (!autoPausedBeforeSettingsRef.current) setAutoPaused(false);
  }, []);
  const closeChapters = useCallback(() => setChaptersOpen(false), []);

  const chapterQuery = useQuery({
    queryKey: queryKeys.chapter(chapterId),
    queryFn: ({ signal }) => api.getChapter(chapterId, signal),
    enabled: Boolean(chapterId),
  });
  const chapter = chapterQuery.data;

  const zoom = useReaderZoom({
    mode,
    resetKey: chapterId,
    rootKey: chapter?.id ?? '',
    onDoubleTap: cancelPendingTap,
    onGestureStart: cancelPendingTap,
  });

  const mangaQuery = useQuery({
    queryKey: queryKeys.manga(chapter?.manga_id ?? 'none'),
    queryFn: ({ signal }) => api.getManga(chapter?.manga_id ?? '', signal),
    enabled: Boolean(chapter?.manga_id),
  });
  const manga = mangaQuery.data;

  const resume = useReadingResume();

  const bookmarksQuery = useQuery({
    queryKey: queryKeys.bookmarks,
    queryFn: ({ signal }) => api.getBookmarks(signal),
    enabled: Boolean(user) && Boolean(chapter),
  });

  const isBookmarked = Boolean(
    chapter && listItems(bookmarksQuery.data).some((bookmark) => bookmark.manga_id === chapter.manga_id),
  );

  const bookmarkMutation = useMutation({
    mutationFn: async () => {
      if (!chapter) return;
      if (isBookmarked) await api.removeBookmark(chapter.manga_id);
      else await api.addBookmark(chapter.manga_id);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['library', 'bookmarks'] });
      toast.success(isBookmarked ? 'Убрано из закладок' : 'Добавлено в библиотеку');
    },
    onError: (error: unknown) => toast.error(humanizeError(error, 'Не удалось обновить закладку')),
  });

  useLayoutEffect(() => {
    const root = document.documentElement;
    root.dataset.reader = 'true';
    return () => {
      delete root.dataset.reader;
    };
  }, []);

  useSeo({
    title: chapter
      ? `${chapterHeading(chapter)} — ${manga?.title ?? 'чтение'} | MangaPoisk`
      : 'Читалка — MangaPoisk Reborn',
    description:
      chapter && manga
        ? `${manga.title}: ${chapterHeading(chapter)} — читать онлайн на русском в MangaPoisk Reborn.`
        : 'Читалка MangaPoisk Reborn: главы манги и манхвы с удобными режимами чтения.',
    // Chapter pages are not useful landing pages; the title page is canonical.
    canonical: manga ? absoluteUrl(mangaPath(manga)) : null,
    robots: 'noindex,follow',
  });

  const pages = useMemo(() => {
    if (!chapter) return [];
    return [...chapter.pages].sort((a, b) => a.number - b.number);
  }, [chapter]);

  const totalPages = pages.length;
  const requestedPage = searchParams.get('page');

  const saveProgress = useDebouncedCallback((page: number) => {
    if (!chapter) return;
    const total = Math.max(totalPages, chapter.page_count || 0);
    const today = new Date().toDateString();
    if (lastReadingDayRef.current !== today) {
      lastReadingDayRef.current = today;
      if (!user) recordLocalReadingDay();
      void queryClient.invalidateQueries({ queryKey: ['streak'] });
    }
    // Anonymous users get a complete localStorage copy; signed-in users get
    // the same copy plus the account position.  The merge endpoint resolves
    // which one is newer when they next sign in.
    saveLocalProgress({
      manga_id: chapter.manga_id,
      chapter_id: chapter.id,
      page,
      total_pages: total,
      owner_id: user?.id ?? null,
      finished: Boolean(!chapter.next_chapter_id && total > 0 && page >= total),
      manga: {
        id: chapter.manga_id,
        title: manga?.title ?? `Глава ${chapter.number}`,
        poster_url: manga?.poster_url ?? null,
        source: manga?.source ?? chapter.source,
        adult: Boolean(manga?.adult),
        genres: manga?.genres ?? [],
        rating: manga?.rating ?? null,
        chapters_count: manga?.chapters_count ?? 0,
        status: manga?.status ?? null,
      },
      chapter: {
        id: chapter.id,
        volume: chapter.volume,
        number: chapter.number,
        title: chapter.title,
        page_count: chapter.page_count || totalPages,
      },
    });
    if (!user) return;
    api
      .upsertProgress({
        manga_id: chapter.manga_id,
        chapter_id: chapter.id,
        page,
        total_pages: total,
      })
      .catch((error: unknown) => {
        if (!progressErrorShownRef.current) {
          progressErrorShownRef.current = true;
          toast.error(humanizeError(error, 'Не удалось сохранить прогресс чтения'));
        }
      });
  }, 850);

  const savedProgress = chapter
    ? resume.items.find((item) => item.chapter_id === chapter.id)
    : undefined;
  const resumePage =
    savedProgress && savedProgress.page > 1 && savedProgress.page <= totalPages
      ? savedProgress.page
      : null;

  useEffect(() => {
    if (!chapter || totalPages === 0) return;
    if (readStartedRef.current === chapter.id) return;
    readStartedRef.current = chapter.id;
    trackEvent('read_start', {
      surface: 'reader',
      mangaId: chapter.manga_id,
      chapterId: chapter.id,
    });
  }, [chapter, totalPages]);

  useEffect(() => {
    if (!chapter || totalPages === 0 || currentPage < totalPages) return;
    if (readCompletedRef.current !== chapter.id) {
      readCompletedRef.current = chapter.id;
      trackEvent('read_complete', {
        surface: 'reader',
        mangaId: chapter.manga_id,
        chapterId: chapter.id,
      });
    }
    if (!chapter.next_chapter_id && finishedRef.current !== chapter.id) {
      finishedRef.current = chapter.id;
      trackEvent('finish', {
        surface: 'reader',
        mangaId: chapter.manga_id,
        chapterId: chapter.id,
      });
    }
  }, [chapter, currentPage, totalPages]);

  useEffect(() => {
    saveProgress.cancel();
    setCurrentPage(1);
    setSettingsOpen(false);
    setChaptersOpen(false);
    setChapterFilter('');
    setResumeDismissed(false);
    setProgressEnabled(false);
    setChromeHidden(false);
    setChromeVisible(true);
    setAutoPaused(true);
    progressErrorShownRef.current = false;
    initialPageHandledRef.current = null;
    cancelPendingTap();
    window.scrollTo({ top: 0, left: 0, behavior: 'auto' });
  }, [chapterId, saveProgress, cancelPendingTap]);

  useEffect(() => () => cancelPendingTap(), [cancelPendingTap]);

  // В постраничном режиме новая страница всегда открывается без масштаба.
  useEffect(() => {
    if (mode === 'horizontal') zoom.reset();
  }, [currentPage, mode, zoom.reset]);

  useEffect(() => {
    if (!chapter || totalPages === 0) return;
    if (initialPageHandledRef.current === chapter.id) return;
    initialPageHandledRef.current = chapter.id;
    if (!requestedPage) return;
    const target = normalizePage(requestedPage, totalPages);
    setCurrentPage(target);
    setProgressEnabled(true);
    if (mode === 'vertical') {
      window.requestAnimationFrame(() => {
        document.getElementById(`${READER_PAGE_PREFIX}${target}`)?.scrollIntoView({ block: 'start' });
      });
    }
    // requestedPage намеренно читается один раз на главу.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chapter, totalPages, mode]);

  useEffect(() => {
    if (!chapter) return;
    if (initialPageHandledRef.current !== chapter.id) return;
    if (requestedPage) {
      setProgressEnabled(true);
      return;
    }
    if (!resume.isReady) return;
    if (savedProgress && savedProgress.page > 1 && savedProgress.page <= totalPages && !resumeDismissed) {
      setProgressEnabled(false);
      return;
    }
    setProgressEnabled(true);
  }, [
    chapter,
    requestedPage,
    resume.isReady,
    savedProgress,
    totalPages,
    resumeDismissed,
  ]);

  useEffect(() => {
    if (!chapter || !progressEnabled || totalPages === 0) return;
    saveProgress.debounced(currentPage);
  }, [chapter, progressEnabled, currentPage, totalPages, saveProgress]);

  useEffect(() => {
    const onVisibility = () => {
      if (document.visibilityState === 'hidden') saveProgress.flush();
    };
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      document.removeEventListener('visibilitychange', onVisibility);
      saveProgress.flush();
    };
  }, [saveProgress]);

  useEffect(() => {
    if (mode !== 'vertical' || totalPages === 0) return;
    if (!('IntersectionObserver' in window)) return;
    const elements = Array.from(document.querySelectorAll<HTMLElement>('[data-reader-page]'));
    if (elements.length === 0) return;
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio);
        const target = visible[0]?.target as HTMLElement | undefined;
        const page = Number(target?.dataset.readerPage);
        if (page > 0) setCurrentPage((previous) => (previous === page ? previous : page));
      },
      { rootMargin: '-44% 0px -44% 0px', threshold: [0, 0.01, 0.5] },
    );
    elements.forEach((element) => observer.observe(element));
    return () => observer.disconnect();
  }, [mode, chapter?.id, totalPages]);

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
    if (pages.length === 0) return;
    for (const page of pages.slice(currentPage, currentPage + 2)) {
      const image = new Image();
      image.src = resolveApiUrl(page.url);
    }
  }, [currentPage, pages]);

  useEffect(() => {
    const nextId = chapter?.next_chapter_id;
    if (!nextId || totalPages === 0) return;
    if (currentPage < totalPages - 1) return;
    void queryClient.prefetchQuery({
      queryKey: queryKeys.chapter(nextId),
      queryFn: ({ signal }) => api.getChapter(nextId, signal),
      staleTime: 60_000,
    });
  }, [chapter?.next_chapter_id, currentPage, totalPages, queryClient]);

  useEffect(() => {
    const onChange = () => setIsFullscreen(Boolean(document.fullscreenElement));
    document.addEventListener('fullscreenchange', onChange);
    return () => document.removeEventListener('fullscreenchange', onChange);
  }, []);

  const scrollToPage = (page: number, smooth = true) => {
    const target = Math.min(Math.max(1, page), totalPages || 1);
    setCurrentPage(target);
    if (mode === 'vertical') {
      document.getElementById(`${READER_PAGE_PREFIX}${target}`)?.scrollIntoView({
        block: 'start',
        behavior: smooth && !reducedMotion ? 'smooth' : 'auto',
      });
    }
  };

  const goToPage = (page: number) => {
    if (totalPages === 0) return;
    scrollToPage(page, true);
    dismissResumeOnInteraction();
  };

  const goPrevPage = () => {
    if (currentPage > 1) {
      if (mode === 'vertical') scrollToPage(currentPage - 1, false);
      else setCurrentPage(currentPage - 1);
    }
    dismissResumeOnInteraction();
  };

  const goNextPage = () => {
    if (currentPage < totalPages) {
      if (mode === 'vertical') scrollToPage(currentPage + 1, false);
      else setCurrentPage(currentPage + 1);
    }
    dismissResumeOnInteraction();
  };

  const goChapter = (direction: 'prev' | 'next') => {
    const targetId = direction === 'prev' ? chapter?.prev_chapter_id : chapter?.next_chapter_id;
    if (!targetId) {
      toast.info(direction === 'prev' ? 'Это первая глава' : 'Это последняя глава');
      return;
    }
    navigate(`/reader/${targetId}`);
  };

  const changeMode = (nextMode: ReaderMode) => {
    updatePrefs({ mode: nextMode });
    if (nextMode === 'vertical') {
      window.setTimeout(() => {
        document.getElementById(`${READER_PAGE_PREFIX}${currentPage}`)?.scrollIntoView({ block: 'start' });
      }, 80);
    }
  };

  const toggleAutoScroll = () => {
    if (reducedMotion) {
      toast.info('Автопрокрутка отключена: в системе включено уменьшение движения');
      return;
    }
    if (mode !== 'vertical') {
      toast.info('Автопрокрутка работает в непрерывном режиме');
      return;
    }
    if (!autoScroll) {
      updatePrefs({ autoScroll: true });
      setAutoPaused(false);
      return;
    }
    setAutoPaused((paused) => !paused);
  };

  const openSettings = () => {
    autoPausedBeforeSettingsRef.current = autoPaused;
    setAutoPaused(true);
    setChromeHidden(false);
    setChromeVisible(true);
    setSettingsOpen(true);
  };

  const openChapters = () => {
    setAutoPaused(true);
    setChaptersOpen(true);
  };

  const toggleFullscreen = async () => {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await document.documentElement.requestFullscreen();
    } catch {
      toast.info('Полноэкранный режим недоступен в этом браузере');
    }
  };

  const toggleBookmark = () => {
    if (!chapter) return;
    if (!user) {
      navigate(`/login?next=${encodeURIComponent(`${window.location.pathname}${window.location.search}`)}`);
      return;
    }
    bookmarkMutation.mutate();
  };

  function dismissResumeOnInteraction() {
    if (!progressEnabled && user && resumePage && !resumeDismissed) {
      setResumeDismissed(true);
      setProgressEnabled(true);
    }
    if (autoScrollActive && !autoPaused) setAutoPaused(true);
  }

  const onWheel = () => {
    if (autoScrollActive && !autoPaused) setAutoPaused(true);
  };

  const onTouchStart = () => {
    if (autoScrollActive && !autoPaused) setAutoPaused(true);
  };

  const handleTap = (action: () => void) => {
    if (Date.now() - closedSettingsAtRef.current < TAP_AFTER_CLOSE_GUARD_MS) return;
    if (Date.now() - lastSwipeAtRef.current < 450) return;
    dismissResumeOnInteraction();
    action();
  };

  /**
   * На touch-устройствах одиночный тап откладывается на 230 мс: если следом
   * пришёл второй, ReaderZoom превращает жест в двойной тап (зум), а действие
   * одиночного тапа отменяется. Мышиный клик на десктопе срабатывает сразу.
   */
  const runTap = (action: () => void, event: ReactMouseEvent<HTMLElement>) => {
    if (zoom.shouldSuppressClick()) return;
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
      dismissResumeOnInteraction();
      if (deltaX < 0) {
        if (currentPage < totalPages) setCurrentPage((page) => Math.min(totalPages, page + 1));
      } else if (currentPage > 1) {
        setCurrentPage((page) => Math.max(1, page - 1));
      }
    }
  };

  useEffect(() => {
    if (!chaptersOpen) return;
    const timer = window.setTimeout(() => {
      document.getElementById('reader-chapter-current')?.scrollIntoView({ block: 'center' });
    }, 90);
    return () => window.clearTimeout(timer);
  }, [chaptersOpen, manga?.chapters]);

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
  }, [currentPage, mode, chapter?.id, zoom.rootRef]);

  const currentPageData = pages[currentPage - 1];
  const currentPageIsTall = isTallPage(currentPageData);
  const showResume = Boolean(
    resumePage &&
      !resumeDismissed &&
      !requestedPage &&
      resume.isReady &&
      !progressEnabled,
  );

  const chaptersForSheet = useMemo(() => {
    const list = manga?.chapters ?? [];
    const query = chapterFilter.trim().toLowerCase();
    if (!query) return list;
    return list.filter((item) =>
      `${chapterHeading(item)} ${item.title} ${item.number} ${item.volume ?? ''}`
        .toLowerCase()
        .includes(query),
    );
  }, [manga?.chapters, chapterFilter]);

  const headerHidden = !chromeVisible || (mode === 'vertical' && chromeHidden);
  const readerClass = `reader reader--${mode}${!chromeVisible ? ' is-chrome-hidden' : ''}`;

  if (chapterQuery.isLoading) {
    return (
      <>
        <QueryCacheBridge />
        <DancingLoader overlay label="Загружаем страницы главы…" />
      </>
    );
  }

  if (!chapter) {
    return (
      <>
        <QueryCacheBridge />
        <ReaderFatal
          title="Не удалось открыть главу"
          message={humanizeError(chapterQuery.error, 'Глава не найдена или источник временно недоступен.')}
          onRetry={() => void chapterQuery.refetch()}
          backHref="/catalogue"
          backLabel="В каталог"
        />
      </>
    );
  }

  if (pages.length === 0) {
    return (
      <>
        <QueryCacheBridge />
        <div className="reader-empty">
          <div className="reader-empty__card">
            <span className="reader-empty__icon" aria-hidden="true">
              <Icon name="book" size={30} />
            </span>
            <h1>Страницы недоступны</h1>
            <p>
              Источник не отдал изображения для этой главы. Такое бывает у лицензированных или
              ещё не опубликованных страниц. Попробуйте обновить главу или открыть её на сайте
              источника.
            </p>
            <div className="reader-empty__actions">
              <button
                type="button"
                className="btn btn--primary"
                onClick={() => void chapterQuery.refetch()}
                disabled={chapterQuery.isFetching}
              >
                {chapterQuery.isFetching ? (
                  <DancingSpinner size={16} />
                ) : (
                  <Icon name="refresh" size={16} />
                )}
                Обновить главу
              </button>
              <Link
                to={manga ? mangaPath(manga) : mangaPathFromId(chapter.manga_id)}
                className="btn btn--outline"
              >
                <Icon name="arrow-left" size={16} />
                К оглавлению
              </Link>
              {chapter.url ? (
                <a
                  className="btn btn--ghost"
                  href={chapter.url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <Icon name="external" size={16} />
                  На сайте источника
                </a>
              ) : null}
            </div>
          </div>
        </div>
      </>
    );
  }

  return (
    <div className={readerClass} style={{ ['--reader-gap' as string]: `${gap}px` }}>
      <h1 className="sr-only">
        {manga?.title ?? 'Читалка MangaPoisk Reborn'} — {chapterHeading(chapter)}
      </h1>
      <QueryCacheBridge />
      <header className={`reader-header${headerHidden ? ' is-hidden' : ''}`}>
        <div className="reader-header__inner">
          <Link
            to={manga ? mangaPath(manga) : mangaPathFromId(chapter.manga_id)}
            className="reader-header__titles"
            aria-label={`К оглавлению «${manga?.title ?? 'манги'}»`}
            title="К оглавлению"
          >
            <span className="reader-header__manga">{manga?.title ?? 'MangaPoisk Reborn'}</span>
            <span className="reader-header__chapter" title={chapterHeading(chapter)}>
              {chapterHeading(chapter)}
            </span>
            <span
              className="reader-header__meta"
              title={`${sourceLabel(chapter.source)} · ${chapter.translator || 'Без перевода'}`}
            >
              <span className="reader-header__source">{sourceLabel(chapter.source)}</span>
              <span aria-hidden="true">·</span>
              <span className="reader-header__translator">
                {chapter.translator?.trim() || 'Без перевода'}
              </span>
            </span>
          </Link>

          <span className="reader-header__counter" aria-hidden="true">
            <strong>{currentPage}</strong> / {totalPages}
          </span>

          <div className="reader-header__actions">
            <button
              type="button"
              className={`btn btn--ghost btn--icon${isBookmarked ? ' is-active' : ''}`}
              onClick={toggleBookmark}
              aria-label={isBookmarked ? 'Убрать из закладок' : 'Добавить в закладки'}
              aria-pressed={isBookmarked}
              title={isBookmarked ? 'В библиотеке' : 'В библиотеку'}
              disabled={bookmarkMutation.isPending}
            >
              <Icon name="bookmark" size={19} />
            </button>
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
            <button
              type="button"
              className={`btn btn--ghost btn--icon btn--desktop${autoScroll ? ' is-active' : ''}`}
              onClick={toggleAutoScroll}
              aria-label={autoScroll ? 'Остановить автопрокрутку' : 'Включить автопрокрутку'}
              aria-pressed={autoScroll}
              title="Автопрокрутка"
            >
              <Icon name={autoScroll && !autoPaused ? 'pause' : 'play'} size={18} />
            </button>
            <button
              type="button"
              className="btn btn--ghost btn--icon btn--desktop"
              onClick={() => void toggleFullscreen()}
              aria-label={isFullscreen ? 'Выйти из полного экрана' : 'Полный экран'}
              title="Полный экран (F)"
            >
              <Icon name={isFullscreen ? 'minimize' : 'maximize'} size={19} />
            </button>
            <Link
              to={manga ? mangaPath(manga) : mangaPathFromId(chapter.manga_id)}
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
          aria-valuemax={totalPages}
          aria-valuenow={currentPage}
        >
          <div className="reader-progress__bar" style={{ width: `${progressPercent(currentPage, totalPages)}%` }} />
        </div>
      </header>

      <span className="sr-only" aria-live="polite">
        Страница {currentPage} из {totalPages}
      </span>

      {showResume && resumePage ? (
        <div className="reader-resume" role="status">
          <div className="reader-resume__body">
            <div className="reader-resume__title">Продолжить со страницы {resumePage}?</div>
            <div className="reader-resume__text">
              Вы остановились здесь в прошлый раз. Можно начать заново.
            </div>
          </div>
          <div className="reader-resume__actions">
            <button
              type="button"
              className="btn btn--primary"
              onClick={() => {
                setResumeDismissed(true);
                setProgressEnabled(true);
                goToPage(resumePage);
              }}
            >
              Продолжить
            </button>
            <button
              type="button"
              className="btn btn--ghost"
              onClick={() => {
                setResumeDismissed(true);
                setProgressEnabled(true);
                setCurrentPage(1);
                window.scrollTo({ top: 0, behavior: 'auto' });
              }}
            >
              С начала
            </button>
          </div>
        </div>
      ) : null}

      {mode === 'vertical' ? (
        <main
          ref={zoom.rootRef}
          className="reader-main reader-main--vertical"
          onWheel={onWheel}
          onTouchStart={onTouchStart}
          onClick={onVerticalClick}
        >
          <div className="reader-pages">
            {pages.map((page, index) => (
              <ReaderPageImage
                key={`${chapter.id}-${page.number}-${index}`}
                page={page}
                index={index + 1}
                fit={pageFit}
                showLabel={showPageNumbers}
                eager={index < 2}
                alt={`Страница ${index + 1}${manga ? ` манги «${manga.title}»` : ''}`}
              />
            ))}
          </div>
          <AdSlot placement="post-chapter" adult={manga?.adult ?? false} />
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
              <PagedReaderImage
                key={`${chapter.id}-${currentPageData.number}`}
                page={currentPageData}
                fit={pageFit}
                tall={currentPageIsTall}
                alt={`Страница ${currentPage}${manga ? ` манги «${manga.title}»` : ''}`}
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

      {currentPage >= totalPages && !chapter.next_chapter_id ? (
        <div className="reader-completion">
          <RecommendationShelf
            title="Что почитать дальше"
            surface="reader_completion"
            seedMangaId={chapter.manga_id}
            limit={12}
          />
        </div>
      ) : null}

      {zoom.enabled && zoom.isZoomed ? (
        <button type="button" className="reader-zoom-reset" onClick={zoom.reset} aria-label="Сбросить масштаб">
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
              disabled={!chapter.prev_chapter_id}
              title="Предыдущая глава"
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
              aria-label={`Выбрать главу · страница ${currentPage} из ${totalPages}`}
              aria-haspopup="dialog"
              aria-expanded={chaptersOpen}
              title="Выбрать главу"
            >
              <strong>{currentPage}</strong> / {totalPages}
              <Icon name="chevron-down" size={13} />
            </button>
            <input
              className="reader-slider"
              type="range"
              min={1}
              max={totalPages}
              step={1}
              value={currentPage}
              onChange={(event) => goToPage(Number(event.target.value))}
              aria-label="Перейти к странице"
            />
            <div className="reader-footer__mode" role="group" aria-label="Режим чтения">
              <button
                type="button"
                className={mode === 'vertical' ? 'is-active' : ''}
                onClick={() => changeMode('vertical')}
                aria-label="Непрерывный режим"
                aria-pressed={mode === 'vertical'}
                title="Непрерывный режим"
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
              disabled={!chapter.next_chapter_id}
              title="Следующая глава"
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
        description="Изменения применяются сразу и сохраняются в настройках читалки."
        variant="sheet"
        footer={
          <>
            <button
              type="button"
              className="btn btn--ghost"
              onClick={() => {
                const wasHorizontal = mode === 'horizontal';
                resetPrefs();
                setAutoPaused(false);
                if (wasHorizontal) {
                  window.setTimeout(() => {
                    document.getElementById(`${READER_PAGE_PREFIX}${currentPage}`)?.scrollIntoView({ block: 'start' });
                  }, 80);
                }
                toast.info('Настройки читалки сброшены');
              }}
            >
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
            <div className="reader-settings__options" role="radiogroup" aria-label="Отступ между страницами">
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
                <span className="setting-row__label" id="reader-autoscroll-toggle-label">
                  Прокручивать автоматически
                </span>
                <span className="setting-row__desc">
                  {reducedMotion
                    ? 'Недоступно: в системе включено уменьшение движения'
                    : 'Работает в непрерывном режиме. Пауза — при касании или колесе.'}
                </span>
              </div>
              <div className="setting-row__control">
                <label className={`switch${reducedMotion || mode !== 'vertical' ? ' switch--disabled' : ''}`}>
                  <input
                    className="switch__input"
                    type="checkbox"
                    checked={autoScroll}
                    disabled={reducedMotion || mode !== 'vertical'}
                    aria-labelledby="reader-autoscroll-toggle-label"
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
                  max={600}
                  step={5}
                  value={autoScrollSpeed}
                  onChange={(event) => updatePrefs({ autoScrollSpeed: clampSpeed(Number(event.target.value)) })}
                  aria-label="Скорость автопрокрутки"
                />
              </div>
            ) : null}
          </section>

          <section className="reader-settings__group">
            <h3 className="reader-settings__title">
              <Icon name="settings" size={14} /> Отображение
            </h3>            <div className="setting-row" style={{ paddingTop: 0 }}>
              <div className="setting-row__main">
                <span className="setting-row__label" id="reader-page-numbers-toggle-label">
                  Номера страниц
                </span>
                <span className="setting-row__desc">Подписи между страницами</span>
              </div>
              <div className="setting-row__control">
                <label className="switch">
                  <input
                    className="switch__input"
                    type="checkbox"
                    checked={showPageNumbers}
                    aria-labelledby="reader-page-numbers-toggle-label"
                    onChange={(event) => updatePrefs({ showPageNumbers: event.target.checked })}
                  />
                  <span className="switch__track">
                    <span className="switch__thumb" />
                  </span>
                </label>
              </div>
            </div>
            <div className="setting-row">
              <div className="setting-row__main">
                <span className="setting-row__label" id="reader-blur-adult-toggle-label">
                  Размывать обложки 18+
                </span>
                <span className="setting-row__desc">Влияет на каталог и страницы тайтлов</span>
              </div>
              <div className="setting-row__control">
                <label className="switch">
                  <input
                    className="switch__input"
                    type="checkbox"
                    checked={blurAdultPosters}
                    aria-labelledby="reader-blur-adult-toggle-label"
                    onChange={(event) => updatePrefs({ blurAdultPosters: event.target.checked })}
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
                Сведите или разведите два пальца на странице. Двойной тап увеличивает
                и сбрасывает масштаб. При смене главы или режима масштаб сбрасывается.
              </p>
            </section>
          ) : null}

          <section className="reader-settings__group">
            <h3 className="reader-settings__title">
              <Icon name="info" size={14} /> Горячие клавиши
            </h3>
            <div className="reader-settings__shortcuts">
              <div className="reader-settings__shortcut">
                <span>{mode === 'horizontal' ? 'Предыдущая / следующая страница' : 'Предыдущая / следующая глава'}</span>
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
                <span>Прокрутка</span>
                <span>
                  <kbd>↑</kbd>
                  <kbd>↓</kbd>
                </span>
              </div>
              <div className="reader-settings__shortcut">
                <span>Полный экран</span>
                <kbd>F</kbd>
              </div>
              <div className="reader-settings__shortcut">
                <span>Настройки</span>
                <kbd>S</kbd>
              </div>
              {mode === 'horizontal' ? (
                <div className="reader-settings__shortcut">
                  <span>Листать вперёд / назад</span>
                  <span>
                    <kbd>Пробел</kbd> / <kbd>Shift</kbd> + <kbd>Пробел</kbd>
                  </span>
                </div>
              ) : null}
            </div>
          </section>
        </div>
      </Modal>

      <Modal
        open={chaptersOpen}
        onClose={closeChapters}
        title="Главы"
        description={manga?.title ?? 'Список глав текущего тайтла'}
        variant="sheet"
        footer={
          <>
            <span className="field__hint" style={{ marginRight: 'auto' }}>
              {formatInt(chaptersForSheet.length)} из {formatInt(manga?.chapters.length ?? 0)}
            </span>
            <Link
              to={manga ? mangaPath(manga) : mangaPathFromId(chapter.manga_id)}
              className="btn btn--outline btn--sm"
              onClick={() => setChaptersOpen(false)}
            >
              К оглавлению
            </Link>
          </>
        }
      >
        <div className="reader-chapters">
          <SearchBox
            value={chapterFilter}
            onChange={setChapterFilter}
            placeholder="Номер или название главы…"
            ariaLabel="Поиск по главам"
          />
          {mangaQuery.isLoading ? (
            <p className="field__hint">Загружаем список глав…</p>
          ) : chaptersForSheet.length > 0 ? (
            <div className="reader-chapters__list">
              {chaptersForSheet.map((item) => {
                const current = item.id === chapter.id;
                return (
                  <button
                    key={item.id}
                    id={current ? 'reader-chapter-current' : undefined}
                    type="button"
                    className={`reader-chapter-item${current ? ' is-current' : ''}`}
                    aria-current={current ? 'page' : undefined}
                    onClick={() => {
                      setChaptersOpen(false);
                      if (!current) navigate(`/reader/${item.id}`);
                    }}
                  >
                    <span className="reader-chapter-item__number">{item.number || '•'}</span>
                    <span className="reader-chapter-item__body">
                      <span className="reader-chapter-item__title">
                        {chapterHeading(item)}
                        {chapterSecondaryTitle(item) ? ` · ${chapterSecondaryTitle(item)}` : ''}
                      </span>
                      <span className="reader-chapter-item__meta reader-chapter-item__meta--translation">
                        {sourceLabel(item.source)} · {item.translator?.trim() || 'Без перевода'}
                      </span>
                      <span className="reader-chapter-item__meta">
                        {item.page_count ? `${formatInt(item.page_count)} стр.` : 'Страницы уточняются'}
                        {item.published_at ? ` · ${formatRelative(item.published_at)}` : ''}
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
            <p className="field__hint">
              {mangaQuery.isError
                ? 'Не удалось загрузить оглавление. Откройте страницу тайтла.'
                : 'Ничего не найдено. Измените запрос.'}
            </p>
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

function ReaderPageImage({
  page,
  index,
  fit,
  showLabel,
  eager,
  alt,
}: {
  page: PageOut;
  index: number;
  fit: PageFit;
  showLabel: boolean;
  eager: boolean;
  alt: string;
}) {
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);
  const [failures, setFailures] = useState(0);
  const [attempt, setAttempt] = useState(0);
  const retryTimer = useRef<number | null>(null);

  useEffect(
    () => () => {
      if (retryTimer.current !== null) window.clearTimeout(retryTimer.current);
    },
    [],
  );

  const retry = () => {
    setFailed(false);
    setLoaded(false);
    setFailures(0);
    setAttempt((value) => value + 1);
  };

  const handleError = () => {
    setLoaded(false);
    const next = failures + 1;
    setFailures(next);
    if (next >= 3) {
      setFailed(true);
      return;
    }
    if (retryTimer.current !== null) window.clearTimeout(retryTimer.current);
    retryTimer.current = window.setTimeout(() => setAttempt((value) => value + 1), 450);
  };

  return (
    <section
      className="reader-page"
      id={`${READER_PAGE_PREFIX}${index}`}
      data-reader-page={index}
      aria-label={`Страница ${index}`}
    >
      <div
        className={`reader-page__frame${loaded ? ' is-loaded' : ''}`}
        style={!loaded ? { aspectRatio: pageRatio(page) } : undefined}
      >
        {!loaded && !failed ? (
          <div className="reader-page__loading" aria-hidden="true">
            <DancingLoader compact label={failures > 0 ? 'Повторяем загрузку…' : undefined} />
          </div>
        ) : null}
        {failed ? (
          <div className="reader-page__error">
            <Icon name="alert" size={24} />
            <span>Изображение не загрузилось</span>
            <button type="button" className="btn btn--outline btn--sm" onClick={retry}>
              <Icon name="refresh" size={14} />
              Повторить
            </button>
          </div>
        ) : (
          <img
            key={attempt}
            className={`reader-page__image fit-${fit}${loaded ? ' is-loaded' : ''}`}
            src={resolveApiUrl(page.url)}
            alt={alt}
            width={page.width ?? undefined}
            height={page.height ?? undefined}
            loading={eager ? 'eager' : 'lazy'}
            decoding="async"
            draggable={false}
            onLoad={() => setLoaded(true)}
            onError={handleError}
          />
        )}
        {showLabel ? <div className="reader-page__label">Страница {index}</div> : null}
      </div>
    </section>
  );
}

function PagedReaderImage({
  page,
  fit,
  tall,
  alt,
}: {
  page: PageOut;
  fit: PageFit;
  tall: boolean;
  alt: string;
}) {
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);
  const [failures, setFailures] = useState(0);
  const [attempt, setAttempt] = useState(0);
  const retryTimer = useRef<number | null>(null);

  useEffect(
    () => () => {
      if (retryTimer.current !== null) window.clearTimeout(retryTimer.current);
    },
    [],
  );

  const retry = () => {
    setFailed(false);
    setLoaded(false);
    setFailures(0);
    setAttempt((value) => value + 1);
  };

  const handleError = () => {
    setLoaded(false);
    const next = failures + 1;
    setFailures(next);
    if (next >= 3) {
      setFailed(true);
      return;
    }
    if (retryTimer.current !== null) window.clearTimeout(retryTimer.current);
    retryTimer.current = window.setTimeout(() => setAttempt((value) => value + 1), 450);
  };

  if (failed) {
    return (
      <div className="reader-paged__error" role="alert">
        <Icon name="alert" size={28} />
        <span>Не удалось загрузить страницу. Проверьте соединение и попробуйте снова.</span>
        <button type="button" className="btn btn--outline btn--sm" onClick={retry}>
          <Icon name="refresh" size={14} />
          Повторить
        </button>
      </div>
    );
  }

  return (
    <>
      {!loaded ? (
        <div className="reader-paged__loading" aria-hidden="true">
          <DancingLoader compact label={failures > 0 ? 'Повторяем загрузку…' : undefined} />
        </div>
      ) : null}
      <img
        key={attempt}
        className={`reader-paged__image fit-${fit}${tall ? ' is-tall' : ''}${loaded ? ' is-loaded' : ''}`}
        src={resolveApiUrl(page.url)}
        alt={alt}
        width={page.width ?? undefined}
        height={page.height ?? undefined}
        loading="eager"
        decoding="async"
        draggable={false}
        onLoad={() => setLoaded(true)}
        onError={handleError}
      />
    </>
  );
}

function ReaderFatal({
  title,
  message,
  onRetry,
  backHref,
  backLabel,
}: {
  title: string;
  message: string;
  onRetry: () => void;
  backHref: string;
  backLabel: string;
}) {
  return (
    <div className="reader-fatal">
      <div className="reader-fatal__card">
        <span className="reader-fatal__icon" aria-hidden="true">
          <Icon name="alert" size={28} />
        </span>
        <h1>{title}</h1>
        <p>{message}</p>
        <div className="reader-fatal__actions">
          <button type="button" className="btn btn--primary" onClick={onRetry}>
            <Icon name="refresh" size={16} />
            Повторить
          </button>
          <Link to={backHref} className="btn btn--outline">
            <Icon name="arrow-left" size={16} />
            {backLabel}
          </Link>
        </div>
      </div>
    </div>
  );
}
