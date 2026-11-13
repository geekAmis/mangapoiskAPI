/**
 * Yandex Metrika loader for the SPA (#85).
 *
 * The counter id is a build-time value (YANDEX_METRIKA_ID or
 * VITE_YANDEX_METRIKA_ID, see vite.config.ts).  Nothing is emitted when the
 * id is empty or not numeric.  The loader is injected once; SPA route changes
 * send an explicit `hit` with `defer: true` on init so the first page is never
 * counted twice.
 *
 * Privacy: only the pathname (no query string / fragment) and a coarse
 * `page_group` custom parameter are sent.  Webvisor (session replay) is off
 * and account identifiers are never passed.
 */

type YandexMetrikaFunction = ((...args: unknown[]) => void) & {
  a?: unknown[][];
  l?: number;
};

type MetrikaWindow = Window & { ym?: YandexMetrikaFunction };

const SCRIPT_ATTRIBUTE = 'data-yandex-metrika';

let installedCounter: string | null = null;

export function metrikaCounterId(raw?: string | null): string | null {
  const fromEnv =
    typeof __YANDEX_METRIKA_ID__ === 'string' ? __YANDEX_METRIKA_ID__ : '';
  const value = (raw === undefined ? fromEnv : (raw ?? '')).trim();
  return /^\d{4,12}$/.test(value) ? value : null;
}

function ensureYm(win: MetrikaWindow): YandexMetrikaFunction {
  if (win.ym) return win.ym;
  const queue: unknown[][] = [];
  const ym = ((...args: unknown[]) => {
    queue.push(args);
  }) as YandexMetrikaFunction;
  ym.a = queue;
  ym.l = Date.now();
  win.ym = ym;
  return ym;
}

/** Inject tag.js and initialise the counter; safe to call on every route. */
export function installMetrika(
  counterId: string | null | undefined,
  doc: Document = document,
  win: MetrikaWindow = window as MetrikaWindow,
): boolean {
  const id = metrikaCounterId(counterId);
  if (!id) return false;
  if (installedCounter === id && doc.querySelector(`script[${SCRIPT_ATTRIBUTE}]`)) {
    return false;
  }
  if (doc.querySelector(`script[${SCRIPT_ATTRIBUTE}]`)) return false;

  const ym = ensureYm(win);
  const script = doc.createElement('script');
  script.async = true;
  script.src = 'https://mc.yandex.ru/metrika/tag.js';
  script.setAttribute(SCRIPT_ATTRIBUTE, id);
  doc.head.appendChild(script);

  ym(id, 'init', {
    defer: true,
    clickmap: true,
    trackLinks: true,
    accurateTrackBounce: true,
    webvisor: false,
    trackHash: false,
  });
  installedCounter = id;
  return true;
}

function cleanPath(pathname: string): string {
  const withoutQuery = pathname.split(/[?#]/, 1)[0] || '/';
  return withoutQuery.startsWith('/') ? withoutQuery : `/${withoutQuery}`;
}

/** Send one SPA page view.  URL query strings and fragments are stripped. */
export function metrikaHit(
  counterId: string | null | undefined,
  pathname: string,
  pageGroup?: string | null,
  win: MetrikaWindow = window as MetrikaWindow,
): boolean {
  const id = metrikaCounterId(counterId);
  if (!id) return false;
  const ym = ensureYm(win);
  const options: Record<string, unknown> = {
    title: typeof document !== 'undefined' ? document.title : undefined,
  };
  if (pageGroup) options.params = { page_group: pageGroup };
  ym(id, 'hit', cleanPath(pathname), options);
  return true;
}

/** Test hook: forget the in-process installation marker. */
export function resetMetrikaForTests(): void {
  installedCounter = null;
}
