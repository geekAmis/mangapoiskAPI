import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

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

  return {
    plugins: [react()],
    define: {
      __LEGAL_CONTACT_EMAIL__: JSON.stringify(legalContactEmail),
      __LEGAL_OWNER_NAME__: JSON.stringify(legalOwnerName),
      __LEGAL_JURISDICTION__: JSON.stringify(legalJurisdiction),
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
