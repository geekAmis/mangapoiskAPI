import { defineConfig, loadEnv, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';

function escapeAttribute(value: string): string {
  return value.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
}

/**
 * Inject Search Console / Yandex Webmaster verification tags at build time.
 * Both the plain names from issue #38 and Vite-prefixed aliases are accepted;
 * an empty value omits the tag instead of emitting `content=""`.
 */
function seoVerificationPlugin(env: Record<string, string>): Plugin {
  return {
    name: 'seo-verification',
    transformIndexHtml(html) {
      const tags: Array<{ tag: string; attrs: Record<string, string>; injectTo: 'head' }> = [];
      const google = (
        env.GOOGLE_SITE_VERIFICATION ??
        env.VITE_GOOGLE_SITE_VERIFICATION ??
        ''
      ).trim();
      const yandex = (env.YANDEX_VERIFICATION ?? env.VITE_YANDEX_VERIFICATION ?? '').trim();
      if (google) {
        tags.push({
          tag: 'meta',
          attrs: {
            name: 'google-site-verification',
            content: escapeAttribute(google),
          },
          injectTo: 'head',
        });
      }
      if (yandex) {
        tags.push({
          tag: 'meta',
          attrs: { name: 'yandex-verification', content: escapeAttribute(yandex) },
          injectTo: 'head',
        });
      }
      return { html, tags };
    },
  };
}

const LEGACY_PUBLIC_ORIGIN = 'https://85.192.37.58.nip.io:8443';

/**
 * Keep static canonical/OG/icon URLs in index.html aligned with the build's
 * configured public origin.  The gateway also prerenders crawler HTML, but
 * the SPA shell itself must not leak the legacy port to humans or link bots.
 */
function publicOriginPlugin(siteUrl: string): Plugin {
  return {
    name: 'public-origin',
    transformIndexHtml(html) {
      const target = siteUrl.trim().replace(/\/+$/, '');
      return target ? html.replaceAll(LEGACY_PUBLIC_ORIGIN, target) : html;
    },
  };
}

export default defineConfig(({ mode }) => {
  // Legal details are build-time values.  Accept the documented
  // LEGAL_* names as well as VITE_LEGAL_* aliases for local development.
  const env = loadEnv(mode, process.cwd(), '');
  const legalContactEmail =
    process.env.LEGAL_CONTACT_EMAIL ??
    env.LEGAL_CONTACT_EMAIL ??
    env.VITE_LEGAL_CONTACT_EMAIL ??
    '';
  const legalOwnerName =
    process.env.LEGAL_OWNER_NAME ??
    env.LEGAL_OWNER_NAME ??
    env.VITE_LEGAL_OWNER_NAME ??
    '';
  const legalJurisdiction =
    process.env.LEGAL_JURISDICTION ??
    env.LEGAL_JURISDICTION ??
    env.VITE_LEGAL_JURISDICTION ??
    '';
  const siteUrl = (
    process.env.VITE_SITE_URL ??
    env.VITE_SITE_URL ??
    ''
  ).trim();

  return {
    plugins: [react(), seoVerificationPlugin(env), ...(siteUrl ? [publicOriginPlugin(siteUrl)] : [])],
    define: {
      __LEGAL_CONTACT_EMAIL__: JSON.stringify(legalContactEmail),
      __LEGAL_OWNER_NAME__: JSON.stringify(legalOwnerName),
      __LEGAL_JURISDICTION__: JSON.stringify(legalJurisdiction),
      __SITE_URL__: JSON.stringify(siteUrl),
    },
    server: {
      port: 5173,
      proxy: {
        '/api': {
          target: 'http://localhost:8000',
          changeOrigin: true,
        },
      },
    },
    preview: {
      port: 4173,
      proxy: {
        '/api': {
          target: 'http://localhost:8000',
          changeOrigin: true,
        },
      },
    },
    build: {
      outDir: 'dist',
      sourcemap: false,
      chunkSizeWarningLimit: 900,
    },
  };
});
