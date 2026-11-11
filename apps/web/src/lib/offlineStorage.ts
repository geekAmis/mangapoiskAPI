/**
 * Устройство-хранилище офлайн-библиотеки.
 *
 * - Android/iOS (Capacitor): изображения — @capacitor/filesystem (Directory.Data),
 *   манифесты, очередь и прогресс — @capacitor/preferences. localStorage не используется.
 * - Браузер: изображения и манифесты — IndexedDB. Для байтов изображений
 *   localStorage не используется нигде.
 */

import { Capacitor } from '@capacitor/core';
import { Directory, Filesystem } from '@capacitor/filesystem';
import { Preferences } from '@capacitor/preferences';
import type {
  OfflineChapter,
  OfflinePage,
  OfflineProgress,
  OfflineStats,
  OfflineTitle,
} from './offlineTypes';
import { offlineTitleStats } from './offlineTypes';

const DB_NAME = 'mangapoisk-offline';
const DB_VERSION = 1;
const TITLES_STORE = 'titles';
const IMAGES_STORE = 'images';
const PROGRESS_STORE = 'progress';
const VALUES_STORE = 'values';

const TITLE_INDEX_KEY = 'offline.titles.v1';
const QUEUE_KEY = 'offline.queue.v1';

const OBJECT_URLS = new Map<string, string>();
const listeners = new Set<() => void>();

export function isNativeOfflineStorage(): boolean {
  return Capacitor.isNativePlatform();
}

/* ------------------------------------------------------------------ */
/* IndexedDB (web)                                                     */
/* ------------------------------------------------------------------ */

interface StoredImage {
  path: string;
  blob: Blob;
  contentType: string;
  size: number;
}

interface StoredValue {
  key: string;
  value: unknown;
}

let dbPromise: Promise<IDBDatabase> | null = null;

function openDb(): Promise<IDBDatabase> {
  if (typeof indexedDB === 'undefined') {
    return Promise.reject(new Error('Браузер не поддерживает IndexedDB для офлайн-библиотеки'));
  }
  if (!dbPromise) {
    dbPromise = new Promise<IDBDatabase>((resolve, reject) => {
      const request = indexedDB.open(DB_NAME, DB_VERSION);
      request.onupgradeneeded = () => {
        const db = request.result;
        if (!db.objectStoreNames.contains(TITLES_STORE)) {
          db.createObjectStore(TITLES_STORE, { keyPath: 'id' });
        }
        if (!db.objectStoreNames.contains(IMAGES_STORE)) {
          db.createObjectStore(IMAGES_STORE, { keyPath: 'path' });
        }
        if (!db.objectStoreNames.contains(PROGRESS_STORE)) {
          db.createObjectStore(PROGRESS_STORE, { keyPath: 'key' });
        }
        if (!db.objectStoreNames.contains(VALUES_STORE)) {
          db.createObjectStore(VALUES_STORE, { keyPath: 'key' });
        }
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error ?? new Error('Не удалось открыть IndexedDB'));
    });
  }
  return dbPromise;
}

function idbRequest<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error('Ошибка IndexedDB'));
  });
}

function idbTransactionDone(transaction: IDBTransaction): Promise<void> {
  return new Promise<void>((resolve, reject) => {
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error ?? new Error('Ошибка IndexedDB'));
    transaction.onabort = () => reject(transaction.error ?? new Error('Транзакция отменена'));
  });
}

async function idbGet<T>(store: string, key: IDBValidKey): Promise<T | undefined> {
  const db = await openDb();
  const tx = db.transaction(store, 'readonly');
  return idbRequest<T | undefined>(tx.objectStore(store).get(key));
}

async function idbGetAll<T>(store: string): Promise<T[]> {
  const db = await openDb();
  const tx = db.transaction(store, 'readonly');
  return idbRequest<T[]>(tx.objectStore(store).getAll());
}

async function idbPut(store: string, value: unknown): Promise<void> {
  const db = await openDb();
  const tx = db.transaction(store, 'readwrite');
  tx.objectStore(store).put(value);
  await idbTransactionDone(tx);
}

async function idbDelete(store: string, key: IDBValidKey): Promise<void> {
  const db = await openDb();
  const tx = db.transaction(store, 'readwrite');
  tx.objectStore(store).delete(key);
  await idbTransactionDone(tx);
}

