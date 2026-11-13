/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE?: string;
  /** Canonical public origin, e.g. https://85.192.37.58.nip.io */
  readonly VITE_SITE_URL?: string;
  /** Optional Vite alias for the build-time Yandex Metrika counter id. */
  readonly VITE_YANDEX_METRIKA_ID?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

interface YandexAdRenderOptions {
  blockId: string;
  renderTo: string;
}

interface YandexAdsManager {
  render(options: YandexAdRenderOptions): void;
}

interface YandexContext {
  AdvManager: YandexAdsManager;
}

interface Window {
  /** Queue populated by index.html before the Yandex RTB SDK loads. */
  yaContextCb?: Array<() => void>;
  /** Available only after https://yandex.ru/ads/system/context.js loads. */
  Ya?: {
    Context?: YandexContext;
  };
  /** Yandex Metrika queue/function, created by TrafficTracker when enabled. */
  ym?: ((...args: unknown[]) => void) & { a?: unknown[][]; l?: number };
}

/**
 * Legal contact details are replaced at build time by vite.config.ts.
 * They intentionally do not use the VITE_ prefix so deployment can pass the
 * documented LEGAL_CONTACT_EMAIL / LEGAL_OWNER_NAME / LEGAL_JURISDICTION names.
 */
declare const __LEGAL_CONTACT_EMAIL__: string;
declare const __LEGAL_OWNER_NAME__: string;
declare const __LEGAL_JURISDICTION__: string;

/**
 * Build-time Yandex Metrika counter id (YANDEX_METRIKA_ID or
 * VITE_YANDEX_METRIKA_ID).  Empty disables the loader entirely.
 */
declare const __YANDEX_METRIKA_ID__: string;
