import { useEffect } from 'react';
import { useSeo } from '../lib/seo';

/**
 * The admin panel is lazily loaded and manages its own title and its own
 * noindex tag.  This wrapper removes the base indexable canonical/robots and
 * keeps exactly one robots tag, without touching AdminPage.tsx.
 */
export function AdminSeo() {
  useSeo({ canonical: null, robots: 'noindex,nofollow' });

  useEffect(() => {
    const dedupe = () => {
      const tags = document.head.querySelectorAll('meta[name="robots"]');
      for (const tag of Array.from(tags).slice(1)) tag.remove();
    };
    dedupe();
    const observer = new MutationObserver(dedupe);
    observer.observe(document.head, { childList: true });
    return () => observer.disconnect();
  }, []);

  return null;
}
