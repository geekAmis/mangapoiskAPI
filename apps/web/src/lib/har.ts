/**
 * Browser-side HAR cookie extraction.
 *
 * HAR files with full media traffic are routinely 100+ MB, so the admin UI
 * parses them locally and sends only the resulting Cookie header to the
 * gateway. The server keeps the same extraction for API clients that upload
 * smaller files.
 */

const SOURCE_HOSTS: Record<string, string[]> = {
  remanga: ['remanga.org'],
  mangalib: ['mangalib.me', 'mangalib.org'],
  mangapoisk: ['mangapoisk.me', 'mangapoisk.org', 'mangapoisk.ru'],
  mangadex: ['mangadex.org'],
  readmanga: ['readmanga.live'],
};

interface HarEntry {
  request?: {
    url?: unknown;
    headers?: Array<{ name?: unknown; value?: unknown }>;
  };
}

function hostMatches(host: string, candidates: string[]): boolean {
  return candidates.some((item) => host === item || host.endsWith(`.${item}`));
}

export type HarCookieResult =
  | { status: 'found'; cookie: string }
  | { status: 'no-cookie' }
  | { status: 'invalid-har' };

export function extractHarCookie(text: string, sourceCode: string): HarCookieResult {
  let payload: unknown;
  try {
    payload = JSON.parse(text);
  } catch {
    return { status: 'invalid-har' };
  }
  if (!payload || typeof payload !== 'object') return { status: 'invalid-har' };
  const log = (payload as { log?: unknown }).log;
  if (!log || typeof log !== 'object') return { status: 'invalid-har' };
  const entries = (log as { entries?: unknown }).entries;
  if (!Array.isArray(entries)) return { status: 'invalid-har' };

  const hosts = SOURCE_HOSTS[sourceCode] ?? [];
  const candidates: string[] = [];
  const sourceHits: string[] = [];

  for (const entry of entries as HarEntry[]) {
    const request = entry?.request;
    if (!request) continue;
    const url = typeof request.url === 'string' ? request.url : '';
    let host = '';
    try {
      host = new URL(url).hostname.toLowerCase();
    } catch {
      host = '';
    }
    let cookie = '';
    if (Array.isArray(request.headers)) {
      for (const header of request.headers) {
        if (
          typeof header?.name === 'string' &&
          header.name.toLowerCase() === 'cookie' &&
          typeof header.value === 'string' &&
          header.value.trim()
        ) {
          cookie = header.value.trim();
          break;
        }
      }
    }
    if (!cookie) continue;
    candidates.push(cookie);
    if (hosts.length > 0 && hostMatches(host, hosts)) sourceHits.push(cookie);
  }

  if (hosts.length > 0) {
    if (sourceHits.length === 0) return { status: 'no-cookie' };
    candidates.length = 0;
    candidates.push(...sourceHits);
  }
  if (candidates.length === 0) return { status: 'no-cookie' };
  if (sourceCode === 'remanga') {
    const preferred = candidates.filter((item) => item.includes('auth:token'));
    if (preferred.length > 0) {
      return {
        status: 'found',
        cookie: preferred.reduce((left, right) => (right.length > left.length ? right : left)),
      };
    }
  }
  return {
    status: 'found',
    cookie: candidates.reduce((left, right) => (right.length > left.length ? right : left)),
  };
}
