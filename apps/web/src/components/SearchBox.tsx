import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { useLocation, useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import type { SearchSuggestionOut } from '../api/types';
import { useDebouncedValue, useOnClickOutside } from '../lib/hooks';
import {
  clearSearchHistory,
  isPrivateSearchMode,
  loadSearchHistory,
  rememberSearchQuery,
  setPrivateSearchMode,
  subscribeSearchHistory,
  type SearchHistoryEntry,
} from '../lib/searchHistory';
import { useAuthStore } from '../stores/auth';
import { Icon } from './Icon';
import { Poster } from './Poster';

interface SearchBoxProps {
  value?: string;
  defaultValue?: string;
  onChange?: (value: string) => void;
  onSubmit?: (value: string) => void;
  onClear?: () => void;
  placeholder?: string;
  ariaLabel?: string;
  autoFocus?: boolean;
  className?: string;
  size?: 'md' | 'lg';
  /** Instant title suggestions for catalogue/header search. */
  enableSuggestions?: boolean;
}

type SuggestionOption =
  | {
      kind: 'title';
      key: string;
      id: string;
      title: string;
      subtitle: string;
      posterUrl: string | null;
    }
  | {
      kind: 'history';
      key: string;
      query: string;
      at: number;
    };

function titleSubtitle(item: SearchSuggestionOut): string {
  const parts: string[] = [];
  if (item.title_en && item.title_en.toLocaleLowerCase() !== item.title.toLocaleLowerCase()) {
    parts.push(item.title_en);
  }
  if (item.year) parts.push(String(item.year));
  return parts.join(' · ');
}

export function SearchBox({
  value,
  defaultValue = '',
  onChange,
  onSubmit,
  onClear,
  placeholder = 'Название манги или автор…',
  ariaLabel = 'Поиск манги',
  autoFocus = false,
  className,
  size = 'md',
  enableSuggestions = false,
}: SearchBoxProps) {
  const [local, setLocal] = useState(value ?? defaultValue);
  const [focused, setFocused] = useState(false);
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const inputRef = useRef<HTMLInputElement>(null);
  const formRef = useRef<HTMLFormElement>(null);
  const listboxId = useId();
  const navigate = useNavigate();
  const location = useLocation();
  const user = useAuthStore((state) => state.user);
  const namespace = user?.id ?? 'anon';
  const [history, setHistory] = useState<SearchHistoryEntry[]>(() =>
    enableSuggestions ? loadSearchHistory(namespace) : [],
  );
  const [privateMode, setPrivateModeState] = useState(() => isPrivateSearchMode());

  useEffect(() => {
    if (value !== undefined) setLocal(value);
  }, [value]);

  useEffect(() => {
    if (!enableSuggestions) return;
    setHistory(loadSearchHistory(namespace));
    setPrivateModeState(isPrivateSearchMode());
    return subscribeSearchHistory(() => {
      setHistory(loadSearchHistory(namespace));
      setPrivateModeState(isPrivateSearchMode());
    });
  }, [enableSuggestions, namespace]);

  useEffect(() => {
    // CataloguePage mirrors the typed query into `?q=` after a short pause.
    // That is a same-page URL update, not a navigation: closing the combobox
    // here would make suggestions disappear while the user is still typing.
    setOpen(false);
    setActiveIndex(-1);
  }, [location.pathname]);

  useOnClickOutside(
    formRef,
    () => {
      setOpen(false);
      setActiveIndex(-1);
    },
    open,
  );

  const trimmed = local.trim();
  const debounced = useDebouncedValue(trimmed, 180);
  const suggestionQuery = useQuery({
    queryKey: ['search', 'suggest', debounced],
    queryFn: ({ signal }) => api.suggestManga(debounced, 6, signal),
    enabled: enableSuggestions && focused && debounced.length >= 2,
    placeholderData: keepPreviousData,
    staleTime: 60_000,
    gcTime: 5 * 60_000,
    retry: false,
    refetchOnWindowFocus: false,
  });

  const suggestions = debounced.length >= 2 ? (suggestionQuery.data?.items ?? []) : [];
  const historyOptions = trimmed
    ? []
    : history.slice(0, 6).map<SuggestionOption>((entry) => ({
        kind: 'history',
        key: `history:${entry.query.toLocaleLowerCase()}`,
        query: entry.query,
        at: entry.at,
      }));
  const titleOptions = suggestions.map<SuggestionOption>((item) => ({
    kind: 'title',
    key: `title:${item.id}`,
    id: item.id,
    title: item.title,
    subtitle: titleSubtitle(item),
    posterUrl: item.poster_url,
  }));
  const options = useMemo(
    () => (trimmed ? titleOptions : historyOptions),
    // The arrays are rebuilt on each render; keying by content avoids stale
    // options after a debounced query resolves.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [trimmed, suggestions, history],
  );

  useEffect(() => {
    setActiveIndex(-1);
  }, [debounced, options.length]);

  const thinHint = !trimmed
    ? ''
    : trimmed.length < 2
      ? 'Введите ещё один символ'
      : '';
  const showDropdown = enableSuggestions && open;

  const update = (next: string) => {
    setLocal(next);
    onChange?.(next);
    if (enableSuggestions) {
      setOpen(true);
      setActiveIndex(-1);
    }
  };

  const close = () => {
    setOpen(false);
    setActiveIndex(-1);
  };

  const submit = (raw: string) => {
    const next = raw.trim();
    rememberSearchQuery(namespace, next);
    close();
    if (onSubmit) onSubmit(next);
    else navigate(next ? `/catalogue?q=${encodeURIComponent(next)}` : '/catalogue');
  };

  const selectOption = (option: SuggestionOption) => {
    rememberSearchQuery(namespace, option.kind === 'history' ? option.query : trimmed);
    close();
    inputRef.current?.focus();
    if (option.kind === 'title') {
      navigate(`/manga/${option.id}`);
      return;
    }
    setLocal(option.query);
    onChange?.(option.query);
    if (onSubmit) onSubmit(option.query);
    else navigate(`/catalogue?q=${encodeURIComponent(option.query)}`);
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (!enableSuggestions) return;
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setOpen(true);
      if (options.length > 0) {
        setActiveIndex((index) => (index + 1) % options.length);
      }
      return;
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault();
      setOpen(true);
      if (options.length > 0) {
        setActiveIndex((index) => (index <= 0 ? options.length - 1 : index - 1));
      }
      return;
    }
    if (event.key === 'Home' && open && options.length > 0) {
      event.preventDefault();
      setActiveIndex(0);
      return;
    }
    if (event.key === 'End' && open && options.length > 0) {
      event.preventDefault();
      setActiveIndex(options.length - 1);
      return;
    }
    if (event.key === 'Enter' && open && activeIndex >= 0 && options[activeIndex]) {
      event.preventDefault();
      selectOption(options[activeIndex]);
      return;
    }
    if (event.key === 'Escape' && open) {
      event.preventDefault();
      event.stopPropagation();
      close();
      return;
    }
    if (event.key === 'Tab') {
      close();
    }
  };

  const togglePrivate = () => {
    const next = !privateMode;
    setPrivateSearchMode(next);
    setPrivateModeState(next);
    setHistory(next ? [] : loadSearchHistory(namespace));
    setActiveIndex(-1);
  };

  const activeId =
    open && activeIndex >= 0 && options[activeIndex]
      ? `${listboxId}-option-${activeIndex}`
      : undefined;

  return (
    <form
      ref={formRef}
      className={`searchbox${size === 'lg' ? ' searchbox--lg' : ''}${className ? ` ${className}` : ''}`}
      role="search"
      onSubmit={(event) => {
        event.preventDefault();
        if (open && activeIndex >= 0 && options[activeIndex]) {
          selectOption(options[activeIndex]);
          return;
        }
        submit(local);
      }}
    >
      <span className="searchbox__icon" aria-hidden="true">
        <Icon name="search" size={19} />
      </span>
      <input
        ref={inputRef}
        type="search"
        className="searchbox__input"
        value={local}
        role={enableSuggestions ? 'combobox' : undefined}
        aria-label={ariaLabel}
        aria-autocomplete={enableSuggestions ? 'list' : undefined}
        aria-expanded={enableSuggestions ? showDropdown : undefined}
        aria-controls={enableSuggestions && showDropdown ? listboxId : undefined}
        aria-activedescendant={activeId}
        aria-haspopup={enableSuggestions ? 'listbox' : undefined}
        onChange={(event) => update(event.target.value)}
        onFocus={() => {
          setFocused(true);
          if (enableSuggestions) setOpen(true);
        }}
        onBlur={() => setFocused(false)}
        onKeyDown={onKeyDown}
        placeholder={placeholder}
        autoFocus={autoFocus}
        enterKeyHint="search"
        autoComplete="off"
        spellCheck={false}
      />
      {local ? (
        <button
          type="button"
          className="searchbox__clear"
          aria-label="Очистить поиск"
          onClick={() => {
            update('');
            onClear?.();
            if (enableSuggestions) {
              setOpen(true);
              inputRef.current?.focus();
            }
          }}
        >
          <Icon name="close" size={16} />
        </button>
      ) : null}
      <button type="submit" className="searchbox__submit" aria-label="Найти">
        <Icon name="search" size={18} />
      </button>

      {enableSuggestions && showDropdown ? (
        <div className="search-suggest">
          {options.length > 0 ? (
            <ul
              className="search-suggest__list"
              id={listboxId}
              role="listbox"
              aria-label={trimmed ? 'Подсказки поиска' : 'Недавние запросы'}
            >
              {options.map((option, index) => {
                const selected = index === activeIndex;
                const optionId = `${listboxId}-option-${index}`;
                return (
                  <li
                    key={option.key}
                    id={optionId}
                    role="option"
                    aria-selected={selected}
                    className={`search-suggest__option${selected ? ' is-active' : ''}`}
                    onMouseEnter={() => setActiveIndex(index)}
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() => selectOption(option)}
                  >
                    {option.kind === 'title' ? (
                      <>
                        <span className="search-suggest__poster" aria-hidden="true">
                          <Poster src={option.posterUrl} alt="" />
                        </span>
                        <span className="search-suggest__body">
                          <span className="search-suggest__title">{option.title}</span>
                          {option.subtitle ? (
                            <span className="search-suggest__meta">{option.subtitle}</span>
                          ) : null}
                        </span>
                        <Icon name="arrow-right" size={16} className="search-suggest__chevron" />
                      </>
                    ) : (
                      <>
                        <span className="search-suggest__icon" aria-hidden="true">
                          <Icon name="clock" size={17} />
                        </span>
                        <span className="search-suggest__body">
                          <span className="search-suggest__title">{option.query}</span>
                        </span>
                        <Icon name="arrow-right" size={16} className="search-suggest__chevron" />
                      </>
                    )}
                  </li>
                );
              })}
            </ul>
          ) : null}

          {options.length === 0 ? (
            <div className="search-suggest__status" role="status" aria-live="polite">
              {thinHint ? (
                thinHint
              ) : !trimmed ? (
                privateMode
                  ? 'Приватный режим: история не сохраняется.'
                  : 'Недавние запросы появятся здесь после первого поиска.'
              ) : suggestionQuery.isFetching ? (
                <>
                  <span className="search-suggest__spinner" aria-hidden="true" />
                  Ищем по каталогу…
                </>
              ) : suggestionQuery.isError ? (
                'Подсказки временно недоступны — нажмите Enter, чтобы искать.'
              ) : (
                'Ничего не найдено. Нажмите Enter, чтобы искать в каталоге.'
              )}
            </div>
          ) : null}

          <div className="search-suggest__footer">
            {history.length > 0 && !privateMode ? (
              <button
                type="button"
                className="search-suggest__footer-btn"
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => clearSearchHistory(namespace)}
              >
                <Icon name="trash" size={14} />
                Очистить историю
              </button>
            ) : (
              <span className="search-suggest__footer-hint">
                {privateMode ? 'История не сохраняется' : 'История хранится только на устройстве'}
              </span>
            )}
            <button
              type="button"
              className={`search-suggest__footer-btn${privateMode ? ' is-active' : ''}`}
              aria-pressed={privateMode}
              onMouseDown={(event) => event.preventDefault()}
              onClick={togglePrivate}
            >
              <Icon name={privateMode ? 'eye-off' : 'eye'} size={14} />
              Приватный режим
            </button>
          </div>
        </div>
      ) : null}
    </form>
  );
}
