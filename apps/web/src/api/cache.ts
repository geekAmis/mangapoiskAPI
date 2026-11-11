import {
  dehydrate,
  hydrate,
  type DehydratedState,
  type Query,
  type QueryClient,
} from '@tanstack/react-query';
import { Capacitor } from '@capacitor/core';
import { Preferences } from '@capacitor/preferences';

/**
 * Устройство-локальный кэш публичных GET-ответов (каталог, поиск, тайтлы,
 * главы, варианты источников). На Android используется Capacitor Preferences
 * (SharedPreferences), а не localStorage браузера.
 */
export const isNativePlatform = Capacitor.isNativePlatform();

const STORAGE_KEY = 'mp:query-cache:v1';
const MAX_AGE_MS = 30 * 60_000;
const PERSIST_DEBOUNCE_MS = 900;

interface CacheEnvelope {
  savedAt: number;
  state: DehydratedState;
}

let hydratePromise: Promise<void> | null = null;
let persistTimer: number | null = null;
let persistenceStarted = false;

/** В кэш попадают только публичные данные. Библиотека и профиль не сохраняются. */
function shouldPersistQuery(query: Query): boolean {
  if (query.state.status !== 'success') return false;
  if (query.state.data === undefined) return false;
  if (!isFresh(query.state.dataUpdatedAt)) return false;
  const root = query.queryKey[0];
  return root === 'manga' || root === 'chapter' || root === 'sources';
}

function isFresh(updatedAt: number): boolean {
  return Number.isFinite(updatedAt) && updatedAt > 0 && Date.now() - updatedAt <= MAX_AGE_MS;
}

function clearTimer() {
  if (persistTimer !== null) {
    window.clearTimeout(persistTimer);
    persistTimer = null;
  }
}

export function hydrateQueryCache(client: QueryClient): Promise<void> {
  if (!isNativePlatform) return Promise.resolve();
  if (hydratePromise) return hydratePromise;

  hydratePromise = (async () => {
    try {
      const { value } = await Preferences.get({ key: STORAGE_KEY });
      if (!value) return;
      const parsed = JSON.parse(value) as Partial<CacheEnvelope>;
      if (
        !parsed.state ||
        !Array.isArray(parsed.state.queries) ||
        typeof parsed.savedAt !== 'number' ||
        Date.now() - parsed.savedAt > MAX_AGE_MS
      ) {
        await Preferences.remove({ key: STORAGE_KEY });
        return;
      }
      const freshQueries = parsed.state.queries.filter((query) =>
        isFresh(query.state?.dataUpdatedAt ?? 0),
      );
      if (freshQueries.length === 0) {
        await Preferences.remove({ key: STORAGE_KEY });
        return;
      }
      hydrate(client, { ...parsed.state, queries: freshQueries });
    } catch {
      // Повреждённый или устаревший кэш не должен мешать запуску приложения.
      await Preferences.remove({ key: STORAGE_KEY }).catch(() => undefined);
    }
  })();

  return hydratePromise;
}

export async function persistQueryCache(client: QueryClient): Promise<void> {
  if (!isNativePlatform) return;
  clearTimer();
  try {
    const state = dehydrate(client, { shouldDehydrateQuery: shouldPersistQuery });
    if (state.queries.length === 0) return;
    const envelope: CacheEnvelope = { savedAt: Date.now(), state };
    await Preferences.set({ key: STORAGE_KEY, value: JSON.stringify(envelope) });
  } catch {
    // Кэш — вспомогательный слой: ошибки записи игнорируем.
  }
}

export function startQueryCachePersistence(client: QueryClient): void {
  if (!isNativePlatform || persistenceStarted) return;
  persistenceStarted = true;

  const schedule = () => {
    clearTimer();
    persistTimer = window.setTimeout(() => {
      persistTimer = null;
      void persistQueryCache(client);
    }, PERSIST_DEBOUNCE_MS);
  };

  client.getQueryCache().subscribe(schedule);

  const flush = () => {
    if (persistTimer !== null) {
      void persistQueryCache(client);
    }
  };

  window.addEventListener('pagehide', flush);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') flush();
  });
}

/** Полностью очищает дисковый кэш (используется при смене сервера/выходе). */
export async function clearQueryCache(): Promise<void> {
  if (!isNativePlatform) return;
  clearTimer();
  try {
    await Preferences.remove({ key: STORAGE_KEY });
  } catch {
    // ignore
  }
}
