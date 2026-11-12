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

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '');
  return {
    plugins: [react(), seoVerificationPlugin(env)],
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
