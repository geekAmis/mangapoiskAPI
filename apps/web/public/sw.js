/* eslint-env serviceworker */
/**
 * MangaPoisk Reborn — offline app shell.
 *
 * Bump CACHE_VERSION whenever the shell strategy or the precache list changes.
 * Versioned caches make sure a new deploy never mixes old HTML with new hashed
 * assets; obsolete caches are deleted on activate.
 *
 * Same-origin API traffic is intentionally not intercepted: offline library
 * data lives in IndexedDB, while API requests stay network-only.
 */

const CACHE_VERSION = 'v4-2026-11-12';
const CACHE_PREFIX = 'mangapoisk-';
const SHELL_CACHE = `${CACHE_PREFIX}shell-${CACHE_VERSION}`;
const RUNTIME_CACHE = `${CACHE_PREFIX}runtime-${CACHE_VERSION}`;

const INDEX_URL = '/index.html';
const ROOT_URL = '/';

const LOADING_GIFS = Array.from(
  { length: 16 },
  (_, index) => `/loading/dance-${String(index + 1).padStart(2, '0')}.gif`,
);
const BOOT_GIFS = Array.from(
  { length: 16 },
  (_, index) => `/loading/boot-${String(index + 1).padStart(2, '0')}.gif`,
);

const PRECACHE_URLS = [
  ROOT_URL,
  INDEX_URL,
  '/manifest.webmanifest',
  '/robots.txt',
  '/icons/favicon.svg',
  '/icons/apple-touch-icon.png',
  '/icons/icon-192.png',
  '/icons/icon-512.png',
  '/icons/poster-fallback.svg',
  ...LOADING_GIFS,
  ...BOOT_GIFS,
];

const STATIC_PREFIXES = ['/assets/', '/icons/', '/loading/', '/themes/'];
const STATIC_FILES = new Set(['/manifest.webmanifest', '/robots.txt']);
const API_PREFIX = '/api';

function isApiRequest(url) {
  return url.pathname === API_PREFIX || url.pathname.startsWith(`${API_PREFIX}/`);
}

function isStaticAsset(url) {
  return (
    STATIC_FILES.has(url.pathname) ||
    STATIC_PREFIXES.some((prefix) => url.pathname.startsWith(prefix))
  );
}

function isCacheable(response) {
  return Boolean(response && response.ok && response.type === 'basic');
}

async function fetchAndStore(cache, url) {
  try {
    const response = await fetch(url, { cache: 'reload' });
    if (isCacheable(response)) {
      await cache.put(url, response.clone());
      return response;
    }
    return null;
  } catch {
    return null;
  }
}

/**
 * Precache the current HTML and every hashed asset referenced by it.
 * URLs are parsed from the built index.html, so a fresh deployment always
 * gets its own JS/CSS in the versioned shell cache.
 */
async function precacheShell() {
  const cache = await caches.open(SHELL_CACHE);

  await Promise.all(
    PRECACHE_URLS.filter((url) => url !== INDEX_URL).map((url) => fetchAndStore(cache, url)),
  );

  const indexResponse = await fetchAndStore(cache, INDEX_URL);
  if (!indexResponse) return;

  let html = '';
  try {
    html = await indexResponse.text();
  } catch {
    return;
  }

  const assetUrls = new Set();
  const matcher = /(?:src|href)="(\/assets\/[^"?#]+)"/g;
  let match = matcher.exec(html);
  while (match) {
    if (match[1]) assetUrls.add(match[1]);
    match = matcher.exec(html);
  }

  await Promise.all([...assetUrls].map((url) => fetchAndStore(cache, url)));

  // The entry bundle contains the filenames of lazy route chunks (and their
  // CSS) as relative imports/dependency maps. Walk those references too so a
  // cold offline deep link such as /offline/read/... does not miss its chunk.
  const known = new Set(assetUrls);
  const scanned = new Set();
  const queue = [...known].filter((url) => url.endsWith('.js'));

  while (queue.length > 0) {
    const url = queue.shift();
    if (!url || scanned.has(url)) continue;
    scanned.add(url);

    let response = await cache.match(url);
    if (!response) response = await fetchAndStore(cache, url);
    if (!response) continue;

    let source = '';
    try {
      source = await response.text();
    } catch {
      continue;
    }

    const chunkMatcher = /(?:assets\/|\.\/)([A-Za-z0-9_-]+\.(?:js|css))/g;
    let chunk = chunkMatcher.exec(source);
    while (chunk) {
      const chunkUrl = `/assets/${chunk[1]}`;
      if (!known.has(chunkUrl)) {
        known.add(chunkUrl);
        const stored = await fetchAndStore(cache, chunkUrl);
        if (stored && chunkUrl.endsWith('.js')) queue.push(chunkUrl);
      }
      chunk = chunkMatcher.exec(source);
    }
  }
}

