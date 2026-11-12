import { useDeferredValue, useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import { ApiError, api, listItems, resolveApiUrl } from '../api/client';
import { notificationsApi } from '../api/notifications';
import type { ChapterOut, MangaDetailOut, MangaVariantOut } from '../api/types';
import { AdSlot } from '../components/ads/AdSlot';
import { AdultNotice } from '../components/AdultNotice';
import { AgeGate } from '../components/AgeGate';
import { ChapterRow } from '../components/ChapterRow';
import { CommentsSection } from '../components/CommentsSection';
import { EmptyState } from '../components/EmptyState';
import { ErrorState, InlineError } from '../components/ErrorState';
import { Icon } from '../components/Icon';
import { DancingSpinner } from '../components/DancingLoader';
import { Modal } from '../components/Modal';
import { Poster } from '../components/Poster';
import { Rating } from '../components/Rating';
import { RecommendationShelf } from '../components/RecommendationShelf';
import { RelatedShelf } from '../components/RelatedShelf';
import { SearchBox } from '../components/SearchBox';
import { Skeleton } from '../components/Skeleton';
import {
  cancelDownload,
  preparePercent,
  retryDownload,
  startChapterDownload,
  startTitleDownload,
  useDownloadJobs,
} from '../lib/downloadManager';
import { humanizeError } from '../lib/errors';
import {
  chapterHeading,
  chaptersLabel,
  contentTypeLabel,
  formatDate,
  formatInt,
  formatRelative,
  sourceLabel,
  statusLabel,
} from '../lib/format';
import {
  absoluteUrl,
  buildBreadcrumbJsonLd,
  buildComicStoryJsonLd,
  jsonLdGraph,
  metaDescription,
  useSeo,
} from '../lib/seo';
import { useOfflineTitle } from '../lib/offlineHooks';
import { formatBytes, jobPercent, offlineTitleStats, type DownloadJobStatus } from '../lib/offlineTypes';
import { queryKeys } from '../lib/queryClient';
import { useReadingResume } from '../lib/useReading';
import { useAuthStore } from '../stores/auth';
import { useReaderStore } from '../stores/reader';
import { toast } from '../stores/toast';

type ChapterSort = 'desc' | 'asc';

const ALL_TRANSLATIONS = 'all';
const NO_TRANSLATOR = 'none';

/**
 * Стабильный на сессию tie-break: если у вариантов одинаковое число глав,
 * «Читать» выбирает один и тот же источник при каждом рендере.
 */
const variantTieBreak = new Map<string, number>();

function tieBreakValue(id: string): number {
  const cached = variantTieBreak.get(id);
  if (cached !== undefined) return cached;
  const value = Math.random();
  variantTieBreak.set(id, value);
  return value;
}

function pickBestVariant(variants: MangaVariantOut[]): MangaVariantOut | null {
  let best: MangaVariantOut | null = null;
  for (const variant of variants) {
    if (!best) {
      best = variant;
      continue;
    }
    if (variant.chapters_count > best.chapters_count) {
      best = variant;
      continue;
    }
    if (
      variant.chapters_count === best.chapters_count &&
      tieBreakValue(variant.id) > tieBreakValue(best.id)
    ) {
      best = variant;
    }
  }
  return best;
}

function translationKey(translator: string | null | undefined): string {
  return translator?.trim() ? `t:${translator.trim()}` : NO_TRANSLATOR;
}

function compareChapters(a: ChapterOut, b: ChapterOut): number {
  const byVolume = (a.volume ?? '').localeCompare(b.volume ?? '', 'ru', { numeric: true });
  if (byVolume !== 0) return byVolume;
  return a.number.localeCompare(b.number, 'ru', { numeric: true });
}

function mangaMetaDescription(
  manga: MangaDetailOut | undefined,
  title: string | undefined,
): string {
  const name = title?.trim() || 'Тайтл';
  const raw = manga?.description?.trim() || manga?.description_fallback?.trim();
  if (raw) return metaDescription(raw);

  const facts = [
    manga?.year ? String(manga.year) : null,
    manga?.genres?.slice(0, 3).join(', ') || null,
  ].filter(Boolean);
  return metaDescription(
    `${name} — читать онлайн на русском.${facts.length > 0 ? ` ${facts.join(' · ')}.` : ''} Описание, список глав и читалка MangaPoisk Reborn.`,
  );
}

export default function MangaPage() {
  const { id = '' } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const user = useAuthStore((state) => state.user);
  const blurAdultPosters = useReaderStore((state) => state.blurAdultPosters);
  const updateReaderPrefs = useReaderStore((state) => state.update);

  const [descriptionExpanded, setDescriptionExpanded] = useState(false);
  const [coverIndex, setCoverIndex] = useState(0);
  const [chapterSearch, setChapterSearch] = useState('');
  const deferredChapterSearch = useDeferredValue(chapterSearch);
  const [chapterSort, setChapterSort] = useState<ChapterSort>('desc');
  const [visibleChapters, setVisibleChapters] = useState(60);
  const [chaptersOpen, setChaptersOpen] = useState(false);
  const [selectedVariantId, setSelectedVariantId] = useState<string | null>(null);
  const [translationFilter, setTranslationFilter] = useState<string>(ALL_TRANSLATIONS);

  const mangaQuery = useQuery({
    queryKey: queryKeys.manga(id),
    queryFn: ({ signal }) => api.getManga(id, signal),
    enabled: Boolean(id),
  });
  const manga = mangaQuery.data;
  const ageBlocked =
    mangaQuery.error instanceof ApiError &&
    mangaQuery.error.status === 403 &&
    mangaQuery.error.code === 'age_confirmation_required';

  const variantsQuery = useQuery({
    queryKey: ['manga', id, 'variants'],
    queryFn: ({ signal }) => api.getMangaVariants(id, signal),
    enabled: Boolean(id),
    retry: false,
    staleTime: 10 * 60_000,
  });

  const variants = useMemo(() => {
    const items = variantsQuery.data?.items;
    if (!Array.isArray(items)) return [];
    const seen = new Set<string>();
    return items.filter((variant) => {
      if (!variant?.id || seen.has(variant.id)) return false;
      seen.add(variant.id);
      return true;
    });
  }, [variantsQuery.data]);

  const bestVariant = useMemo(() => pickBestVariant(variants), [variants]);
  const activeVariant = useMemo(() => {
    if (variants.length === 0) return null;
    if (selectedVariantId) {
      return variants.find((variant) => variant.id === selectedVariantId) ?? bestVariant;
    }
    return bestVariant;
  }, [variants, selectedVariantId, bestVariant]);

  const activeVariantId = activeVariant?.id ?? id;
  const bestVariantId = bestVariant?.id ?? id;

  const { title: offlineTitle } = useOfflineTitle(activeVariantId);
  const downloadJobs = useDownloadJobs();
  const deviceJob = downloadJobs.find(
    (job) =>
      job.mangaId === activeVariantId &&
      job.mode === 'title' &&
      (job.status === 'queued' ||
        job.status === 'running' ||
        job.status === 'error' ||
        job.status === 'cancelled'),
  );
  const activeDeviceJob =
    deviceJob && (deviceJob.status === 'queued' || deviceJob.status === 'running')
      ? deviceJob
      : null;
  const offlineStats = offlineTitle ? offlineTitleStats(offlineTitle) : null;
  const offlineChapterIds = useMemo(
    () => new Set((offlineTitle?.chapters ?? []).map((chapter) => chapter.id)),
    [offlineTitle],
  );
  const chapterJobStatuses = useMemo(() => {
    const statuses = new Map<string, DownloadJobStatus>();
    for (const job of downloadJobs) {
      if (job.mangaId !== activeVariantId || job.mode !== 'chapter') continue;
      const chapterId = job.chapters[0]?.id;
      if (chapterId) statuses.set(chapterId, job.status);
    }
    return statuses;
  }, [downloadJobs, activeVariantId]);
  const chapterJobNotices = useRef(new Map<string, DownloadJobStatus>());

  const isChapterDownloading = (chapterId: string): boolean => {
    const status = chapterJobStatuses.get(chapterId);
    return status === 'queued' || status === 'running';
  };

  // Полные данные выбранного источника (описание, жанры, главы).
  const activeMangaQuery = useQuery({
    queryKey: queryKeys.manga(activeVariantId),
    queryFn: ({ signal }) => api.getManga(activeVariantId, signal),
    enabled: Boolean(activeVariant) && activeVariantId !== id,
    staleTime: 5 * 60_000,
  });
  const activeManga = activeVariantId === id ? manga : activeMangaQuery.data;

  // «Читать» всегда ведёт в источник с максимальным числом глав.
  const bestMangaQuery = useQuery({
    queryKey: queryKeys.manga(bestVariantId),
    queryFn: ({ signal }) => api.getManga(bestVariantId, signal),
    enabled: Boolean(bestVariant) && bestVariantId !== id,
    staleTime: 5 * 60_000,
  });
  const bestManga = bestVariantId === id ? manga : bestMangaQuery.data;

  const bookmarksQuery = useQuery({
    queryKey: queryKeys.bookmarks,
    queryFn: ({ signal }) => api.getBookmarks(signal),
    enabled: Boolean(user),
  });

  const resume = useReadingResume();

  const followQuery = useQuery({
    queryKey: ['follow', id],
    queryFn: () => notificationsApi.followStatus(id),
    enabled: Boolean(user) && Boolean(id),
    staleTime: 60_000,
  });
  const isFollowing = followQuery.data?.following ?? false;

  const viewTitle = activeVariant?.title ?? manga?.title;
  const seoTitle = viewTitle
    ? `${viewTitle} — читать онлайн на русском`
    : 'Тайтл — MangaPoisk Reborn';
  const seoCover =
    manga?.covers?.find((cover) => cover.is_primary)?.url ??
    manga?.poster_url ??
    activeVariant?.poster_url ??
    null;
  const seoCanonical = manga
    ? absoluteUrl(`/manga/${manga.id}`)
    : mangaQuery.isError
      ? null
      : undefined;
  const seoJsonLd = manga
    ? jsonLdGraph(
        buildComicStoryJsonLd({
          name: manga.title,
          url: absoluteUrl(`/manga/${manga.id}`) ?? '',
          description: manga.description || manga.description_fallback,
          image: seoCover,
          alternateNames: [manga.title_en, manga.title_alt],
          genres: manga.genres,
          year: manga.year,
          adult: manga.adult,
          rating: manga.rating,
          ratingCount: manga.rating_count,
          sameAs: manga.url,
          dateModified: manga.updated_at,
        }),
        buildBreadcrumbJsonLd([
          { name: 'Главная', url: '/' },
          { name: 'Каталог', url: '/catalogue' },
          { name: viewTitle ?? manga.title, url: `/manga/${manga.id}` },
        ]),
      )
    : null;

  useSeo({
    title: seoTitle,
    description: mangaMetaDescription(manga, viewTitle),
    canonical: seoCanonical,
    robots:
      ageBlocked || manga?.adult_only || manga?.requires_age_confirmation
        ? 'noindex,nofollow'
        : mangaQuery.isError
          ? 'noindex,follow'
          : 'index,follow,max-image-preview:large',
    image: seoCover,
    imageAlt: viewTitle ? `Обложка «${viewTitle}»` : undefined,
    type: 'book',
    jsonLd: seoJsonLd,
  });

  const bookmarks = listItems(bookmarksQuery.data);
  const isBookmarked = bookmarks.some((bookmark) => bookmark.manga_id === id);

  const progressItems = resume.items;
  const variantIds = useMemo(() => new Set([id, ...variants.map((variant) => variant.id)]), [id, variants]);
  const progress = progressItems.find((item) => variantIds.has(item.manga_id));

  const bookmarkMutation = useMutation({
    mutationFn: async () => {
      if (isBookmarked) await api.removeBookmark(id);
      else await api.addBookmark(id);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['library', 'bookmarks'] });
      toast.success(isBookmarked ? 'Убрано из закладок' : 'Добавлено в библиотеку');
    },
    onError: (error: unknown) => {
      toast.error(humanizeError(error, 'Не удалось обновить закладку'));
    },
  });

  const followMutation = useMutation({
    mutationFn: async () => {
      if (isFollowing) {
        await notificationsApi.unfollow(id);
        return false;
      }
      await notificationsApi.follow(
        id,
        manga?.title ?? 'Тайтл',
        manga?.poster_url ?? null,
        manga?.source ?? null,
      );
      return true;
    },
    onSuccess: (nowFollowing) => {
      void queryClient.invalidateQueries({ queryKey: ['follow', id] });
      void queryClient.invalidateQueries({ queryKey: ['notifications'] });
      toast.success(
        nowFollowing
          ? 'Вы следите за новыми главами. Уведомление появится в колокольчике.'
          : 'Вы больше не следите за новыми главами этого тайтла',
      );
    },
    onError: (error: unknown) => {
      toast.error(humanizeError(error, 'Не удалось обновить подписку на главы'));
    },
  });

  const refreshMutation = useMutation({
    mutationFn: () => {
      if (!manga) return Promise.reject(new Error('Нет данных о манге'));
      const target = activeVariant ?? manga;
      return api.importManga({ source: target.source, source_id: target.source_id, refresh: true });
    },
    onSuccess: (result) => {
      queryClient.setQueryData(queryKeys.manga(result.manga.id), result.manga);
      void queryClient.invalidateQueries({ queryKey: ['manga', id, 'variants'] });
      void queryClient.invalidateQueries({ queryKey: ['manga', 'list'] });
      toast.success(
        `Обновлено: глав — ${formatInt(result.imported_chapters)}, страниц — ${formatInt(result.imported_pages)}.`,
      );
    },
    onError: (error: unknown) => {
      toast.error(humanizeError(error, 'Не удалось обновить тайтл из источника'));
    },
  });

  useEffect(() => {
    setDescriptionExpanded(false);
    setCoverIndex(0);
    setChapterSearch('');
    setChapterSort('desc');
    setVisibleChapters(60);
    setChaptersOpen(false);
    setSelectedVariantId(null);
    setTranslationFilter(ALL_TRANSLATIONS);
  }, [id]);

  // Одиночная глава скачивается в фоне: сообщаем о завершении или ошибке,
  // когда задание меняет статус, а не только в момент нажатия кнопки.
  useEffect(() => {
    for (const job of downloadJobs) {
      if (job.mangaId !== activeVariantId || job.mode !== 'chapter') continue;
      const previous = chapterJobNotices.current.get(job.id);
      chapterJobNotices.current.set(job.id, job.status);
      if (previous !== 'queued' && previous !== 'running') continue;
      if (job.status === 'done') {
        const chapter = job.chapters[0];
        toast.success(
          `${chapter ? chapterHeading(chapter) : 'Глава'} сохранена на устройстве`,
        );
      } else if (job.status === 'error') {
        toast.error(job.error ?? 'Не удалось скачать главу на устройстве');
      }
    }
  }, [downloadJobs, activeVariantId]);

  useEffect(() => {
    setTranslationFilter(ALL_TRANSLATIONS);
  }, [activeVariantId]);

  useEffect(() => {
    setVisibleChapters(60);
  }, [deferredChapterSearch, chapterSort, translationFilter, activeVariantId]);

  if (!manga) {
    if (ageBlocked) {
      return (
        <AgeGate
          signedIn={Boolean(user)}
          onConfirmed={() => void mangaQuery.refetch()}
        />
      );
    }
    if (mangaQuery.isLoading) {
      return (
        <div className="page container manga-page">
          <Skeleton width="280px" height="14px" />
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

    return (
      <div className="page container manga-page">
        <ErrorState
          title="Не удалось открыть тайтл"
          message={humanizeError(mangaQuery.error, 'Возможно, тайтл был удалён или ссылка неверна.')}
          onRetry={() => void mangaQuery.refetch()}
          action={
            <Link to="/catalogue" className="btn btn--outline btn--sm">
              Вернуться в каталог
            </Link>
          }
        />
      </div>
    );
  }

  // Defence in depth against a cached adult response after logout/revoke.
  if (
    (manga.adult_only || manga.requires_age_confirmation) &&
    !user?.age_confirmed_at
  ) {
    return (
      <AgeGate
        signedIn={Boolean(user)}
        onConfirmed={() => void mangaQuery.refetch()}
      />
    );
  }

  const chapters = activeManga?.chapters ?? (activeVariantId === id ? manga.chapters : []);
  const chapterCount = chapters.length || activeVariant?.chapters_count || 0;
  const chaptersLoading = activeVariantId !== id && activeMangaQuery.isLoading;
  const chaptersError = activeVariantId !== id && activeMangaQuery.isError;
  const firstChapter = chapters.length > 0 ? chapters[chapters.length - 1] : null;

  const playChapters = bestManga?.chapters ?? (bestVariantId === id ? manga.chapters : []);
  const playFirstChapter = playChapters.length > 0 ? playChapters[playChapters.length - 1] : null;
  const bestProgress = progressItems.find((item) => item.manga_id === bestVariantId);
  const playProgressChapter = bestProgress
    ? (playChapters.find((chapter) => chapter.id === bestProgress.chapter_id) ?? null)
    : null;
  const playChapter = playProgressChapter ?? playFirstChapter;
  const playPage = playProgressChapter && bestProgress && bestProgress.page > 1 ? bestProgress.page : null;
  const isContinuing = Boolean(playProgressChapter);
  const playHref = playChapter
    ? `/reader/${playChapter.id}${playPage ? `?page=${playPage}` : ''}`
    : null;
  const playLoading = Boolean(bestVariant) && bestVariantId !== id && bestMangaQuery.isLoading;

  const progressChapter = progress
    ? (chapters.find((chapter) => chapter.id === progress.chapter_id) ?? null)
    : null;
  const activeProgress =
    progressItems.find((item) => item.manga_id === activeVariantId) ?? progress ?? null;
  const lastChapter = [...chapters].sort(compareChapters).at(-1) ?? null;
  const lastChapterTotal = activeProgress
    ? activeProgress.total_pages || lastChapter?.page_count || 0
    : 0;
  const finishedTitle = Boolean(
    activeProgress &&
      lastChapter &&
      activeProgress.chapter_id === lastChapter.id &&
      lastChapterTotal > 0 &&
      activeProgress.page >= lastChapterTotal,
  );

  // Одиночная загрузка всегда берёт главу выбранного источника, чтобы
  // идентификатор тайтла в офлайн-манифесте совпадал с главой. Приоритет —
  // текущая глава, затем последняя опубликованная.
  const latestChapter = [...chapters].sort(compareChapters).at(-1) ?? null;
  const chapterDownloadTarget = progressChapter ?? latestChapter ?? firstChapter;
  const chapterDownloadDone = chapterDownloadTarget
    ? offlineChapterIds.has(chapterDownloadTarget.id)
    : false;
  const chapterDownloadPending = chapterDownloadTarget
    ? isChapterDownloading(chapterDownloadTarget.id)
    : false;

  const viewManga = activeManga ?? manga;
  const covers = viewManga.covers ?? [];
  const safeCoverIndex = covers.length > 0 ? Math.min(coverIndex, covers.length - 1) : 0;
  const activeCover = covers[safeCoverIndex];
  const posterSrc = activeCover?.url ?? activeVariant?.poster_url ?? viewManga.poster_url;
  const displayTitle = activeVariant?.title ?? viewManga.title;
  const altTitles = [viewManga.title_en, viewManga.title_alt].filter(
    (title): title is string => Boolean(title && title.trim() && title.trim() !== displayTitle),
  );
  const hasLongDescription = Boolean(viewManga.description && viewManga.description.length > 460);

  // Счётчик источника может быть нулевым до импорта глав; уточняем его по
  // уже загруженному оглавлению выбранного варианта.
  const variantChaptersCount = (variant: MangaVariantOut): number => {
    if (variant.id === activeVariantId && chapters.length > 0) return chapters.length;
    if (variant.id === bestVariantId && playChapters.length > 0) return playChapters.length;
    return variant.chapters_count;
  };

  const sourceVariants: MangaVariantOut[] = [];
  const sourceMap = new Map<string, MangaVariantOut>();
  for (const variant of variants) {
    const current = sourceMap.get(variant.source);
    if (!current || variant.chapters_count > current.chapters_count) {
      sourceMap.set(variant.source, variant);
    }
  }
  sourceVariants.push(
    ...Array.from(sourceMap.values()).sort((a, b) => b.chapters_count - a.chapters_count),
  );
  const showVariantPicker = sourceVariants.length >= 2;

  interface TranslationGroup {
    key: string;
    source: string;
    translator: string | null;
    count: number;
  }

  const translationMap = new Map<string, TranslationGroup>();
  for (const chapter of chapters) {
    const key = translationKey(chapter.translator);
    const existing = translationMap.get(key);
    if (existing) {
      existing.count += 1;
    } else {
      translationMap.set(key, {
        key,
        source: chapter.source,
        translator: chapter.translator?.trim() || null,
        count: 1,
      });
    }
  }
  const translationGroups = Array.from(translationMap.values()).sort((a, b) => b.count - a.count);
  const translationScopedChapters =
    translationFilter === ALL_TRANSLATIONS
      ? chapters
      : chapters.filter((chapter) => translationKey(chapter.translator) === translationFilter);

  const normalizedSearch = deferredChapterSearch.trim().toLowerCase();
  const sortedChapters = [...translationScopedChapters]
    .filter((chapter) => {
      if (!normalizedSearch) return true;
      return `${chapterHeading(chapter)} ${chapter.title} ${chapter.number} ${chapter.volume ?? ''} ${chapter.translator ?? ''}`
        .toLowerCase()
        .includes(normalizedSearch);
    })
    .sort((a, b) => (chapterSort === 'asc' ? compareChapters(a, b) : compareChapters(b, a)));

  const shownChapters = sortedChapters.slice(0, visibleChapters);
  const toggleBookmark = () => {
    if (!user) {
      navigate(`/login?next=${encodeURIComponent(`${location.pathname}${location.search}`)}`);
      return;
    }
    bookmarkMutation.mutate();
  };

  const toggleFollow = () => {
    if (!user) {
      navigate(`/login?next=${encodeURIComponent(`${location.pathname}${location.search}`)}`);
      return;
    }
    followMutation.mutate();
  };

  const queueDeviceDownload = async () => {
    if (!user) {
      toast.info('Войдите, чтобы подготовить главы на сервере и скачать тайтл на устройство');
      navigate(`/login?next=${encodeURIComponent(`${location.pathname}${location.search}`)}`);
      return;
    }
    const target = activeManga ?? (activeVariantId === id ? manga : null);
    if (!target || chapters.length === 0) {
      toast.info('Пока нет глав для скачивания на устройство');
      return;
    }
    try {
      const job = await startTitleDownload({
        manga: target,
        chapters: target.chapters.length > 0 ? target.chapters : chapters,
        mangaId: activeVariantId,
        title: displayTitle,
        poster: activeVariant?.poster_url ?? viewManga.poster_url,
        source: activeVariant?.source ?? viewManga.source,
      });
      if (job) {
        toast.success(
          `Готовим ${formatInt(job.chapters.length)} глав на сервере и скачиваем на устройство. Прогресс сохранится.`,
        );
      } else {
        toast.info('Все главы уже скачаны на устройство');
      }
    } catch (error: unknown) {
      toast.error(humanizeError(error, 'Не удалось начать скачивание на устройство'));
    }
  };

  const downloadChapter = async (chapter: ChapterOut) => {
    if (chapter.is_external) {
      toast.info('Эта глава открывается на сайте источника и не сохраняется офлайн');
      return;
    }
    const target = activeManga ?? (activeVariantId === id ? manga : null);
    if (!target) {
      toast.error('Данные тайтла ещё не загружены — попробуйте через секунду');
      return;
    }
    try {
      const job = await startChapterDownload({
        manga: target,
        chapter,
        mangaId: activeVariantId,
        title: displayTitle,
        poster: activeVariant?.poster_url ?? viewManga.poster_url,
        source: activeVariant?.source ?? viewManga.source,
      });
      if (job) {
        toast.success(`${chapterHeading(chapter)} скачивается на устройство`);
      } else {
        toast.info(`${chapterHeading(chapter)} уже на устройстве`);
      }
    } catch (error: unknown) {
      toast.error(humanizeError(error, 'Не удалось скачать главу на устройство'));
    }
  };

  return (
    <div className="page container manga-page">
      <nav className="breadcrumbs" aria-label="Хлебные крошки">
        <Link to="/">Главная</Link>
        <Icon name="chevron-right" size={13} />
        <Link to="/catalogue">Каталог</Link>
        <Icon name="chevron-right" size={13} />
        <span aria-current="page">{displayTitle}</span>
      </nav>

      {viewManga.adult_only || viewManga.requires_age_confirmation || viewManga.adult ? (
        <AdultNotice source={viewManga.source} />
      ) : null}

      {mangaQuery.isError ? (
        <div className="manga-inline-error">
          <InlineError
            message={humanizeError(mangaQuery.error, 'Данные могли устареть — показана сохранённая версия.')}
            onRetry={() => void mangaQuery.refetch()}
          />
        </div>
      ) : null}

      <div className="manga-hero">
        <div className="manga-poster-column">
          <div className="manga-poster-frame">
            <Poster
              src={posterSrc}
              alt={`Обложка «${displayTitle}»`}
              blurred={viewManga.adult && blurAdultPosters}
              eager
            />
            {covers.length > 1 ? (
              <>
                <div className="manga-cover-nav">
                  <button
                    type="button"
                    className="manga-cover-nav__arrow"
                    aria-label="Предыдущая обложка"
                    onClick={() =>
                      setCoverIndex((safeCoverIndex - 1 + covers.length) % covers.length)
                    }
                  >
                    <Icon name="chevron-left" size={16} />
                  </button>
                  <span className="manga-cover-nav__count">
                    {safeCoverIndex + 1} / {covers.length}
                    {activeCover ? ` · ${sourceLabel(activeCover.source)}` : ''}
                  </span>
                  <button
                    type="button"
                    className="manga-cover-nav__arrow"
                    aria-label="Следующая обложка"
                    onClick={() => setCoverIndex((safeCoverIndex + 1) % covers.length)}
                  >
                    <Icon name="chevron-right" size={16} />
                  </button>
                </div>
                <div className="manga-cover-thumbs" role="list" aria-label="Все обложки тайтла">
                  {covers.map((cover, index) => (
                    <button
                      key={`${cover.source}-${cover.source_id}-${index}`}
                      type="button"
                      role="listitem"
                      className={`manga-cover-thumb${index === safeCoverIndex ? ' is-active' : ''}`}
                      onClick={() => setCoverIndex(index)}
                      aria-label={`Обложка ${sourceLabel(cover.source)}${cover.is_primary ? ', основная' : ''}`}
                      aria-pressed={index === safeCoverIndex}
                    >
                      <img src={resolveApiUrl(cover.url)} alt="" loading="lazy" decoding="async" />
                    </button>
                  ))}
                </div>
              </>
            ) : null}
            {viewManga.adult ? (
              <div className="manga-poster-overlay">
                <span className="badge badge--danger">18+</span>
                <button
                  type="button"
                  className="btn btn--sm"
                  onClick={() => updateReaderPrefs({ blurAdultPosters: !blurAdultPosters })}
                  aria-pressed={blurAdultPosters}
                >
                  <Icon name={blurAdultPosters ? 'eye' : 'eye-off'} size={15} />
                  {blurAdultPosters ? 'Показать' : 'Скрыть'}
                </button>
              </div>
            ) : null}
          </div>

          {viewManga.adult && blurAdultPosters ? (
            <p className="manga-poster-note">
              <Icon name="shield" size={15} />
              Обложка скрыта настройкой для контента 18+. Изображение не влияет на доступ к главам.
            </p>
          ) : null}

          <div className="manga-side-actions">
            <button
              type="button"
              className={`btn ${isBookmarked ? 'btn--primary' : 'btn--outline'} btn--block`}
              onClick={toggleBookmark}
              disabled={bookmarkMutation.isPending}
              aria-pressed={isBookmarked}
            >
              <Icon name="bookmark" size={17} />
              {isBookmarked ? 'В библиотеке' : 'В закладки'}
            </button>
            <button
              type="button"
              className={`btn ${isFollowing ? 'btn--primary' : 'btn--outline'} btn--block`}
              onClick={toggleFollow}
              disabled={followMutation.isPending || (Boolean(user) && followQuery.isLoading)}
              aria-pressed={isFollowing}
              title="Получать уведомление о каждой новой главе"
            >
              <Icon name="bell" size={17} />
              {isFollowing ? 'Вы следите за главами' : 'Следить за главами'}
            </button>
            {chapterDownloadTarget && chapterDownloadDone ? (
              <Link
                to={`/offline/read/${activeVariantId}/${chapterDownloadTarget.id}`}
                className="btn btn--outline btn--block"
              >
                <Icon name="check" size={17} />
                Читать главу офлайн
              </Link>
            ) : (
              <button
                type="button"
                className="btn btn--ghost btn--block"
                onClick={() => chapterDownloadTarget && void downloadChapter(chapterDownloadTarget)}
                disabled={
                  !chapterDownloadTarget ||
                  chapterDownloadTarget.is_external ||
                  chapterDownloadPending
                }
                title={
                  chapterDownloadTarget?.is_external
                    ? 'Внешняя глава открывается на сайте источника'
                    : 'Сохранить одну главу в офлайн-библиотеку устройства'
                }
              >
                {chapterDownloadPending ? (
                  <DancingSpinner size={17} />
                ) : (
                  <Icon name="download" size={17} />
                )}
                {chapterDownloadPending ? 'Скачиваем главу…' : 'Скачать главу на устройство'}
              </button>
            )}
          </div>
        </div>

        <div className="manga-info">
          <h1 className="manga-title">{displayTitle}</h1>
          {altTitles.length > 0 ? <p className="manga-alt-title">{altTitles.join(' · ')}</p> : null}

          <div className="manga-meta-line">
            <Rating
              value={activeVariant?.rating ?? viewManga.rating}
              count={viewManga.rating_count}
            />
            <span>{sourceLabel(activeVariant?.source ?? viewManga.source)}</span>
            {viewManga.last_chapter_at ? (
              <span title={formatDate(viewManga.last_chapter_at)}>
                Обновлено {formatRelative(viewManga.last_chapter_at)}
              </span>
            ) : null}
          </div>

          <div className="manga-facts">
            {viewManga.year ? <span className="chip">{viewManga.year}</span> : null}
            <span className="chip">{statusLabel(viewManga.status)}</span>
            <span className="chip">{contentTypeLabel(viewManga.content_type)}</span>
            <span className="chip">{chaptersLabel(chapterCount)}</span>
            {viewManga.adult ? <span className="badge badge--danger">18+</span> : null}
          </div>

          {showVariantPicker ? (
            <div className="variant-picker" role="group" aria-label="Источник тайтла">
              <div className="variant-picker__head">
                <span className="variant-picker__label">Источник</span>
                <span className="variant-picker__hint">Выберите, откуда читать</span>
              </div>
              <div className="variant-picker__options">
                {sourceVariants.map((variant) => {
                  const active = variant.source === activeVariant?.source;
                  const best = variant.id === bestVariant?.id;
                  return (
                    <button
                      key={variant.source}
                      type="button"
                      className={`variant-option${active ? ' is-active' : ''}`}
                      onClick={() => setSelectedVariantId(variant.id)}
                      aria-pressed={active}
                      title={`${sourceLabel(variant.source)} · ${variant.title}`}
                    >
                      <span className="variant-option__name">{sourceLabel(variant.source)}</span>
                      <span className="variant-option__meta">
                        {formatInt(variantChaptersCount(variant))} гл.
                      </span>
                      {best ? <span className="variant-option__badge">Больше глав</span> : null}
                    </button>
                  );
                })}
              </div>
            </div>
          ) : null}

          {viewManga.genres.length > 0 ? (
            <div className="manga-genres">
              {viewManga.genres.map((genre) => (
                <Link key={genre} to={`/catalog/genres#${encodeURIComponent(genre)}`} className="chip">
                  {genre}
                </Link>
              ))}
            </div>
          ) : null}

          <div className="manga-actions">
            {playHref && playChapter ? (
              <Link to={playHref} className="btn btn--primary btn--lg">
                <Icon name="book" size={18} />
                {isContinuing ? 'Продолжить чтение' : 'Читать'}
                {showVariantPicker && bestVariant ? ` · ${sourceLabel(bestVariant.source)}` : ''}
              </Link>
            ) : (
              <button type="button" className="btn btn--primary btn--lg" disabled>
                <Icon name="book" size={18} />
                {playLoading ? 'Загружаем главы…' : 'Глав пока нет'}
              </button>
            )}
            {playProgressChapter && playFirstChapter && playFirstChapter.id !== playChapter?.id ? (
              <Link to={`/reader/${playFirstChapter.id}`} className="btn btn--outline btn--lg">
                <Icon name="scroll" size={18} />
                С начала
              </Link>
            ) : null}
            <button
              type="button"
              className="btn btn--ghost btn--lg"
              onClick={() => void refreshMutation.mutate()}
              disabled={refreshMutation.isPending}
            >
              {refreshMutation.isPending ? (
                <DancingSpinner size={18} />
              ) : (
                <Icon name="refresh" size={18} />
              )}
              {refreshMutation.isPending ? 'Обновляем…' : 'Обновить из источника'}
            </button>
          </div>

          {deviceJob ? (
            <div
              className={`manga-download-status${deviceJob.status === 'error' || deviceJob.prepare.status === 'error' ? ' is-error' : ''}`}
              role="status"
            >
              <div className="manga-download-status__head">
                <span className="manga-download-status__icon" aria-hidden="true">
                  <Icon name={activeDeviceJob ? 'download' : 'alert'} size={17} />
                </span>
                <div className="manga-download-status__body">
                  <strong>
                    {activeDeviceJob
                      ? activeDeviceJob.prepare.status === 'running' ||
                        activeDeviceJob.prepare.status === 'idle'
                        ? activeDeviceJob.downloadedPages > 0
                          ? 'Готовим и скачиваем'
                          : 'Подготовка на сервере'
                        : 'Скачиваем на устройство'
                      : deviceJob.status === 'cancelled'
                        ? 'Загрузка отменена'
                        : 'Загрузка остановилась'}
                  </strong>
                  {deviceJob.mode === 'title' ? (
                    <>
                      <span>
                        Подготовка на сервере {formatInt(deviceJob.prepare.prepared)} из{' '}
                        {formatInt(deviceJob.chapters.length)}
                      </span>
                      <span>
                        Скачано на устройство {formatInt(deviceJob.completedChapters)} из{' '}
                        {formatInt(deviceJob.chapters.length)}
                      </span>
                      {deviceJob.prepare.failed > 0 ? (
                        <span>
                          Не удалось подготовить глав: {formatInt(deviceJob.prepare.failed)}.
                          Нажмите «Повторить» — готовое будет пропущено.
                        </span>
                      ) : null}
                    </>
                  ) : null}
                  {!activeDeviceJob ? (
                    <span>
                      {deviceJob.error ?? 'Повторите загрузку — уже скачанное будет пропущено.'}
                    </span>
                  ) : null}
                </div>
                {activeDeviceJob ? (
                  <button
                    type="button"
                    className="btn btn--ghost btn--sm"
                    onClick={() => void cancelDownload(activeDeviceJob.id)}
                  >
                    <Icon name="close" size={14} />
                    Отменить
                  </button>
                ) : (
                  <button
                    type="button"
                    className="btn btn--outline btn--sm"
                    onClick={() => void retryDownload(deviceJob.id)}
                  >
                    <Icon name="refresh" size={14} />
                    Повторить
                  </button>
                )}
              </div>
              {activeDeviceJob || deviceJob.mode === 'title' ? (
                <>
                  {deviceJob.mode === 'title' ? (
                    <div className="manga-download-status__progress">
                      <div className="progress">
                        <div
                          className="progress__bar"
                          style={{ width: `${preparePercent(deviceJob)}%` }}
                        />
                      </div>
                      <span>{preparePercent(deviceJob)}%</span>
                    </div>
                  ) : null}
                  <div className="manga-download-status__progress">
                    <div className="progress">
                      <div
                        className="progress__bar"
                        style={{ width: `${jobPercent(deviceJob)}%` }}
                      />
                    </div>
                    <span>{jobPercent(deviceJob)}%</span>
                  </div>
                </>
              ) : null}
            </div>
          ) : offlineStats && offlineStats.chapters > 0 ? (
            <div className="manga-download-status is-done" role="status">
              <span className="manga-download-status__icon" aria-hidden="true">
                <Icon name="check" size={17} />
              </span>
              <div className="manga-download-status__body">
                <strong>Уже на устройстве</strong>
                <span>
                  {formatInt(offlineStats.chapters)}{' '}
                  {offlineStats.chapters === 1 ? 'глава' : 'глав'} ·{' '}
                  {formatInt(offlineStats.pages)}{' '}
                  {offlineStats.pages === 1 ? 'страница' : 'страниц'} ·{' '}
                  {formatBytes(offlineStats.bytes)}
                </span>
              </div>
              <Link to={`/offline/manga/${activeVariantId}`} className="btn btn--outline btn--sm">
                <Icon name="book" size={14} />
                Открыть офлайн
              </Link>
            </div>
          ) : null}

          {progress && progressChapter ? (
            <div className="manga-status-note">
              <Icon name="book" size={18} />
              <div>
                Вы остановились на <strong>{chapterHeading(progressChapter)}</strong>, страница{' '}
                <strong>{progress.page}</strong> из {progress.total_pages || progressChapter.page_count}.{' '}
                <Link
                  to={`/reader/${progressChapter.id}?page=${progress.page}`}
                  style={{ color: 'var(--accent)', fontWeight: 650 }}
                >
                  Продолжить
                </Link>
              </div>
            </div>
          ) : null}

          {finishedTitle ? (
            <RecommendationShelf
              title="Что почитать дальше"
              surface="manga_completion"
              seedMangaId={id}
              limit={12}
              className="manga-completion"
            />
          ) : null}

          {viewManga.description ? (
            <div className="manga-description">
              <div className="manga-description__head">
                <h2>Описание</h2>
              </div>
              <p className={`manga-description__text${hasLongDescription && !descriptionExpanded ? ' is-clamped' : ''}`}>
                {viewManga.description}
              </p>
              {hasLongDescription ? (
                <button
                  type="button"
                  className="manga-description__toggle"
                  onClick={() => setDescriptionExpanded((value) => !value)}
                  aria-expanded={descriptionExpanded}
                >
                  {descriptionExpanded ? 'Свернуть' : 'Читать далее'}
                </button>
              ) : null}
            </div>
          ) : (
            <div className="manga-description">
              <div className="manga-description__head">
                <h2>Описание</h2>
              </div>
              <p className="manga-description__text">
                {viewManga.description_fallback ?? 'Упс. Описание не нашлось в источниках'}
              </p>
            </div>
          )}
        </div>
      </div>

      <div className="manga-content">
        <section className="chapters-panel" aria-labelledby="chapters-title">
          <div className="chapters-head">
            <div>
              <h2 className="chapters-head__title" id="chapters-title">
                Главы <span className="chapters-head__count">{formatInt(chapterCount)}</span>
              </h2>
              {firstChapter ? (
                <p className="section-head__sub">
                  {showVariantPicker && activeVariant
                    ? `${sourceLabel(activeVariant.source)} · `
                    : ''}
                  Последняя: {chapterHeading(chapters[0])} · {formatRelative(chapters[0].published_at)}
                </p>
              ) : showVariantPicker && activeVariant ? (
                <p className="section-head__sub">{sourceLabel(activeVariant.source)}</p>
              ) : null}
            </div>
            <div className="chapters-head__actions">
              <button
                type="button"
                className="btn btn--primary btn--sm"
                onClick={() => void queueDeviceDownload()}
                disabled={chapters.length === 0 || chaptersLoading || Boolean(activeDeviceJob)}
                title="Подготовить главы на сервере и сохранить их на это устройство. Уже скачанное будет пропущено."
              >
                <Icon name="download" size={16} />
                {activeDeviceJob
                  ? activeDeviceJob.prepare.status === 'running' ||
                    activeDeviceJob.prepare.status === 'idle'
                    ? `Подготовка ${preparePercent(activeDeviceJob)}%`
                    : `Скачиваем ${jobPercent(activeDeviceJob)}%`
                  : 'Скачать всё на устройство'}
              </button>
              <button
                type="button"
                className="btn btn--ghost btn--sm"
                onClick={() => void refreshMutation.mutate()}
                disabled={refreshMutation.isPending}
              >
                {refreshMutation.isPending ? (
                  <DancingSpinner size={16} />
                ) : (
                  <Icon name="refresh" size={16} />
                )}
                Обновить
              </button>
            </div>
          </div>

          {chaptersLoading ? (
            <div className="chapter-list chapter-list--loading" aria-busy="true">
              {Array.from({ length: 6 }, (_, index) => (
                <Skeleton key={index} height="58px" />
              ))}
            </div>
          ) : chaptersError ? (
            <div className="chapters-empty">
              <EmptyState
                compact
                icon="alert"
                title="Не удалось загрузить главы источника"
                description={humanizeError(activeMangaQuery.error, 'Попробуйте ещё раз или вернитесь к основному источнику.')}
                action={
                  <button
                    type="button"
                    className="btn btn--primary btn--sm"
                    onClick={() => void activeMangaQuery.refetch()}
                  >
                    <Icon name="refresh" size={15} />
                    Повторить
                  </button>
                }
                secondaryAction={
                  <button
                    type="button"
                    className="btn btn--outline btn--sm"
                    onClick={() => setSelectedVariantId(null)}
                  >
                    Основной источник
                  </button>
                }
              />
            </div>
          ) : chapters.length > 0 ? (
            <>
              <div className="chapter-tools">
                <SearchBox
                  value={chapterSearch}
                  onChange={setChapterSearch}
                  placeholder="Номер, название или перевод…"
                  ariaLabel="Поиск по главам"
                />
                <div className="chapter-tools__sort" role="group" aria-label="Сортировка глав">
                  <button
                    type="button"
                    className={chapterSort === 'desc' ? 'is-active' : ''}
                    onClick={() => setChapterSort('desc')}
                    aria-pressed={chapterSort === 'desc'}
                  >
                    Сначала новые
                  </button>
                  <button
                    type="button"
                    className={chapterSort === 'asc' ? 'is-active' : ''}
                    onClick={() => setChapterSort('asc')}
                    aria-pressed={chapterSort === 'asc'}
                  >
                    Сначала старые
                  </button>
                </div>
              </div>

              <div className="chapter-translations" role="group" aria-label="Фильтр по переводу">
                <button
                  type="button"
                  className={`chip${translationFilter === ALL_TRANSLATIONS ? ' is-active' : ''}`}
                  onClick={() => setTranslationFilter(ALL_TRANSLATIONS)}
                  aria-pressed={translationFilter === ALL_TRANSLATIONS}
                >
                  Все переводы
                </button>
                {translationGroups.map((group) => (
                  <button
                    key={group.key}
                    type="button"
                    className={`chip${translationFilter === group.key ? ' is-active' : ''}`}
                    onClick={() => setTranslationFilter(group.key)}
                    aria-pressed={translationFilter === group.key}
                    title={`${group.source}/${group.translator ?? 'Без перевода'}/${formatInt(group.count)}`}
                  >
                    <span className="chapter-translations__label">
                      {group.source}/{group.translator ?? 'Без перевода'}/{formatInt(group.count)}
                    </span>
                  </button>
                ))}
              </div>

              {shownChapters.length > 0 ? (
                <div className="chapter-list">
                  {shownChapters.map((chapter) => (
                    <ChapterRow
                      key={chapter.id}
                      chapter={chapter}
                      current={chapter.id === progress?.chapter_id}
                      downloaded={offlineChapterIds.has(chapter.id)}
                      downloadStatus={chapterJobStatuses.get(chapter.id)}
                      offlineHref={`/offline/read/${activeVariantId}/${chapter.id}`}
                      onDownload={downloadChapter}
                    />
                  ))}
                </div>
              ) : (
                <div className="chapters-empty">
                  <EmptyState
                    compact
                    icon="search"
                    title="Глава не найдена"
                    description="Измените запрос или выберите другой перевод — поиск идёт по номеру, тому, названию и команде."
                  />
                </div>
              )}

              {sortedChapters.length > shownChapters.length ? (
                <div className="chapter-load-more">
                  <button
                    type="button"
                    className="btn btn--outline btn--sm"
                    onClick={() => setVisibleChapters((value) => value + 60)}
                  >
                    Показать ещё {Math.min(60, sortedChapters.length - shownChapters.length)}
                  </button>
                </div>
              ) : null}
              {sortedChapters.length > 60 ? (
                <p className="chapter-list__hint">
                  Показано {formatInt(shownChapters.length)} из {formatInt(sortedChapters.length)} глав.
                </p>
              ) : null}
              <div className="chapters-mobile-cta">
                <button
                  type="button"
                  className="btn btn--outline btn--block"
                  onClick={() => setChaptersOpen(true)}
                >
                  <Icon name="list" size={17} />
                  Все главы ({formatInt(chapterCount)})
                </button>
              </div>
            </>
          ) : (
            <div className="chapters-empty">
              <EmptyState
                compact
                icon="download"
                title="Главы ещё не загружены"
                description="Каталог знает о тайтле, но список глав пуст. Обновите данные из источника — обычно это занимает несколько секунд."
                action={
                  <button
                    type="button"
                    className="btn btn--primary btn--sm"
                    onClick={() => void refreshMutation.mutate()}
                    disabled={refreshMutation.isPending}
                  >
                    {refreshMutation.isPending ? (
                      <DancingSpinner size={15} />
                    ) : (
                      <Icon name="refresh" size={15} />
                    )}
                    Загрузить главы
                  </button>
                }
              />
            </div>
          )}
        </section>

        {viewManga.adult_only || viewManga.requires_age_confirmation ? null : (
          <AdSlot placement="sidebar" adult={viewManga.adult} />
        )}
      </div>

      <RelatedShelf mangaId={id} />

      <CommentsSection mangaId={manga.id} />

      <Modal
        open={chaptersOpen}
        onClose={() => setChaptersOpen(false)}
        title="Главы"
        description={showVariantPicker && activeVariant ? `${displayTitle} · ${sourceLabel(activeVariant.source)}` : displayTitle}
        variant="sheet"
        footer={
          <>
            <span className="field__hint" style={{ marginRight: 'auto' }}>
              {formatInt(sortedChapters.length)} глав · {formatInt(chapters.length)} всего
            </span>
            <button type="button" className="btn btn--primary" onClick={() => setChaptersOpen(false)}>
              Готово
            </button>
          </>
        }
      >
        <div className="chapters-sheet">
          <SearchBox
            value={chapterSearch}
            onChange={setChapterSearch}
            placeholder="Номер, название или перевод…"
            ariaLabel="Поиск по главам"
          />
          <div className="chapter-translations" role="group" aria-label="Фильтр по переводу">
            <button
              type="button"
              className={`chip${translationFilter === ALL_TRANSLATIONS ? ' is-active' : ''}`}
              onClick={() => setTranslationFilter(ALL_TRANSLATIONS)}
            >
              Все переводы
            </button>
            {translationGroups.map((group) => (
              <button
                key={group.key}
                type="button"
                className={`chip${translationFilter === group.key ? ' is-active' : ''}`}
                onClick={() => setTranslationFilter(group.key)}
              >
                <span className="chapter-translations__label">
                  {group.source}/{group.translator ?? 'Без перевода'}/{formatInt(group.count)}
                </span>
              </button>
            ))}
          </div>
          <div className="chapter-list chapter-list--modal">
            {sortedChapters.slice(0, visibleChapters).map((chapter) => (
              <ChapterRow
                key={chapter.id}
                chapter={chapter}
                current={chapter.id === progress?.chapter_id}
                downloaded={offlineChapterIds.has(chapter.id)}
                downloadStatus={chapterJobStatuses.get(chapter.id)}
                offlineHref={`/offline/read/${activeVariantId}/${chapter.id}`}
                onDownload={downloadChapter}
              />
            ))}
          </div>
          {sortedChapters.length > visibleChapters ? (
            <div className="chapter-load-more">
              <button
                type="button"
                className="btn btn--outline btn--sm"
                onClick={() => setVisibleChapters((value) => value + 60)}
              >
                Показать ещё
              </button>
            </div>
          ) : null}
        </div>
      </Modal>
    </div>
  );
}
