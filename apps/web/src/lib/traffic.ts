/**
 * Internal privacy-friendly page-view beacon (#85).
 *
 * Unlike Yandex Metrika, this beacon is first-party and stores no raw IP or
 * user agent.  The server HMACs the random device id and deduplicates it per
 * UTC day, so the admin dashboard can show unique visitors without PII.
 *
 * Private areas (/admin, reader, library, login) are never sent.  DNT and
 * Global Privacy Control are honoured in the same way as product analytics.
 */

import { API_BASE } from '../api/client';
import { analyticsClientId, analyticsOptedOut } from './analytics';

export type TrafficPathGroup =
  | 'home'
  | 'catalogue'
  | 'manga'
  | 'collection'
  | 'sources'
  | 'legal'
  | 'profile'
  | 'other';

const PRIVATE_PREFIXES = [
  '/admin',
  '/read/',
  '/reader/',
  '/offline/',
  '/library',
  '/profile',
  '/login',
  '/register',
  '/auth/',
];

const LEGAL_PATHS = new Set(['/terms', '/privacy', '/dmca', '/contacts', '/age']);

/** Coarse public section, or null when the route must not be tracked. */
export function trafficPathGroup(pathname: string): TrafficPathGroup | null {
  const path = (pathname.split(/[?#]/, 1)[0] || '/').replace(/\/+$/, '') || '/';
  if (PRIVATE_PREFIXES.some((prefix) => path === prefix || path.startsWith(prefix))) {
    return null;
  }
  if (path === '/') return 'home';
  if (path === '/catalog' || path.startsWith('/catalog/') || path === '/catalogue') {
    return 'catalogue';
  }
  if (path.startsWith('/manga/')) return 'manga';
  if (path.startsWith('/collections/')) return 'collection';
  if (path === '/sources') return 'sources';
  if (LEGAL_PATHS.has(path)) return 'legal';
  if (path.startsWith('/u/')) return 'profile';
  return 'other';
}

/**
 * Send one beacon for a public page view.
 *
 * Several calls from the same browser on the same day are expected; the
 * server's unique (visitor_hash, day) constraint makes them idempotent.
 */
export function recordTrafficVisit(pathname: string): boolean {
  const pathGroup = trafficPathGroup(pathname);
  if (pathGroup === null || analyticsOptedOut()) return false;

  const payload = JSON.stringify({
    visitor_id: analyticsClientId(),
    path_group: pathGroup,
  });
  const endpoint = `${API_BASE}/traffic/visit`;

  try {
    if (typeof navigator !== 'undefined' && typeof navigator.sendBeacon === 'function') {
      const blob = new Blob([payload], { type: 'application/json' });
      if (navigator.sendBeacon(endpoint, blob)) return true;
    }
  } catch {
    // Fall through to fetch; a blocked beacon must never break navigation.
  }

  void fetch(endpoint, {
    method: 'POST',
    body: payload,
    headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin',
    keepalive: true,
  }).catch(() => undefined);
  return true;
}
