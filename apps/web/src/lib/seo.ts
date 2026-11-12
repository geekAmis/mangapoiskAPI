import { useEffect } from 'react';

/**
 * Small, dependency-free SEO layer for the SPA.
 *
 * The production site is a client-rendered React app: nginx serves the same
 * index.html for every route.  Base tags in index.html describe the site,
 * while this hook updates the document head for the active route.  Google and
 * Yandex render JavaScript, so the rendered head is what they see; keeping the
 * values in one place also avoids the duplicated/missing tags the audit found.
 */

export const SEO_SITE_NAME = 'MangaPoisk Reborn';
export const SEO_DEFAULT_TITLE = 'MangaPoisk Reborn — читалка манги и манхвы онлайн';
export const SEO_DEFAULT_DESCRIPTION =
  'MangaPoisk Reborn — русский каталог манги и манхвы: поиск по источникам, удобная читалка, закладки, история чтения и офлайн-экспорт глав.';
export const SEO_DEFAULT_IMAGE = '/icons/icon-512.png';
export const SEO_DEFAULT_ROBOTS = 'index,follow,max-image-preview:large';

const MANAGED_ATTRIBUTE = 'data-seo';
const JSON_LD_SELECTOR = `script[${MANAGED_ATTRIBUTE}="json-ld"]`;

export interface SeoOptions {
  /** Document title. Omit to let the page manage it (e.g. the admin panel). */
  title?: string;
  description?: string;
  /**
   * Canonical URL as an absolute URL or a root-relative path.
   * `undefined` canonicalises the current path; `null` removes the tag.
   */
  canonical?: string | null;
  /** Defaults to index,follow,max-image-preview:large. */
  robots?: string;
  /** Absolute or root-relative social image. */
  image?: string | null;
  imageAlt?: string;
  type?: 'website' | 'article' | 'book';
  locale?: string;
  /** One JSON-LD node, an array of nodes, or a fully built @graph. */
  jsonLd?: Record<string, unknown> | Array<Record<string, unknown>> | null;
}

export function siteOrigin(): string {
  const configured = import.meta.env.VITE_SITE_URL?.trim();
  if (configured) return configured.replace(/\/+$/, '');
  if (typeof window !== 'undefined') return window.location.origin;
  return 'https://85.192.37.58.nip.io:8443';
}

