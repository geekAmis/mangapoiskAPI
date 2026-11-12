/**
 * Recent search history is deliberately device-local:
 *   * it never goes to the API and therefore cannot leak between accounts;
 *   * entries are namespaced per signed-in user (anonymous searches get their
 *     own bucket), so a second user on a shared device does not see them;
 *   * privacy mode stops both reading and writing the history.
 */

const HISTORY_PREFIX = 'mp:search-history:v1';
const PRIVATE_KEY = 'mp:search-private:v1';
const MAX_ENTRIES = 8;
const CHANGE_EVENT = 'mp:search-history-change';

export interface SearchHistoryEntry {
  query: string;
  at: number;
}

function storage(): Storage | null {
  if (typeof window === 'undefined') return null;
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function historyKey(namespace: string): string {
  return `${HISTORY_PREFIX}:${namespace || 'anon'}`;
}

function normalizeQuery(value: string): string {
  return value.trim().replace(/\s+/g, ' ');
}

function parseEntries(raw: string | null): SearchHistoryEntry[] {
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    const entries: SearchHistoryEntry[] = [];
    for (const item of parsed) {
      const query =
        typeof item === 'string'
          ? item
          : typeof item === 'object' && item !== null && typeof (item as { query?: unknown }).query === 'string'
            ? (item as { query: string }).query
            : '';
      const cleaned = normalizeQuery(query);
      if (!cleaned) continue;
      const at =
        typeof item === 'object' && item !== null && typeof (item as { at?: unknown }).at === 'number'
          ? (item as { at: number }).at
          : 0;
      entries.push({ query: cleaned, at });
    }
    return entries;
  } catch {
    return [];
  }
}

function notify(): void {
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new Event(CHANGE_EVENT));
  }
}

export function isPrivateSearchMode(): boolean {
  const store = storage();
  return store?.getItem(PRIVATE_KEY) === '1';
}

export function setPrivateSearchMode(value: boolean): void {
  const store = storage();
  if (!store) return;
  try {
    if (value) store.setItem(PRIVATE_KEY, '1');
    else store.removeItem(PRIVATE_KEY);
  } catch {
    // Storage can be disabled (private browsing, quotas); the in-memory UI
    // still respects the toggle for this session.
  }
  notify();
}

export function loadSearchHistory(namespace: string): SearchHistoryEntry[] {
  if (isPrivateSearchMode()) return [];
  const store = storage();
  if (!store) return [];
  const entries = parseEntries(store.getItem(historyKey(namespace)));
  const seen = new Set<string>();
  const unique: SearchHistoryEntry[] = [];
  for (const entry of entries) {
    const key = entry.query.toLocaleLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    unique.push(entry);
    if (unique.length >= MAX_ENTRIES) break;
  }
  return unique;
}

export function rememberSearchQuery(namespace: string, value: string): void {
  if (isPrivateSearchMode()) return;
  const query = normalizeQuery(value);
  if (!query) return;
  const store = storage();
  if (!store) return;
  const key = historyKey(namespace);
  const entries = parseEntries(store.getItem(key)).filter(
    (entry) => entry.query.toLocaleLowerCase() !== query.toLocaleLowerCase(),
  );
  entries.unshift({ query, at: Date.now() });
  try {
    store.setItem(key, JSON.stringify(entries.slice(0, MAX_ENTRIES)));
    notify();
  } catch {
    // Quota/disabled storage must never break search.
  }
}

export function clearSearchHistory(namespace: string): void {
  const store = storage();
  if (!store) return;
  try {
    store.removeItem(historyKey(namespace));
    notify();
  } catch {
    // ignore
  }
}

export function subscribeSearchHistory(callback: () => void): () => void {
  if (typeof window === 'undefined') return () => undefined;
  window.addEventListener(CHANGE_EVENT, callback);
  return () => window.removeEventListener(CHANGE_EVENT, callback);
}
