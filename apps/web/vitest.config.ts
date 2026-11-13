import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  define: {
    __LEGAL_CONTACT_EMAIL__: JSON.stringify(''),
    __LEGAL_OWNER_NAME__: JSON.stringify(''),
    __LEGAL_JURISDICTION__: JSON.stringify(''),
    __YANDEX_METRIKA_ID__: JSON.stringify(''),
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './tests/setup.ts',
    include: ['tests/**/*.test.{ts,tsx}'],
    css: false,
  },
});
