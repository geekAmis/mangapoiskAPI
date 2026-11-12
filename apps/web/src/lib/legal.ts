import { absoluteUrl, SEO_SITE_NAME, siteOrigin } from './seo';

/**
 * Legal contact details are baked into the web bundle at build time.
 *
 * The production deployment passes the non-VITE-prefixed variables
 * LEGAL_CONTACT_EMAIL / LEGAL_OWNER_NAME / LEGAL_JURISDICTION to the Docker
 * build (see apps/web/Dockerfile and docker-compose.yml).  When they are not
 * set we deliberately render an explicit placeholder instead of inventing an
 * address or an owner name.
 */
declare const __LEGAL_CONTACT_EMAIL__: string;
declare const __LEGAL_OWNER_NAME__: string;
declare const __LEGAL_JURISDICTION__: string;

export const LEGAL_UPDATED = '2026-11-13';
export const LEGAL_UPDATED_LABEL = '13 ноября 2026';

export interface LegalConfig {
  contactEmail: string | null;
  ownerName: string | null;
  jurisdiction: string | null;
}

function clean(value: string | null | undefined): string | null {
  const trimmed = (value ?? '').trim();
  return trimmed ? trimmed : null;
}

export function legalConfigFromValues(values: {
  contactEmail?: string | null;
  ownerName?: string | null;
  jurisdiction?: string | null;
}): LegalConfig {
  return {
    contactEmail: clean(values.contactEmail),
    ownerName: clean(values.ownerName),
    jurisdiction: clean(values.jurisdiction),
  };
}

export const LEGAL_CONFIG = legalConfigFromValues({
  contactEmail: typeof __LEGAL_CONTACT_EMAIL__ === 'string' ? __LEGAL_CONTACT_EMAIL__ : '',
  ownerName: typeof __LEGAL_OWNER_NAME__ === 'string' ? __LEGAL_OWNER_NAME__ : '',
  jurisdiction: typeof __LEGAL_JURISDICTION__ === 'string' ? __LEGAL_JURISDICTION__ : '',
});

export interface LegalDisplayValue {
  text: string;
  isPlaceholder: boolean;
}

/**
 * Empty env values become a visible, unambiguous placeholder.  The env key is
 * part of the text so an operator cannot mistake the placeholder for a real
 * contact.
 */
export function legalDisplayValue(value: string | null, envKey: string): LegalDisplayValue {
  if (value) return { text: value, isPlaceholder: false };
  return {
    text: `Не указано — заполните ${envKey} перед запуском`,
    isPlaceholder: true,
  };
}

export function isValidContactEmail(value: string | null): boolean {
  return Boolean(value && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value));
}

export interface LegalPageDefinition {
  path: string;
  label: string;
  shortLabel: string;
  title: string;
}

export const LEGAL_PAGES: LegalPageDefinition[] = [
  {
    path: '/terms',
    label: 'Пользовательское соглашение',
    shortLabel: 'Соглашение',
    title: 'Пользовательское соглашение',
  },
  {
    path: '/privacy',
    label: 'Политика конфиденциальности',
    shortLabel: 'Конфиденциальность',
    title: 'Политика конфиденциальности',
  },
  {
    path: '/dmca',
    label: 'Правообладателям / DMCA',
    shortLabel: 'Правообладателям',
    title: 'Правообладателям и DMCA',
  },
  {
    path: '/contacts',
    label: 'Контакты и реквизиты',
    shortLabel: 'Контакты',
    title: 'Контакты и реквизиты',
  },
  {
    path: '/age',
    label: 'Возрастное ограничение 18+',
    shortLabel: '18+',
    title: 'Возрастное ограничение 18+',
  },
];

export function legalPage(path: string): LegalPageDefinition {
  const found = LEGAL_PAGES.find((page) => page.path === path);
  if (!found) throw new Error(`Unknown legal page: ${path}`);
  return found;
}

/**
 * schema.org WebPage for a legal document.  Only fields the project can
 * actually substantiate are emitted; no fake organisation or address data.
 */
export function buildLegalWebPageJsonLd(input: {
  title: string;
  description: string;
  path: string;
}): Record<string, unknown> {
  const data: Record<string, unknown> = {
    '@context': 'https://schema.org',
    '@type': 'WebPage',
    name: input.title,
    description: input.description,
    url: absoluteUrl(input.path),
    inLanguage: 'ru',
    dateModified: LEGAL_UPDATED,
    isPartOf: {
      '@type': 'WebSite',
      name: SEO_SITE_NAME,
      url: `${siteOrigin()}/`,
    },
  };

  if (LEGAL_CONFIG.ownerName) {
    data.publisher = {
      '@type': 'Organization',
      name: LEGAL_CONFIG.ownerName,
    };
  }

  return data;
}
