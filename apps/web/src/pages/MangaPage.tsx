import { useDeferredValue, useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import { api, listItems } from '../api/client';
import type { ChapterOut, MangaVariantOut } from '../api/types';
import { ChapterRow } from '../components/ChapterRow';
import { EmptyState } from '../components/EmptyState';
import { ErrorState, InlineError } from '../components/ErrorState';
import { ExportDialog } from '../components/ExportDialog';
import { Icon } from '../components/Icon';
import { Modal } from '../components/Modal';
import { Poster } from '../components/Poster';
import { Rating } from '../components/Rating';
import { SearchBox } from '../components/SearchBox';
import { Skeleton } from '../components/Skeleton';
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
import { useDocumentTitle } from '../lib/hooks';
import { queryKeys } from '../lib/queryClient';
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

export default function MangaPage() {
  const { id = '' } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const user = useAuthStore((state) => state.user);
  const blurAdultPosters = useReaderStore((state) => state.blurAdultPosters);
  const updateReaderPrefs = useReaderStore((state) => state.update);

  const [descriptionExpanded, setDescriptionExpanded] = useState(false);
  const [chapterSearch, setChapterSearch] = useState('');
  const deferredChapterSearch = useDeferredValue(chapterSearch);
  const [chapterSort, setChapterSort] = useState<ChapterSort>('desc');
  const [visibleChapters, setVisibleChapters] = useState(60);
  const [exportChapter, setExportChapter] = useState<ChapterOut | null>(null);
  const [chaptersOpen, setChaptersOpen] = useState(false);
  const [selectedVariantId, setSelectedVariantId] = useState<string | null>(null);
  const [translationFilter, setTranslationFilter] = useState<string>(ALL_TRANSLATIONS);

  const mangaQuery = useQuery({
    queryKey: queryKeys.manga(id),
    queryFn: ({ signal }) => api.getManga(id, signal),
    enabled: Boolean(id),
  });
  const manga = mangaQuery.data;

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

  const progressQuery = useQuery({
    queryKey: queryKeys.progress,
    queryFn: ({ signal }) => api.getProgress(signal),
    enabled: Boolean(user),
  });

  const viewTitle = activeVariant?.title ?? manga?.title;
  useDocumentTitle(viewTitle ? `${viewTitle} — читать онлайн` : 'Тайтл — MangaPoisk Reborn');

  const bookmarks = listItems(bookmarksQuery.data);
  const isBookmarked = bookmarks.some((bookmark) => bookmark.manga_id === id);

  const progressItems = listItems(progressQuery.data);
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

  const warmMutation = useMutation({
    mutationFn: () => api.warmManga(activeVariant?.id ?? id),
    onSuccess: (result) => {
      toast.success(`Сервер архивирует ${formatInt(result.queued)} глав. Можно читать дальше.`);
    },
    onError: (error: unknown) => {
      toast.error(humanizeError(error, 'Не удалось поставить главы в очередь архива.'));
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
    setChapterSearch('');
    setChapterSort('desc');
    setVisibleChapters(60);
    setExportChapter(null);
    setChaptersOpen(false);
    setSelectedVariantId(null);
    setTranslationFilter(ALL_TRANSLATIONS);
  }, [id]);

  useEffect(() => {
    setTranslationFilter(ALL_TRANSLATIONS);
  }, [activeVariantId]);

  useEffect(() => {
    setVisibleChapters(60);
  }, [deferredChapterSearch, chapterSort, translationFilter, activeVariantId]);

  if (!manga) {
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
  const exportTarget = playChapter ?? firstChapter;

  const progressChapter = progress
    ? (chapters.find((chapter) => chapter.id === progress.chapter_id) ?? progress.chapter ?? null)
    : null;

  const viewManga = activeManga ?? manga;
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

  return (
    <div className="page container manga-page">
      <nav className="breadcrumbs" aria-label="Хлебные крошки">
        <Link to="/">Главная</Link>
        <Icon name="chevron-right" size={13} />
        <Link to="/catalogue">Каталог</Link>
        <Icon name="chevron-right" size={13} />
        <span aria-current="page">{displayTitle}</span>
      </nav>

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
              src={activeVariant?.poster_url ?? viewManga.poster_url}
              alt={`Обложка «${displayTitle}»`}
              blurred={viewManga.adult && blurAdultPosters}
              eager
            />
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
              className="btn btn--ghost btn--block"
              onClick={() => exportTarget && setExportChapter(exportTarget)}
              disabled={!exportTarget}
            >
              <Icon name="download" size={17} />
              Экспорт главы
            </button>
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
                <Link key={genre} to={`/catalogue?genre=${encodeURIComponent(genre)}`} className="chip">
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
              <Icon name="refresh" size={18} className={refreshMutation.isPending ? 'spin' : undefined} />
              {refreshMutation.isPending ? 'Обновляем…' : 'Обновить из источника'}
            </button>
          </div>

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
              <p className="manga-description__text">Описание пока не добавлено.</p>
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
                className="btn btn--outline btn--sm"
                onClick={() => exportTarget && setExportChapter(exportTarget)}
                disabled={!exportTarget}
              >
                <Icon name="download" size={16} />
                Скачать главу
              </button>
              <button
                type="button"
                className="btn btn--ghost btn--sm"
                onClick={() => warmMutation.mutate()}
                disabled={warmMutation.isPending}
                title="Сервер скачает все главы в свой архив; потом они читаются без источника"
              >
                <Icon name="server" size={16} />
                {warmMutation.isPending ? 'Готовим…' : 'Скачать всё'}
              </button>
              <button
                type="button"
                className="btn btn--ghost btn--sm"
                onClick={() => void refreshMutation.mutate()}
                disabled={refreshMutation.isPending}
              >
                <Icon name="refresh" size={16} className={refreshMutation.isPending ? 'spin' : undefined} />
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
                      onExport={setExportChapter}
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
                    <Icon name="refresh" size={15} className={refreshMutation.isPending ? 'spin' : undefined} />
                    Загрузить главы
                  </button>
                }
              />
            </div>
          )}
        </section>
      </div>

      <ExportDialog
        open={Boolean(exportChapter)}
        onClose={() => setExportChapter(null)}
        chapter={exportChapter}
      />

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
                onExport={(target) => {
                  setChaptersOpen(false);
                  setExportChapter(target);
                }}
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
