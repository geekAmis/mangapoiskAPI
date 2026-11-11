import { useEffect, useId, useRef, useState } from 'react';
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { api } from '../api/client';
import type { ImportMangaResponse } from '../api/types';
import { EmptyState } from '../components/EmptyState';
import { ErrorState, InlineError } from '../components/ErrorState';
import { Icon } from '../components/Icon';
import { MangaCard } from '../components/MangaCard';
import { MangaGridSkeleton, Skeleton } from '../components/Skeleton';
import { Modal } from '../components/Modal';
import { Pagination } from '../components/Pagination';
import { Poster } from '../components/Poster';
import { SearchBox } from '../components/SearchBox';
import { humanizeError } from '../lib/errors';
import {
  GENRE_OPTIONS,
  SORT_OPTIONS,
  STATUS_OPTIONS,
  formatInt,
  sourceLabel,
  statusLabel,
} from '../lib/format';
import { useDebouncedValue, useDocumentTitle } from '../lib/hooks';
import { queryKeys } from '../lib/queryClient';
import { toast } from '../stores/toast';

const LIMIT = 24;
const CURRENT_YEAR = new Date().getFullYear();
const YEARS = Array.from({ length: CURRENT_YEAR - 1989 }, (_, index) => CURRENT_YEAR - index);

function parsePage(value: string | null): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < 1) return 1;
  return Math.trunc(parsed);
}

function parseYear(value: string | null): number | undefined {
  if (!value || !/^\d{4}$/.test(value)) return undefined;
  const year = Number(value);
  return year >= 1950 && year <= CURRENT_YEAR + 1 ? year : undefined;
}

function isSort(value: string | null): value is (typeof SORT_OPTIONS)[number]['value'] {
  return SORT_OPTIONS.some((option) => option.value === value);
}

function isStatus(value: string | null): value is (typeof STATUS_OPTIONS)[number]['value'] {
  return STATUS_OPTIONS.some((option) => option.value === value);
}

