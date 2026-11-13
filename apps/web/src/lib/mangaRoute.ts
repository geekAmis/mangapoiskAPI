/**
 * Public manga URLs are `/manga/{uuid}-{slug}`.  The UUID is the only routing
 * key; the slug is cosmetic and may be stale or missing.  React Router exposes
 * the whole segment as one param, so parse the UUID explicitly instead of
 * splitting on the first hyphen (UUIDs contain hyphens too).
 */

const UUID_RE =
  /^([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(?:-([a-z0-9-]*))?$/i;

export interface MangaRouteParam {
  id: string;
  slug: string | null;
}

export function parseMangaRouteParam(value: string): MangaRouteParam {
  const match = UUID_RE.exec((value || '').trim());
  if (!match) return { id: value, slug: null };
  return { id: match[1], slug: match[2] || null };
}

export interface MangaPathSource {
  id: string;
  url_slug?: string | null;
}

/** Canonical public path for a title, using the cosmetic slug when present. */
export function mangaPath(manga: MangaPathSource): string {
  const slug = manga.url_slug?.trim();
  return slug ? `/manga/${manga.id}-${slug}` : `/manga/${manga.id}`;
}

/** Fallback when only an id is available (notifications, admin links). */
export function mangaPathFromId(id: string): string {
  return `/manga/${id}`;
}