/* ------------------------------------------------------------------ */
/* Preferences (native) / values store (web)                           */
/* ------------------------------------------------------------------ */

export async function readPersistentValue<T>(key: string): Promise<T | null> {
  if (isNativeOfflineStorage()) {
    const result = await Preferences.get({ key });
    if (!result.value) return null;
    try {
      return JSON.parse(result.value) as T;
    } catch {
      return null;
    }
  }
  const stored = await idbGet<StoredValue>(VALUES_STORE, key);
  return stored ? (stored.value as T) : null;
}

export async function writePersistentValue<T>(key: string, value: T | null): Promise<void> {
  if (isNativeOfflineStorage()) {
    if (value === null) await Preferences.remove({ key });
    else await Preferences.set({ key, value: JSON.stringify(value) });
    return;
  }
  if (value === null) await idbDelete(VALUES_STORE, key);
  else await idbPut(VALUES_STORE, { key, value } satisfies StoredValue);
}

/* ------------------------------------------------------------------ */
/* Manifest helpers                                                    */
/* ------------------------------------------------------------------ */

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function isOfflineTitle(value: unknown): value is OfflineTitle {
  if (!isRecord(value)) return false;
  return (
    typeof value.id === 'string' &&
    typeof value.title === 'string' &&
    Array.isArray(value.chapters)
  );
}

function titleKey(id: string): string {
  return `offline.title.${id}`;
}

export function offlineChapterPrefix(mangaId: string, chapterId: string): string {
  return `offline/${safeSegment(mangaId)}/${safeSegment(chapterId)}/`;
}

export function offlineTitlePrefix(mangaId: string): string {
  return `offline/${safeSegment(mangaId)}/`;
}

export function offlinePagePath(mangaId: string, chapterId: string, number: number): string {
  return `${offlineChapterPrefix(mangaId, chapterId)}${number}.bin`;
}

function safeSegment(value: string): string {
  return value.replace(/[^A-Za-z0-9._-]/g, '_');
}

function emitTitlesChanged(): void {
  for (const listener of listeners) listener();
}

