import { useSyncExternalStore } from 'react';
import { API_BASE } from './client';
import { useAuthStore } from '../stores/auth';

export type AdPlacement =
  | 'header'
  | 'sidebar'
  | 'in-feed'
  | 'post-chapter'
  | 'mobile-sticky';

export type AdProviderType =
  | 'yandex'
  | 'adfox'
  | 'google'
  | 'custom_html'
  | 'custom_script';

export type AdAudience = 'guest' | 'authenticated' | 'both';

export interface AdSlotConfig {
  id: string;
  name: string;
  type: AdProviderType;
  placement: AdPlacement;
  priority: number;
  audience: AdAudience;
  frequency_cap: number;
  format: string;
  width: number | null;
  height: number | null;
  content: string;
  content_type: 'html' | 'script' | 'none';
  require_consent: boolean;
}

export const ADS_CONSENT_KEY = 'mp-ads-consent';
export const ADS_CONSENT_EVENT = 'mp-ads-consent-change';
export const ADS_CONSENT_OPEN_EVENT = 'mp-ads-consent-open';

export type AdsConsent = 'granted' | 'denied' | null;

export function getAdsConsent(): AdsConsent {
  try {
    const value = localStorage.getItem(ADS_CONSENT_KEY);
    return value === 'granted' || value === 'denied' ? value : null;
  } catch {
    return null;
  }
}

export function setAdsConsent(granted: boolean): void {
  try {
    localStorage.setItem(ADS_CONSENT_KEY, granted ? 'granted' : 'denied');
  } catch {
    /* приватный режим: выбор живёт только до перезагрузки */
  }
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new Event(ADS_CONSENT_EVENT));
  }
}

export function hasAdsConsent(): boolean {
  return getAdsConsent() === 'granted';
}

export function subscribeAdsConsent(listener: () => void): () => void {
  if (typeof window === 'undefined') return () => undefined;
  const onChange = () => listener();
  window.addEventListener(ADS_CONSENT_EVENT, onChange);
  window.addEventListener('storage', onChange);
  return () => {
    window.removeEventListener(ADS_CONSENT_EVENT, onChange);
    window.removeEventListener('storage', onChange);
  };
}

/** Reactive consent state for banners, privacy controls and ad slots. */
export function useAdsConsent(): AdsConsent {
  return useSyncExternalStore(subscribeAdsConsent, getAdsConsent, () => null);
}

/** Open the consent banner again from the footer or the privacy page. */
export function openAdsConsentBanner(): void {
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new Event(ADS_CONSENT_OPEN_EVENT));
  }
}

/**
 * Public slot feed. Any network, adblock or control outage is treated as
 * "no ads": the page keeps its layout and nothing is logged to the console.
 */
export async function fetchAdsConfig(
  options: { adult?: boolean; signal?: AbortSignal } = {},
): Promise<AdSlotConfig[]> {
  const token = useAuthStore.getState().accessToken;
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (token) headers.Authorization = `Bearer ${token}`;

  const params = new URLSearchParams();
  if (options.adult) params.set('adult', '1');
  if (hasAdsConsent()) params.set('consent', '1');
  const query = params.toString();

  try {
    const response = await fetch(`${API_BASE}/ads/config${query ? `?${query}` : ''}`, {
      headers,
      cache: 'no-store',
      credentials: 'same-origin',
      signal: options.signal,
    });
    if (!response.ok) return [];
    const data: unknown = await response.json();
    return Array.isArray(data) ? (data as AdSlotConfig[]) : [];
  } catch {
    return [];
  }
}
