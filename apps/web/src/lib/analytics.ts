import { api } from '../api/client';
import type { AnalyticsEventIn, AnalyticsEventName } from '../api/types';

const CLIENT_KEY = 'mp:analytics-client:v1';
const QUEUE_KEY = 'mp:analytics-queue:v1';
const MAX_QUEUE = 50;
const FLUSH_DELAY_MS = 1800;

let flushTimer: number | null = null;
let flushing = false;

function randomId(): string {
  try {
    return crypto.randomUUID().replace(/-/g, '');
  } catch {
    return `${Date.now().toString(36)}${Math.random().toString(36).slice(2)}`;
  }
}

export function analyticsOptedOut(): boolean {
  if (typeof navigator === 'undefined') return true;
  const nav = navigator as Navigator & { globalPrivacyControl?: boolean };
  return (
    nav.doNotTrack === '1' ||
    nav.globalPrivacyControl === true ||
    (typeof window !== 'undefined' &&
      (window as Window & { doNotTrack?: string }).doNotTrack === '1')
  );
}

const optedOut = analyticsOptedOut;

export function analyticsClientId(): string {
  if (typeof window === 'undefined') return 'server';
  try {
    const existing = window.localStorage.getItem(CLIENT_KEY);
    if (existing && /^[A-Za-z0-9_-]{8,64}$/.test(existing)) return existing;
    const created = randomId().slice(0, 40);
    window.localStorage.setItem(CLIENT_KEY, created);
    return created;
  } catch {
    return randomId().slice(0, 40);
  }
}

function readQueue(): AnalyticsEventIn[] {
  if (typeof window === 'undefined') return [];
  try {
    const raw = window.localStorage.getItem(QUEUE_KEY);
    const parsed = raw ? (JSON.parse(raw) as unknown) : [];
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (item): item is AnalyticsEventIn =>
        typeof item === 'object' &&
        item !== null &&
        typeof (item as AnalyticsEventIn).event === 'string' &&
        typeof (item as AnalyticsEventIn).dedupe_key === 'string',
    );
  } catch {
    return [];
  }
}

function writeQueue(items: AnalyticsEventIn[]): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(QUEUE_KEY, JSON.stringify(items.slice(-MAX_QUEUE)));
  } catch {
    // Analytics must never break reading if storage is full or unavailable.
  }
}

function scheduleFlush(): void {
  if (typeof window === 'undefined' || flushTimer !== null) return;
  flushTimer = window.setTimeout(() => {
    flushTimer = null;
    void flushAnalytics();
  }, FLUSH_DELAY_MS);
}

export function trackEvent(
  event: AnalyticsEventName,
  options: {
    surface: string;
    mangaId?: string | null;
    chapterId?: string | null;
  },
): void {
  if (optedOut()) return;
  const item: AnalyticsEventIn = {
    event,
    dedupe_key: randomId(),
    client_id: analyticsClientId(),
    surface: options.surface.slice(0, 32),
    manga_id: options.mangaId ?? null,
    chapter_id: options.chapterId ?? null,
  };
  const queue = readQueue();
  queue.push(item);
  writeQueue(queue);
  scheduleFlush();
}

export async function flushAnalytics(): Promise<void> {
  if (typeof window === 'undefined' || flushing || optedOut()) return;
  const queue = readQueue();
  if (queue.length === 0) return;
  const batch = queue.slice(0, 50);
  flushing = true;
  try {
    await api.trackEvents(batch);
    const sent = new Set(batch.map((item) => item.dedupe_key));
    writeQueue(readQueue().filter((item) => !sent.has(item.dedupe_key)));
    if (readQueue().length > 0) scheduleFlush();
  } catch {
    // Offline: keep the queue capped and retry on the next reading action or
    // page visibility change.  No user-facing error is ever shown.
  } finally {
    flushing = false;
  }
}

if (typeof window !== 'undefined') {
  window.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') void flushAnalytics();
  });
}
