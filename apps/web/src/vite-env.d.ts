/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE?: string;
  /** Canonical public origin, e.g. https://85.192.37.58.nip.io */
  readonly VITE_SITE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

/**
 * Legal contact details are replaced at build time by vite.config.ts.
 * They intentionally do not use the VITE_ prefix so deployment can pass the
 * documented LEGAL_CONTACT_EMAIL / LEGAL_OWNER_NAME / LEGAL_JURISDICTION names.
 */
declare const __LEGAL_CONTACT_EMAIL__: string;
declare const __LEGAL_OWNER_NAME__: string;
declare const __LEGAL_JURISDICTION__: string;