export function subscribeOfflineTitles(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export async function listOfflineTitles(): Promise<OfflineTitle[]> {
  let titles: OfflineTitle[];
  if (isNativeOfflineStorage()) {
    const ids = (await readPersistentValue<string[]>(TITLE_INDEX_KEY)) ?? [];
    const values = await Promise.all(ids.map((id) => readPersistentValue<unknown>(titleKey(id))));
    titles = values.filter(isOfflineTitle);
  } else {
    titles = await idbGetAll<OfflineTitle>(TITLES_STORE);
  }
  return titles.sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
}

export async function getOfflineTitle(id: string): Promise<OfflineTitle | null> {
  if (isNativeOfflineStorage()) {
    const value = await readPersistentValue<unknown>(titleKey(id));
    return isOfflineTitle(value) ? value : null;
  }
  return (await idbGet<OfflineTitle>(TITLES_STORE, id)) ?? null;
}

export async function saveOfflineTitle(title: OfflineTitle): Promise<void> {
  const normalized: OfflineTitle = {
    ...title,
    chapters: [...title.chapters].sort((a, b) =>
      (a.volume ?? '').localeCompare(b.volume ?? '', 'ru', { numeric: true }) ||
      a.number.localeCompare(b.number, 'ru', { numeric: true }),
    ),
    updatedAt: new Date().toISOString(),
  };
  if (isNativeOfflineStorage()) {
    await writePersistentValue(titleKey(normalized.id), normalized);
    const ids = (await readPersistentValue<string[]>(TITLE_INDEX_KEY)) ?? [];
    if (!ids.includes(normalized.id)) {
      await writePersistentValue(TITLE_INDEX_KEY, [normalized.id, ...ids]);
    }
  } else {
    await idbPut(TITLES_STORE, normalized);
  }
  emitTitlesChanged();
}

export async function deleteOfflineTitle(id: string): Promise<void> {
  if (isNativeOfflineStorage()) {
    await writePersistentValue(titleKey(id), null);
    const ids = (await readPersistentValue<string[]>(TITLE_INDEX_KEY)) ?? [];
    await writePersistentValue(
      TITLE_INDEX_KEY,
      ids.filter((value) => value !== id),
    );
  } else {
    await idbDelete(TITLES_STORE, id);
  }
  await removeOfflineFiles(offlineTitlePrefix(id));
  revokeCachedUrls(offlineTitlePrefix(id));
  emitTitlesChanged();
}

export async function deleteOfflineChapter(mangaId: string, chapterId: string): Promise<void> {
  const title = await getOfflineTitle(mangaId);
  if (!title) return;
  const chapters = title.chapters.filter((chapter) => chapter.id !== chapterId);
  await removeOfflineFiles(offlineChapterPrefix(mangaId, chapterId));
  revokeCachedUrls(offlineChapterPrefix(mangaId, chapterId));
  if (chapters.length === 0) {
    await deleteOfflineTitle(mangaId);
    return;
  }
  await saveOfflineTitle({ ...title, chapters });
}

/* ------------------------------------------------------------------ */
/* Images                                                              */
/* ------------------------------------------------------------------ */

export interface SaveOfflinePageInput {
  mangaId: string;
  chapterId: string;
  number: number;
  width: number | null;
  height: number | null;
  blob: Blob;
  contentType: string;
}

export async function saveOfflinePage(input: SaveOfflinePageInput): Promise<OfflinePage> {
  const path = offlinePagePath(input.mangaId, input.chapterId, input.number);
  const contentType = input.contentType || input.blob.type || 'image/jpeg';
  const size = input.blob.size;

  if (isNativeOfflineStorage()) {
    const base64 = await blobToBase64(input.blob);
    await Filesystem.writeFile({
      path,
      data: base64,
      directory: Directory.Data,
      recursive: true,
    });
  } else {
    await idbPut(IMAGES_STORE, {
      path,
      blob: input.blob,
      contentType,
      size,
    } satisfies StoredImage);
  }

  return {
    number: input.number,
    path,
    width: input.width ?? null,
    height: input.height ?? null,
    contentType,
    size,
  };
}

export interface OfflinePageInfo {
  exists: boolean;
  size: number;
  contentType: string | null;
}

export async function getOfflinePageInfo(path: string): Promise<OfflinePageInfo> {
  if (isNativeOfflineStorage()) {
    try {
      const stat = await Filesystem.stat({ path, directory: Directory.Data });
      return { exists: true, size: stat.size ?? 0, contentType: null };
    } catch {
      return { exists: false, size: 0, contentType: null };
    }
  }
  const record = await idbGet<StoredImage>(IMAGES_STORE, path);
  if (!record) return { exists: false, size: 0, contentType: null };
  return { exists: true, size: record.size, contentType: record.contentType };
}

/** URL для <img>: blob URL в браузере, capacitor-преобразованный file:// на нативе. */
export async function getOfflinePageUrl(page: OfflinePage): Promise<string> {
  const cached = OBJECT_URLS.get(page.path);
  if (cached) return cached;

  if (isNativeOfflineStorage()) {
    const result = await Filesystem.getUri({ path: page.path, directory: Directory.Data });
    const url = Capacitor.convertFileSrc(result.uri);
    OBJECT_URLS.set(page.path, url);
    return url;
  }

  const record = await idbGet<StoredImage>(IMAGES_STORE, page.path);
  if (!record) throw new Error('Изображение не найдено в офлайн-хранилище');
  const url = URL.createObjectURL(record.blob);
  OBJECT_URLS.set(page.path, url);
  return url;
}

/**
 * Дополнительная точка входа из манифеста: получить URL по идентификаторам.
 * Страницы хранят путь, поэтому читалке удобнее getOfflinePageUrl(page).
 */
export async function getOfflineTitlePageUrl(
  mangaId: string,
  chapterId: string,
  pageNumber: number,
): Promise<string | null> {
  const title = await getOfflineTitle(mangaId);
  const chapter = title?.chapters.find((item) => item.id === chapterId);
  const page = chapter?.pages.find((item) => item.number === pageNumber);
  if (!page) return null;
  return getOfflinePageUrl(page);
}

async function removeOfflineFiles(prefix: string): Promise<void> {
  if (isNativeOfflineStorage()) {
    try {
      await Filesystem.rmdir({ path: prefix.replace(/\/$/, ''), directory: Directory.Data, recursive: true });
    } catch {
      // Каталога может не быть — это нормально при удалении/отмене.
    }
    return;
  }
  const db = await openDb();
  const tx = db.transaction(IMAGES_STORE, 'readwrite');
  const store = tx.objectStore(IMAGES_STORE);
  const request = store.openKeyCursor();
  await new Promise<void>((resolve, reject) => {
    request.onerror = () => reject(request.error ?? new Error('Ошибка IndexedDB'));
    request.onsuccess = () => {
      const cursor = request.result;
      if (!cursor) {
        resolve();
        return;
      }
      if (String(cursor.primaryKey).startsWith(prefix)) store.delete(cursor.primaryKey);
      cursor.continue();
    };
  });
  await idbTransactionDone(tx);
}

function revokeCachedUrls(prefix: string): void {
  for (const [path, url] of OBJECT_URLS) {
    if (path.startsWith(prefix)) {
      if (url.startsWith('blob:')) URL.revokeObjectURL(url);
      OBJECT_URLS.delete(path);
    }
  }
}

/* ------------------------------------------------------------------ */
/* Progress                                                            */
/* ------------------------------------------------------------------ */

interface ProgressRecord {
  key: string;
  value: OfflineProgress;
}

function progressKey(mangaId: string, chapterId: string): string {
  return `${mangaId}:${chapterId}`;
}

export async function getOfflineProgress(
  mangaId: string,
  chapterId: string,
): Promise<OfflineProgress | null> {
  const key = progressKey(mangaId, chapterId);
  if (isNativeOfflineStorage()) {
    return readPersistentValue<OfflineProgress>(`offline.progress.${key}`);
  }
  const record = await idbGet<ProgressRecord>(PROGRESS_STORE, key);
  return record?.value ?? null;
}

export async function saveOfflineProgress(progress: OfflineProgress): Promise<void> {
  const key = progressKey(progress.mangaId, progress.chapterId);
  if (isNativeOfflineStorage()) {
    await writePersistentValue(`offline.progress.${key}`, progress);
    return;
  }
  await idbPut(PROGRESS_STORE, { key, value: progress } satisfies ProgressRecord);
}

/* ------------------------------------------------------------------ */
/* Queue persistence                                                   */
/* ------------------------------------------------------------------ */

export async function readDownloadQueue<T>(): Promise<T | null> {
  return readPersistentValue<T>(QUEUE_KEY);
}

export async function writeDownloadQueue<T>(value: T): Promise<void> {
  await writePersistentValue(QUEUE_KEY, value);
}

/* ------------------------------------------------------------------ */
/* Stats / chapters helpers                                            */
/* ------------------------------------------------------------------ */

export function statsFromTitles(titles: OfflineTitle[]): OfflineStats {
  return titles.reduce<OfflineStats>(
    (acc, title) => {
      const stats = offlineTitleStats(title);
      return {
        chapters: acc.chapters + stats.chapters,
        pages: acc.pages + stats.pages,
        bytes: acc.bytes + stats.bytes,
      };
    },
    { chapters: 0, pages: 0, bytes: 0 },
  );
}

export async function getOfflineTotalSize(): Promise<OfflineStats> {
  return statsFromTitles(await listOfflineTitles());
}

export async function findOfflineChapter(
  mangaId: string,
  chapterId: string,
): Promise<{ title: OfflineTitle; chapter: OfflineChapter } | null> {
  const title = await getOfflineTitle(mangaId);
  const chapter = title?.chapters.find((item) => item.id === chapterId);
  return title && chapter ? { title, chapter } : null;
}

export async function isChapterFullyDownloaded(
  mangaId: string,
  chapterId: string,
  expectedPages?: number,
): Promise<boolean> {
  const found = await findOfflineChapter(mangaId, chapterId);
  if (!found) return false;
  if (found.chapter.pages.length === 0) return false;
  if (expectedPages && found.chapter.pages.length < expectedPages) return false;
  return true;
}

/* ------------------------------------------------------------------ */
/* Utils                                                               */
/* ------------------------------------------------------------------ */

async function blobToBase64(blob: Blob): Promise<string> {
  const buffer = await blob.arrayBuffer();
  const bytes = new Uint8Array(buffer);
  const chunk = 0x8000;
  let binary = '';
  for (let offset = 0; offset < bytes.length; offset += chunk) {
    binary += String.fromCharCode(...bytes.subarray(offset, Math.min(offset + chunk, bytes.length)));
  }
  return btoa(binary);
}
