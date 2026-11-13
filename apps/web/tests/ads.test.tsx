import { StrictMode, act } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import {
  AdSlot,
  yandexBlockIdFromConfig,
} from '../src/components/ads/AdSlot';
import {
  ADS_CONSENT_KEY,
  setAdsConsent,
  type AdSlotConfig,
} from '../src/api/ads';

const BLOCK_ID = 'R-A-20411736-1';

function yandexSlot(overrides: Partial<AdSlotConfig> = {}): AdSlotConfig {
  return {
    id: 'yandex-in-feed',
    name: 'Yandex RTB in-feed',
    type: 'yandex',
    placement: 'in-feed',
    priority: 1,
    audience: 'both',
    frequency_cap: 0,
    format: '728x90',
    width: 728,
    height: 90,
    content: '',
    content_type: 'none',
    require_consent: false,
    config: { block_id: BLOCK_ID },
    ...overrides,
  };
}

function renderAd(slot: AdSlotConfig, strict = false) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => [slot],
    })),
  );
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const tree = (
    <QueryClientProvider client={client}>
      <AdSlot placement="in-feed" />
    </QueryClientProvider>
  );
  return render(strict ? <StrictMode>{tree}</StrictMode> : tree);
}

afterEach(() => {
  delete window.Ya;
  delete window.yaContextCb;
  localStorage.removeItem(ADS_CONSENT_KEY);
});

describe('Yandex RTB ad slot', () => {
  it('validates the R-A-<number>-<number> block id', () => {
    expect(yandexBlockIdFromConfig({ block_id: BLOCK_ID })).toBe(BLOCK_ID);
    expect(yandexBlockIdFromConfig({ block_id: ' R-A-1-2 ' })).toBe('R-A-1-2');
    expect(yandexBlockIdFromConfig({ block_id: 'RA-1-2' })).toBeNull();
    expect(yandexBlockIdFromConfig({ block_id: 'R-A-1' })).toBeNull();
    expect(yandexBlockIdFromConfig({ block_id: 42 })).toBeNull();
    expect(yandexBlockIdFromConfig({})).toBeNull();
    expect(yandexBlockIdFromConfig(undefined)).toBeNull();
  });

  it('renders the container and calls Ya.Context.AdvManager.render', async () => {
    const renderMock = vi.fn();
    window.Ya = { Context: { AdvManager: { render: renderMock } } };

    renderAd(yandexSlot());

    await waitFor(() =>
      expect(document.getElementById(`yandex_rtb_${BLOCK_ID}`)).toBeTruthy(),
    );
    expect(renderMock).toHaveBeenCalledTimes(1);
    expect(renderMock).toHaveBeenCalledWith({
      blockId: BLOCK_ID,
      renderTo: `yandex_rtb_${BLOCK_ID}`,
    });
  });

  it('queues one render callback in StrictMode and never renders twice', async () => {
    window.yaContextCb = [];

    renderAd(yandexSlot(), true);

    await waitFor(() =>
      expect(document.getElementById(`yandex_rtb_${BLOCK_ID}`)).toBeTruthy(),
    );
    const queue = window.yaContextCb ?? [];
    expect(queue).toHaveLength(1);

    const renderMock = vi.fn();
    window.Ya = { Context: { AdvManager: { render: renderMock } } };
    queue.forEach((callback) => callback());
    queue.forEach((callback) => callback());

    expect(renderMock).toHaveBeenCalledTimes(1);
  });

  it('does not double render when the SDK is already loaded in StrictMode', async () => {
    const renderMock = vi.fn();
    window.Ya = { Context: { AdvManager: { render: renderMock } } };

    renderAd(yandexSlot(), true);

    await waitFor(() => expect(renderMock).toHaveBeenCalled());
    expect(renderMock).toHaveBeenCalledTimes(1);
  });

  it.each([
    ['missing', {}],
    ['invalid', { block_id: 'not-a-yandex-block' }],
    ['non-string', { block_id: 42 }],
  ])('renders the placeholder for a %s block id', async (_label, config) => {
    const renderMock = vi.fn();
    window.Ya = { Context: { AdvManager: { render: renderMock } } };

    renderAd(yandexSlot({ config }));

    await waitFor(() => expect(screen.getByLabelText('Реклама')).toBeTruthy());
    expect(screen.getByText('728x90')).toBeTruthy();
    expect(renderMock).not.toHaveBeenCalled();
  });

  it.each([
    ['null', null],
    ['denied', 'denied'],
  ] as const)('renders Yandex when consent is %s', async (_label, consent) => {
    if (consent) localStorage.setItem(ADS_CONSENT_KEY, consent);
    const renderMock = vi.fn();
    window.Ya = { Context: { AdvManager: { render: renderMock } } };

    renderAd(yandexSlot({ require_consent: false }));

    await waitFor(() =>
      expect(document.getElementById(`yandex_rtb_${BLOCK_ID}`)).toBeTruthy(),
    );
    expect(renderMock).toHaveBeenCalledTimes(1);
  });

  it('does not re-render Yandex when the consent choice changes', async () => {
    const renderMock = vi.fn();
    window.Ya = { Context: { AdvManager: { render: renderMock } } };
    renderAd(yandexSlot());
    await waitFor(() => expect(renderMock).toHaveBeenCalledTimes(1));

    act(() => setAdsConsent(false));
    await waitFor(() => expect(localStorage.getItem(ADS_CONSENT_KEY)).toBe('denied'));
    await new Promise((resolve) => setTimeout(resolve, 50));

    expect(renderMock).toHaveBeenCalledTimes(1);
  });

  it('still hides require_consent providers until consent is granted', async () => {
    localStorage.setItem(ADS_CONSENT_KEY, 'denied');
    const custom: AdSlotConfig = {
      ...yandexSlot(),
      id: 'custom-in-feed',
      type: 'custom_html',
      content: '<span>custom</span>',
      content_type: 'html',
      config: {},
      require_consent: true,
    };

    renderAd(custom);

    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalled());
    expect(screen.queryByLabelText('Реклама')).toBeNull();
  });
});
