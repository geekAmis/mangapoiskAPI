import { buildLegalWebPageJsonLd, type LegalPageDefinition } from './legal';
import { useSeo } from './seo';

/**
 * Shared SEO setup for legal routes: a self-canonical, an indexable WebPage
 * node and the route-specific description.
 */
export function useLegalSeo(
  page: LegalPageDefinition,
  description: string,
  robots = 'index,follow',
): void {
  useSeo({
    title: `${page.title} — MangaPoisk Reborn`,
    description,
    canonical: page.path,
    robots,
    jsonLd: buildLegalWebPageJsonLd({
      title: page.title,
      description,
      path: page.path,
    }),
  });
}