export function absoluteUrl(value: string | null | undefined): string | null {
  if (!value) return null;
  const trimmed = value.trim();
  if (!trimmed) return null;
  if (/^https?:\/\//i.test(trimmed)) return trimmed;
  if (trimmed.startsWith('//')) return `https:${trimmed}`;
  return `${siteOrigin()}${trimmed.startsWith('/') ? '' : '/'}${trimmed}`;
}

/** Canonical URL for the current location without query or hash noise. */
export function currentCanonical(): string {
  if (typeof window === 'undefined') return `${siteOrigin()}/`;
  const path = window.location.pathname.replace(/\/+$/, '') || '/';
  return `${siteOrigin()}${path}`;
}

/** Collapse whitespace and clamp a text field to a search-snippet length. */
export function metaDescription(text: string | null | undefined, maxLength = 160): string {
  const compact = (text ?? '')
    .replace(/<[^>]*>/g, ' ')
    .replace(/&nbsp;/gi, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  if (!compact) return SEO_DEFAULT_DESCRIPTION;
  if (compact.length <= maxLength) return compact;
  const cut = compact.slice(0, maxLength - 1);
  const lastSpace = cut.lastIndexOf(' ');
  return `${(lastSpace > maxLength * 0.6 ? cut.slice(0, lastSpace) : cut).trimEnd()}…`;
}

export function jsonLdGraph(
  ...nodes: Array<Record<string, unknown>>
): Record<string, unknown> {
  return {
    '@context': 'https://schema.org',
    '@graph': nodes.map((node) => {
      const copy = { ...node };
      delete copy['@context'];
      return copy;
    }),
  };
}

export function buildWebSiteJsonLd(): Record<string, unknown> {
  const origin = siteOrigin();
  return {
    '@context': 'https://schema.org',
    '@type': 'WebSite',
    name: SEO_SITE_NAME,
    alternateName: 'MangaPoisk',
    url: `${origin}/`,
    description: SEO_DEFAULT_DESCRIPTION,
    inLanguage: 'ru',
    potentialAction: {
      '@type': 'SearchAction',
      target: {
        '@type': 'EntryPoint',
        urlTemplate: `${origin}/catalogue?q={search_term_string}`,
      },
      'query-input': 'required name=search_term_string',
    },
  };
}

export function buildOrganizationJsonLd(): Record<string, unknown> {
  const origin = siteOrigin();
  return {
    '@context': 'https://schema.org',
    '@type': 'Organization',
    name: SEO_SITE_NAME,
    url: `${origin}/`,
    logo: {
      '@type': 'ImageObject',
      url: absoluteUrl(SEO_DEFAULT_IMAGE),
    },
    sameAs: ['https://github.com/geekAmis/mangapoiskAPI'],
  };
}

export function buildBreadcrumbJsonLd(
  items: Array<{ name: string; url: string }>,
): Record<string, unknown> {
  return {
    '@context': 'https://schema.org',
    '@type': 'BreadcrumbList',
    itemListElement: items.map((item, index) => ({
      '@type': 'ListItem',
      position: index + 1,
      name: item.name,
      item: absoluteUrl(item.url),
    })),
  };
}

export interface ComicStoryInput {
  name: string;
  url: string;
  description?: string | null;
  image?: string | null;
  alternateNames?: Array<string | null | undefined>;
  genres?: string[];
  year?: number | null;
  adult?: boolean;
  rating?: number | null;
  ratingCount?: number | null;
  sameAs?: string | null;
  dateModified?: string | null;
}

/**
 * schema.org ComicStory for a title page.  Only real catalogue fields are
 * emitted: the project has no reliable author/publisher data, so those
 * properties are deliberately absent instead of being invented.
 */
export function buildComicStoryJsonLd(input: ComicStoryInput): Record<string, unknown> {
  const alternateNames: string[] = [];
  const seenNames = new Set([input.name.trim().toLowerCase()]);
  for (const value of input.alternateNames ?? []) {
    const name = value?.trim();
    if (!name) continue;
    const key = name.toLowerCase();
    if (seenNames.has(key)) continue;
    seenNames.add(key);
    alternateNames.push(name);
  }
  const data: Record<string, unknown> = {
    '@context': 'https://schema.org',
    '@type': 'ComicStory',
    name: input.name,
    url: input.url,
    inLanguage: 'ru',
  };

  if (input.description?.trim()) data.description = input.description.trim();
  const image = absoluteUrl(input.image);
  if (image) data.image = image;
  if (alternateNames.length > 0) data.alternateName = alternateNames;
  if (input.genres?.length) data.genre = input.genres;
  if (input.year) data.copyrightYear = input.year;
  if (typeof input.adult === 'boolean') data.isFamilyFriendly = !input.adult;
  if (input.dateModified) data.dateModified = input.dateModified;
  if (input.sameAs) data.sameAs = input.sameAs;

  if (
    typeof input.rating === 'number' &&
    input.rating > 0 &&
    typeof input.ratingCount === 'number' &&
    input.ratingCount > 0
  ) {
    data.aggregateRating = {
      '@type': 'AggregateRating',
      ratingValue: input.rating,
      ratingCount: input.ratingCount,
      bestRating: 10,
      worstRating: 1,
    };
  }

  return data;
}

function metaCleanup(
  attribute: 'name' | 'property',
  key: string,
  content: string,
  cleanups: Array<() => void>,
): void {
  const selector = `meta[${attribute}="${key}"]`;
  const existing = document.head.querySelector<HTMLMetaElement>(selector);
  const previous = existing?.getAttribute('content') ?? null;
  const element =
    existing ??
    (() => {
      const created = document.createElement('meta');
      created.setAttribute(attribute, key);
      document.head.appendChild(created);
      return created;
    })();

  element.setAttribute('content', content);

  cleanups.push(() => {
    if (existing) {
      if (previous === null) existing.removeAttribute('content');
      else existing.setAttribute('content', previous);
    } else {
      element.remove();
    }
  });
}

function linkCleanup(
  rel: string,
  href: string | null,
  cleanups: Array<() => void>,
): void {
  const selector = `link[rel="${rel}"]`;
  const existing = document.head.querySelector<HTMLLinkElement>(selector);
  const previous = existing?.getAttribute('href') ?? null;

  if (href === null) {
    if (existing) {
      existing.remove();
      cleanups.push(() => document.head.appendChild(existing));
    }
    return;
  }

  const element =
    existing ??
    (() => {
      const created = document.createElement('link');
      created.setAttribute('rel', rel);
      document.head.appendChild(created);
      return created;
    })();
  element.setAttribute('href', href);

  cleanups.push(() => {
    if (existing) {
      if (previous === null) existing.removeAttribute('href');
      else existing.setAttribute('href', previous);
    } else {
      element.remove();
    }
  });
}

function jsonLdCleanup(
  jsonLd: SeoOptions['jsonLd'],
  cleanups: Array<() => void>,
): void {
  const previousScript = document.head.querySelector<HTMLScriptElement>(JSON_LD_SELECTOR);
  const previousText = previousScript?.textContent ?? null;

  if (!jsonLd) {
    if (previousScript) {
      previousScript.remove();
      cleanups.push(() => document.head.appendChild(previousScript));
    }
    return;
  }

  const script =
    previousScript ??
    (() => {
      const created = document.createElement('script');
      created.type = 'application/ld+json';
      created.setAttribute(MANAGED_ATTRIBUTE, 'json-ld');
      document.head.appendChild(created);
      return created;
    })();
  script.textContent = JSON.stringify(jsonLd);

  cleanups.push(() => {
    if (previousScript) {
      previousScript.textContent = previousText;
    } else {
      script.remove();
    }
  });
}

/**
 * Apply route-specific metadata for as long as the calling component is
 * mounted.  Cleanup restores the previous title/meta so navigating between
 * routes cannot leave stale canonical, robots or JSON-LD behind.
 */
export function useSeo(options: SeoOptions): void {
  const signature = JSON.stringify({
    title: options.title,
    description: options.description,
    canonical: options.canonical,
    robots: options.robots,
    image: options.image,
    imageAlt: options.imageAlt,
    type: options.type,
    locale: options.locale,
    jsonLd: options.jsonLd,
  });

  useEffect(() => {
    if (typeof document === 'undefined') return;

    const cleanups: Array<() => void> = [];
    const previousTitle = document.title;
    const title = options.title?.trim();
    const description = options.description?.trim();

    if (title) document.title = title;

    if (description) {
      metaCleanup('name', 'description', description, cleanups);
    }

    metaCleanup('name', 'robots', options.robots ?? SEO_DEFAULT_ROBOTS, cleanups);

    const canonical =
      options.canonical === undefined ? currentCanonical() : absoluteUrl(options.canonical);
    linkCleanup('canonical', canonical, cleanups);

    const socialTitle = title ?? SEO_SITE_NAME;
    const socialDescription = description ?? SEO_DEFAULT_DESCRIPTION;
    const socialImage = absoluteUrl(options.image ?? SEO_DEFAULT_IMAGE);
    const socialType = options.type ?? 'website';
    const socialUrl = canonical ?? currentCanonical();

    metaCleanup('property', 'og:type', socialType, cleanups);
    metaCleanup('property', 'og:locale', options.locale ?? 'ru_RU', cleanups);
    metaCleanup('property', 'og:site_name', SEO_SITE_NAME, cleanups);
    metaCleanup('property', 'og:title', socialTitle, cleanups);
    metaCleanup('property', 'og:description', socialDescription, cleanups);
    metaCleanup('property', 'og:url', socialUrl, cleanups);
    if (socialImage) metaCleanup('property', 'og:image', socialImage, cleanups);
    if (options.imageAlt) metaCleanup('property', 'og:image:alt', options.imageAlt, cleanups);

    metaCleanup('name', 'twitter:card', 'summary_large_image', cleanups);
    metaCleanup('name', 'twitter:title', socialTitle, cleanups);
    metaCleanup('name', 'twitter:description', socialDescription, cleanups);
    if (socialImage) metaCleanup('name', 'twitter:image', socialImage, cleanups);
    if (options.imageAlt) metaCleanup('name', 'twitter:image:alt', options.imageAlt, cleanups);

    jsonLdCleanup(options.jsonLd, cleanups);

    return () => {
      for (const cleanup of cleanups.reverse()) cleanup();
      if (title) document.title = previousTitle;
    };
  }, [signature]); // eslint-disable-line react-hooks/exhaustive-deps
}