self.addEventListener('install', (event) => {
  event.waitUntil(
    precacheShell()
      .catch(() => {
        /* A partial cache is still useful; the next online visit fills gaps. */
      })
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(
        keys
          .filter(
            (key) =>
              key.startsWith(CACHE_PREFIX) && key !== SHELL_CACHE && key !== RUNTIME_CACHE,
          )
          .map((key) => caches.delete(key)),
      );
      await self.clients.claim();
    })(),
  );
});

async function handleNavigation(event) {
  const cache = await caches.open(SHELL_CACHE);
  try {
    const response = await fetch(event.request);
    if (isCacheable(response)) {
      const contentType = response.headers.get('content-type') ?? '';
      if (contentType.includes('text/html')) {
        await cache.put(INDEX_URL, response.clone());
      }
    }
    return response;
  } catch {
    const fallback =
      (await cache.match(INDEX_URL)) ?? (await cache.match(ROOT_URL));
    if (fallback) return fallback;

    return new Response(
      '<!doctype html><html lang="ru"><meta charset="utf-8"><title>Нет сети</title>' +
        '<body style="background:#060b12;color:#edf4fc;font:16px system-ui;padding:32px">' +
        '<h1>Нет подключения</h1><p>Откройте приложение хотя бы раз онлайн, чтобы сохранить оболочку для офлайн-чтения.</p>',
      {
        status: 503,
        headers: { 'Content-Type': 'text/html; charset=utf-8' },
      },
    );
  }
}

async function cacheFirst(request) {
  const cache = await caches.open(RUNTIME_CACHE);
  const cached = await cache.match(request);
  if (cached) return cached;

  try {
    const response = await fetch(request);
    if (isCacheable(response)) await cache.put(request, response.clone());
    return response;
  } catch {
    return Response.error();
  }
}

async function staleWhileRevalidate(request) {
  const cache = await caches.open(RUNTIME_CACHE);
  const cached = await cache.match(request);

  const network = fetch(request)
    .then(async (response) => {
      if (isCacheable(response)) await cache.put(request, response.clone());
      return response;
    })
    .catch(() => null);

  if (cached) return cached;
  return (await network) ?? Response.error();
}

self.addEventListener('fetch', (event) => {
  const { request } = event;

  if (request.method !== 'GET') return;

  let url;
  try {
    url = new URL(request.url);
  } catch {
    return;
  }

  if (url.origin !== self.location.origin) return;
  if (isApiRequest(url)) return;

  if (request.mode === 'navigate') {
    event.respondWith(handleNavigation(event));
    return;
  }

  if (!isStaticAsset(url)) return;

  // Hashed build files are immutable; everything else may change independently.
  if (url.pathname.startsWith('/assets/')) {
    event.respondWith(cacheFirst(request));
  } else {
    event.respondWith(staleWhileRevalidate(request));
  }
});

self.addEventListener('message', (event) => {
  if (event.data === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});