export default function CataloguePage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const sourcesQuery = useQuery({
    queryKey: queryKeys.sources,
    queryFn: ({ signal }) => api.sources(signal),
    staleTime: 10 * 60_000,
  });

  const q = searchParams.get('q')?.trim() ?? '';
  const source = searchParams.get('source') ?? '';
  const genre = searchParams.get('genre') ?? '';
  const year = parseYear(searchParams.get('year'));
  const statusRaw = searchParams.get('status');
  const status = isStatus(statusRaw) ? statusRaw : '';
  const sortRaw = searchParams.get('sort');
  const sort = isSort(sortRaw) ? sortRaw : 'popular';
  const page = parsePage(searchParams.get('page'));

  const [filtersOpen, setFiltersOpen] = useState(false);
  const [liveOpen, setLiveOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [searchInput, setSearchInput] = useState(q);
  const debouncedSearch = useDebouncedValue(searchInput, 380);
  const committedSearchRef = useRef<string | null>(null);

  useDocumentTitle(q ? `${q} — поиск в каталоге` : 'Каталог манги — MangaPoisk Reborn');

  const params = {
    query: q || undefined,
    source: source || undefined,
    genre: genre || undefined,
    year,
    status: status || undefined,
    sort,
    page,
    limit: LIMIT,
  };

  const catalogueQuery = useQuery({
    queryKey: ['manga', 'list', params],
    queryFn: ({ signal }) => api.listManga(params, signal),
    placeholderData: keepPreviousData,
  });

  const updateParams = (patch: Record<string, string | undefined>, keepPage = false) => {
    const next = new URLSearchParams(searchParams);
    for (const [key, value] of Object.entries(patch)) {
      if (value) next.set(key, value);
      else next.delete(key);
    }
    if (!keepPage) next.delete('page');
    setSearchParams(next);
  };

  // Держим поле в синхроне с адресной строкой (переходы назад/вперёд, чипы).
  // Собственный debounce-коммит не должен затирать символы, набранные после него.
  useEffect(() => {
    if (committedSearchRef.current === q) {
      committedSearchRef.current = null;
      return;
    }
    setSearchInput(q);
  }, [q]);

  // Живой поиск с задержкой: запрос уходит, пока пользователь печатает.
  useEffect(() => {
    const next = debouncedSearch.trim();
    if (next === q) return;
    committedSearchRef.current = next;
    setSearchParams((current) => {
      const params = new URLSearchParams(current);
      if (next) params.set('q', next);
      else params.delete('q');
      params.delete('page');
      return params;
    });
  }, [debouncedSearch, q, setSearchParams]);

  // Подгружаем следующую страницу заранее, чтобы «Вперёд» открывалась мгновенно.
  useEffect(() => {
    const data = catalogueQuery.data;
    if (!data?.has_next || catalogueQuery.isFetching) return;
    const timer = window.setTimeout(() => {
      const nextParams = { ...params, page: page + 1 };
      void queryClient.prefetchQuery({
        queryKey: ['manga', 'list', nextParams],
        queryFn: ({ signal }) => api.listManga(nextParams, signal),
        staleTime: 2 * 60_000,
      });
    }, 1200);
    return () => window.clearTimeout(timer);
    // params намеренно разложен на примитивы ниже.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    catalogueQuery.data,
    catalogueQuery.isFetching,
    page,
    q,
    source,
    genre,
    year,
    status,
    sort,
    queryClient,
  ]);

  const resetFilters = () => {
    setSearchParams(new URLSearchParams());
    setFiltersOpen(false);
  };

  const goToPage = (nextPage: number) => {
    const next = new URLSearchParams(searchParams);
    if (nextPage <= 1) next.delete('page');
    else next.set('page', String(nextPage));
    setSearchParams(next);
    document.getElementById('catalogue-results')?.scrollIntoView({ block: 'start' });
  };

  const sources = sourcesQuery.data?.filter((item) => item.enabled) ?? [];
  const sourceOptions =
    sources.length > 0
      ? sources
      : [{ code: 'mangapoisk', name: 'MangaPoisk', enabled: true, language: 'ru', base_url: '', requires_cookies: false, capabilities: {} }];

  const activeFilterCount = [source, genre, year, status].filter(Boolean).length;
  const hasFilters = Boolean(q || activeFilterCount);
  const items = catalogueQuery.data?.items ?? [];
  const total = catalogueQuery.data?.total ?? 0;

  const activeChips: Array<{ key: string; label: string; clear: () => void }> = [];
  if (q) activeChips.push({ key: 'q', label: `«${q}»`, clear: () => updateParams({ q: undefined }) });
  if (source)
    activeChips.push({
      key: 'source',
      label: sources.find((item) => item.code === source)?.name ?? sourceLabel(source),
      clear: () => updateParams({ source: undefined }),
    });
  if (genre) activeChips.push({ key: 'genre', label: genre, clear: () => updateParams({ genre: undefined }) });
  if (year) activeChips.push({ key: 'year', label: String(year), clear: () => updateParams({ year: undefined }) });
  if (status)
    activeChips.push({
      key: 'status',
      label: statusLabel(status),
      clear: () => updateParams({ status: undefined }),
    });

  return (
    <div className="page container">
      <div className="page-head">
        <div className="page-head__main">
          <span className="eyebrow">Библиотека историй</span>
          <h1 className="page-title">Каталог</h1>
          <p className="page-subtitle">
            Поиск по локальному индексу и источникам. Фильтруйте по жанру, году и статусу
            выхода — всё сохраняется в адресной строке.
          </p>
        </div>
        <div className="page-head__actions">
          <button type="button" className="btn btn--outline" onClick={() => setImportOpen(true)}>
            <Icon name="plus" size={17} />
            Импорт по ссылке
          </button>
        </div>
      </div>

      <div className="catalogue-search">
        <SearchBox
          value={searchInput}
          size="lg"
          placeholder="Название, автор или альтернативное имя…"
          ariaLabel="Поиск по каталогу"
          onChange={setSearchInput}
          onSubmit={(value) => {
            setSearchInput(value);
            updateParams({ q: value || undefined });
          }}
          onClear={() => {
            setSearchInput('');
            updateParams({ q: undefined });
          }}
        />
      </div>

      <div className="catalogue-toolbar">
        <div className="catalogue-toolbar__search">
          <div className="chip-row">
            {SORT_OPTIONS.map((option) => (
              <button
                key={option.value}
                type="button"
                className={`chip${sort === option.value ? ' is-active' : ''}`}
                onClick={() => updateParams({ sort: option.value })}
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>
        <button
          type="button"
          className={`btn btn--outline filters-toggle${filtersOpen ? ' is-active' : ''}`}
          onClick={() => setFiltersOpen((value) => !value)}
          aria-expanded={filtersOpen}
          aria-controls="catalogue-filters"
        >
          <Icon name="filter" size={16} />
          Фильтры
          {activeFilterCount > 0 ? <span className="badge badge--accent">{activeFilterCount}</span> : null}
        </button>
      </div>

      <div id="catalogue-filters" className={`filters-panel${filtersOpen ? ' is-open' : ''}`}>
        <div className="field">
          <label className="field__label" htmlFor="filter-source">
            Источник
          </label>
          <select
            id="filter-source"
            className="select"
            value={source}
            onChange={(event) => updateParams({ source: event.target.value || undefined })}
          >
            <option value="">Все источники</option>
            {sourceOptions.map((item) => (
              <option key={item.code} value={item.code}>
                {item.name}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label className="field__label" htmlFor="filter-genre">
            Жанр
          </label>
          <select
            id="filter-genre"
            className="select"
            value={genre}
            onChange={(event) => updateParams({ genre: event.target.value || undefined })}
          >
            <option value="">Любой жанр</option>
            {GENRE_OPTIONS.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
            {genre && !GENRE_OPTIONS.includes(genre as (typeof GENRE_OPTIONS)[number]) ? (
              <option value={genre}>{genre}</option>
            ) : null}
          </select>
        </div>
        <div className="field">
          <label className="field__label" htmlFor="filter-year">
            Год
          </label>
          <select
            id="filter-year"
            className="select"
            value={year ? String(year) : ''}
            onChange={(event) => updateParams({ year: event.target.value || undefined })}
          >
            <option value="">Любой год</option>
            {YEARS.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label className="field__label" htmlFor="filter-status">
            Статус
          </label>
          <select
            id="filter-status"
            className="select"
            value={status}
            onChange={(event) => updateParams({ status: event.target.value || undefined })}
          >
            <option value="">Любой статус</option>
            {STATUS_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
        <div className="filters-actions">
          <button
            type="button"
            className="btn btn--ghost"
            onClick={resetFilters}
            disabled={!hasFilters && sort === 'popular'}
          >
            <Icon name="close" size={16} />
            Сбросить
          </button>
        </div>
      </div>

      <div id="catalogue-results" className="catalogue-meta">
        <div className="catalogue-meta__active">
          {activeChips.length > 0 ? (
            activeChips.map((chip) => (
              <button key={chip.key} type="button" className="chip is-active" onClick={chip.clear}>
                {chip.label}
                <Icon name="close" size={13} />
              </button>
            ))
          ) : (
            <span className="result-count">Все истории в локальном индексе</span>
          )}
          {activeChips.length > 0 ? (
            <button type="button" className="filter-clear" onClick={resetFilters}>
              Сбросить всё
            </button>
          ) : null}
        </div>
        {catalogueQuery.data ? (
          <span className="result-count">
            Найдено: <strong>{formatInt(total)}</strong>
          </span>
        ) : null}
      </div>

      {catalogueQuery.isError && items.length > 0 ? (
        <div style={{ marginBottom: 16 }}>
          <InlineError message={humanizeError(catalogueQuery.error)} onRetry={() => void catalogueQuery.refetch()} />
        </div>
      ) : null}

      {catalogueQuery.isLoading ? (
        <MangaGridSkeleton count={12} />
      ) : catalogueQuery.isError && items.length === 0 ? (
        <ErrorState
          title="Каталог недоступен"
          message={humanizeError(catalogueQuery.error)}
          onRetry={() => void catalogueQuery.refetch()}
          action={
            <button type="button" className="btn btn--outline btn--sm" onClick={() => setImportOpen(true)}>
              Импортировать по ссылке
            </button>
          }
        />
      ) : items.length > 0 ? (
        <>
          <div
            className={`manga-grid catalogue-grid${catalogueQuery.isFetching ? ' is-fetching' : ''}`}
            aria-busy={catalogueQuery.isFetching}
          >
            {items.map((manga, index) => (
              <MangaCard key={manga.id} manga={manga} eager={index < 6} />
            ))}
          </div>
          <Pagination
            page={catalogueQuery.data?.page ?? page}
            hasNext={catalogueQuery.data?.has_next ?? false}
            total={catalogueQuery.data?.total}
            limit={catalogueQuery.data?.limit ?? LIMIT}
            onChange={goToPage}
            disabled={catalogueQuery.isFetching}
          />
        </>
      ) : (
        <div className="catalogue-empty">
          <EmptyState
            icon={q ? 'search' : 'compass'}
            title={q ? 'Ничего не нашлось' : 'В каталоге пока пусто'}
            description={
              q
                ? 'В локальном индексе нет подходящих историй. Попробуйте живой поиск по источнику — найденное сразу добавится в каталог.'
                : 'Подключите источник или импортируйте мангу по ссылке. После импорта она появится в каталоге и в читалке.'
            }
            action={
              q ? (
                <button type="button" className="btn btn--primary" onClick={() => setLiveOpen(true)}>
                  <Icon name="search" size={17} />
                  Найти в источнике
                </button>
              ) : (
                <button type="button" className="btn btn--primary" onClick={() => setImportOpen(true)}>
                  <Icon name="plus" size={17} />
                  Импортировать мангу
                </button>
              )
            }
            secondaryAction={
              hasFilters ? (
                <button type="button" className="btn btn--outline" onClick={resetFilters}>
                  Сбросить фильтры
                </button>
              ) : (
                <button type="button" className="btn btn--outline" onClick={() => setImportOpen(true)}>
                  Импорт по ссылке
                </button>
              )
            }
          />
        </div>
      )}

      <LiveSearchDialog
        open={liveOpen}
        onClose={() => setLiveOpen(false)}
        query={q}
        source={source}
        onLiveImported={() => {
          void catalogueQuery.refetch();
        }}
      />
      <ImportDialog open={importOpen} onClose={() => setImportOpen(false)} sources={sourceOptions} />
    </div>
  );
}

function LiveSearchDialog({
  open,
  onClose,
  query,
  source,
  onLiveImported,
}: {
  open: boolean;
  onClose: () => void;
  query: string;
  source: string;
  onLiveImported: () => void;
}) {
  const navigate = useNavigate();
  const liveQuery = useQuery({
    queryKey: ['manga', 'live-search', query, source],
    queryFn: ({ signal }) => api.searchManga({ q: query, source: source || undefined, live: true, limit: 24 }, signal),
    enabled: open && query.trim().length > 0,
    retry: 0,
    staleTime: 0,
  });
  const notifiedRef = useRef<string | null>(null);

  useEffect(() => {
    if (!liveQuery.data) return;
    const key = `${query}::${source}`;
    if (notifiedRef.current === key) return;
    notifiedRef.current = key;
    onLiveImported();
  }, [liveQuery.data, query, source, onLiveImported]);

  const results = liveQuery.data?.items ?? [];

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Живой поиск по источнику"
      description={`Запрос «${query}». Найденные тайтлы автоматически импортируются в локальный каталог.`}
      size="lg"
      footer={
        <>
          <button type="button" className="btn btn--ghost" onClick={onClose}>
            Закрыть
          </button>
          <button
            type="button"
            className="btn btn--outline"
            onClick={() => {
              onLiveImported();
              onClose();
            }}
          >
            <Icon name="refresh" size={16} />
            Обновить каталог
          </button>
        </>
      }
    >
      {liveQuery.isLoading ? (
        <div style={{ display: 'grid', gap: 8 }}>
          {Array.from({ length: 4 }, (_, index) => (
            <Skeleton key={index} height="72px" />
          ))}
        </div>
      ) : liveQuery.isError ? (
        <ErrorState
          title="Источник не ответил"
          message={humanizeError(liveQuery.error)}
          onRetry={() => void liveQuery.refetch()}
        />
      ) : results.length > 0 ? (
        <>
          <div className="live-search-note">
            <Icon name="info" size={17} />
            <span>
              Найдено {formatInt(liveQuery.data?.total ?? results.length)}. Результаты уже
              сохранены в каталог — откройте тайтл, чтобы читать.
            </span>
          </div>
          <div className="live-results">
            {results.map((manga) => (
              <button
                key={manga.id}
                type="button"
                className="live-result"
                onClick={() => {
                  onClose();
                  navigate(`/manga/${manga.id}`);
                }}
              >
                <span className="live-result__poster">
                  <Poster src={manga.poster_url} alt="" />
                </span>
                <span className="live-result__body">
                  <span className="live-result__title">{manga.title}</span>
                  <span className="live-result__meta">
                    {sourceLabel(manga.source)}
                    {manga.year ? ` · ${manga.year}` : ''}
                  </span>
                  <span className="live-result__meta">
                    {manga.genres.slice(0, 2).join(' · ') || 'Жанры не указаны'}
                  </span>
                </span>
              </button>
            ))}
          </div>
        </>
      ) : (
        <EmptyState
          compact
          icon="search"
          title="В источнике ничего не нашлось"
          description="Попробуйте изменить запрос или выбрать другой источник. Импорт по прямой ссылке тоже доступен."
        />
      )}
    </Modal>
  );
}

function ImportDialog({
  open,
  onClose,
  sources,
}: {
  open: boolean;
  onClose: () => void;
  sources: Array<{ code: string; name: string }>;
}) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [source, setSource] = useState(sources[0]?.code ?? 'mangapoisk');
  const [url, setUrl] = useState('');
  const [error, setError] = useState('');
  const formId = useId();

  useEffect(() => {
    if (!open) return;
    setError('');
    setUrl('');
    setSource(sources[0]?.code ?? 'mangapoisk');
    // Список источников не должен сбрасывать уже введённую ссылку при обновлении каталога.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const mutation = useMutation({
    mutationFn: (targetUrl: string) =>
      api.importManga({ source, url: targetUrl, refresh: true }),
    onSuccess: (result: ImportMangaResponse) => {
      toast.success(
        `«${result.manga.title}» импортирована: глав — ${formatInt(result.imported_chapters)}, страниц — ${formatInt(result.imported_pages)}.`,
      );
      void queryClient.invalidateQueries({ queryKey: ['manga'] });
      onClose();
      navigate(`/manga/${result.manga.id}`);
    },
    onError: (mutationError: unknown) => {
      setError(humanizeError(mutationError, 'Не удалось импортировать мангу. Проверьте ссылку и источник.'));
    },
  });

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Импорт по ссылке"
      description="Вставьте публичную ссылку на страницу тайтла. Каталог загрузит метаданные и список глав."
      footer={
        <>
          <button type="button" className="btn btn--ghost" onClick={onClose} disabled={mutation.isPending}>
            Отмена
          </button>
          <button type="submit" form={formId} className="btn btn--primary" disabled={mutation.isPending}>
            {mutation.isPending ? (
              <>
                <Icon name="loader" size={16} className="spin" />
                Импортируем…
              </>
            ) : (
              <>
                <Icon name="download" size={16} />
                Импортировать
              </>
            )}
          </button>
        </>
      }
    >
      <form
        id={formId}
        className="import-form"
        onSubmit={(event) => {
          event.preventDefault();
          const trimmed = url.trim();
          if (!/^https?:\/\/\S+$/i.test(trimmed)) {
            setError('Введите полную ссылку, начинающуюся с http:// или https://.');
            return;
          }
          setError('');
          mutation.mutate(trimmed);
        }}
      >
        {error ? (
          <div className="form-alert" role="alert">
            <Icon name="alert" size={17} />
            <span>{error}</span>
          </div>
        ) : null}
        <div className="field">
          <label className="field__label" htmlFor="import-source">
            Источник
          </label>
          <select
            id="import-source"
            className="select"
            value={source}
            onChange={(event) => setSource(event.target.value)}
          >
            {sources.map((item) => (
              <option key={item.code} value={item.code}>
                {item.name}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label className="field__label" htmlFor="import-url">
            Ссылка на мангу
          </label>
          <input
            id="import-url"
            className="input"
            type="url"
            inputMode="url"
            placeholder="https://mangapoisk.me/manga/…"
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            autoFocus
            required
          />
          <span className="field__hint">
            Поддерживаются публичные страницы источника. Закрытые и платные главы не обходятся.
          </span>
        </div>
        <p className="import-form__note">
          Импорт может занять несколько секунд: каталог загружает обложку, описание и список глав.
          Если тайтл уже есть, данные обновятся.
        </p>
      </form>
    </Modal>
  );
}
