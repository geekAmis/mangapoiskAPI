import { useSyncExternalStore } from 'react';

/**
 * A local, self-declared 18+ confirmation.
 *
 * This is intentionally not an identity check and is never sent to the server:
 * it only stores the reader's choice in this browser.  The /age page explains
 * that limitation and lets the reader revoke the confirmation.
 */
export const AGE_CONFIRMATION_KEY = 'mp-age-confirmed';
export const AGE_CONFIRMATION_EVENT = 'mp-age-confirmed-change';

export function hasAgeConfirmation(): boolean {
  try {
    return localStorage.getItem(AGE_CONFIRMATION_KEY) === '1';
  } catch {
    return false;
  }
}

export function setAgeConfirmation(confirmed: boolean): void {
  try {
    if (confirmed) localStorage.setItem(AGE_CONFIRMATION_KEY, '1');
    else localStorage.removeItem(AGE_CONFIRMATION_KEY);
  } catch {
    /* приватный режим: подтверждение живёт только до перезагрузки */
  }
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new Event(AGE_CONFIRMATION_EVENT));
  }
}

export function subscribeAgeConfirmation(listener: () => void): () => void {
  if (typeof window === 'undefined') return () => undefined;
  const onChange = () => listener();
  window.addEventListener(AGE_CONFIRMATION_EVENT, onChange);
  window.addEventListener('storage', onChange);
  return () => {
    window.removeEventListener(AGE_CONFIRMATION_EVENT, onChange);
    window.removeEventListener('storage', onChange);
  };
}

export function useAgeConfirmation(): boolean {
  return useSyncExternalStore(
    subscribeAgeConfirmation,
    hasAgeConfirmation,
    () => false,
  );
}
