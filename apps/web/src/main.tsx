import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import { ErrorBoundary } from './components/ErrorBoundary';
import { ToastHost } from './components/Toast';
import { ScrollToTop } from './lib/ScrollToTop';
import { SettingsBridge } from './lib/SettingsBridge';
import { ThemeEffects } from './lib/ThemeEffects';
import { queryClient } from './lib/queryClient';
import './styles/themes.css';
import './styles/base.css';
import './styles/components.css';
import './styles/layout.css';
import './styles/pages.css';
import './styles/legal.css';
import './styles/reader.css';

const rootElement = document.getElementById('root');
if (!rootElement) throw new Error('Не найден корневой элемент #root');

createRoot(rootElement).render(
  <StrictMode>
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <ThemeEffects />
          <SettingsBridge />
          <ScrollToTop />
          <App />
          <ToastHost />
        </BrowserRouter>
      </QueryClientProvider>
    </ErrorBoundary>
  </StrictMode>,
);

// The inline dancer in index.html is visible before the JS bundle arrives.
// Remove it only after React has painted its first frame.
const bootLoader = document.getElementById('boot-loader');
if (bootLoader) {
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      bootLoader.classList.add('is-done');
      window.setTimeout(() => bootLoader.remove(), 260);
    });
  });
}

/**
 * The service worker is production-only: Vite's dev server must never be
 * shadowed by a stale app shell. Registration is deliberately deferred until
 * the page has loaded so it cannot compete with the first render.
 *
 * The worker calls skipWaiting()/clients.claim() and drops caches from older
 * versions on activate. We do not force a reload when a new worker takes
 * control: an open chapter must not jump while the reader is in use.
 */
if (import.meta.env.PROD && 'serviceWorker' in navigator) {
  const registerServiceWorker = () => {
    void navigator.serviceWorker
      .register('/sw.js', { scope: '/' })
      .then((registration) => {
        // Check for updates on every launch and when the tab becomes visible,
        // without altering the page that is currently reading.
        void registration.update().catch(() => undefined);
        document.addEventListener('visibilitychange', () => {
          if (document.visibilityState === 'visible') {
            void registration.update().catch(() => undefined);
          }
        });
      })
      .catch((error: unknown) => {
        // Offline reading still works in the current session; only cold
        // offline starts depend on the worker.
        console.warn('[service-worker] registration failed', error);
      });
  };

  if (document.readyState === 'complete') {
    registerServiceWorker();
  } else {
    window.addEventListener('load', registerServiceWorker, { once: true });
  }
}
