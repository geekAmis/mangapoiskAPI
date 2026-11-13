import { act } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { AdSlot } from '../src/components/ads/AdSlot';
import { ConsentBanner, ConsentControls } from '../src/components/ConsentBanner';
import {
  ADS_CONSENT_KEY,
  getAdsConsent,
  hasAdsConsent,
  setAdsConsent,
  type AdSlotConfig,
} from '../src/api/ads';
import { setAgeConfirmation, hasAgeConfirmation } from '../src/lib/age';

function renderBanner() {
  return render(
    <MemoryRouter>
      <ConsentBanner />
    </MemoryRouter>,
  );
}

function renderAd() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <AdSlot placement="header" />
    </QueryClientProvider>,
  );
}

const CONSENT_SLOT: AdSlotConfig = {
  id: 'consent-slot',
  name: 'Consent test',
  type: 'custom_html',
  placement: 'header',
  priority: 1,
  audience: 'both',
  frequency_cap: 0,
  format: 'Тестовый блок',
  width: 970,
  height: 90,
  content: '<span>AD</span>',
  content_type: 'html',
  require_consent: true,
  config: {},
};

describe('cookie/ads consent', () => {
  it('shows the short cookie banner on first visit, persists accept and hides on reload', () => {
    const first = renderBanner();
    expect(screen.getByText('Cookie')).toBeTruthy();
    expect(
      screen.getByText(/Используем cookie для входа, настроек и статистики/),
    ).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Политика' })).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Принять' }));
    expect(localStorage.getItem(ADS_CONSENT_KEY)).toBe('granted');
    expect(hasAdsConsent()).toBe(true);
    expect(screen.queryByText('Cookie')).toBeNull();

    first.unmount();
    renderBanner();
    expect(screen.queryByText('Cookie')).toBeNull();
  });

  it('persists the necessary-only choice and does not show the banner again', () => {
    renderBanner();
    fireEvent.click(screen.getByRole('button', { name: 'Только необходимые' }));
    expect(localStorage.getItem(ADS_CONSENT_KEY)).toBe('denied');
    expect(getAdsConsent()).toBe('denied');
    expect(screen.queryByText('Cookie')).toBeNull();
  });

  it('does not show require_consent ad slots until consent is granted', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: true,
        status: 200,
        json: async () => [CONSENT_SLOT],
      })),
    );

    renderAd();
    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalled());
    expect(screen.queryByLabelText('Реклама')).toBeNull();

    act(() => setAdsConsent(true));
    await waitFor(() => expect(screen.getByLabelText('Реклама')).toBeTruthy());

    act(() => setAdsConsent(false));
    await waitFor(() => expect(screen.queryByLabelText('Реклама')).toBeNull());
  });

  it('uses cookie/statistics wording in the privacy controls', () => {
    render(
      <MemoryRouter>
        <ConsentControls />
      </MemoryRouter>,
    );
    expect(screen.getByText('Cookie и статистика')).toBeTruthy();
    expect(screen.getByText(/Выбор не сделан/)).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Разрешить' }));
    expect(localStorage.getItem(ADS_CONSENT_KEY)).toBe('granted');
    expect(screen.getByText(/Разрешено/)).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Только необходимые' }));
    expect(localStorage.getItem(ADS_CONSENT_KEY)).toBe('denied');
    expect(screen.getByText(/Только необходимые\. Выбор/)).toBeTruthy();
  });

  it('stores and revokes the 18+ self-confirmation locally', () => {
    expect(hasAgeConfirmation()).toBe(false);
    act(() => setAgeConfirmation(true));
    expect(localStorage.getItem('mp-age-confirmed')).toBe('1');
    expect(hasAgeConfirmation()).toBe(true);
    act(() => setAgeConfirmation(false));
    expect(localStorage.getItem('mp-age-confirmed')).toBeNull();
    expect(hasAgeConfirmation()).toBe(false);
  });
});
