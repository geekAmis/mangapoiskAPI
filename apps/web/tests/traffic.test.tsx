import { StrictMode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { Link, MemoryRouter } from 'react-router-dom';
import { TrafficTracker } from '../src/components/TrafficTracker';
import {
  installMetrika,
  metrikaCounterId,
  metrikaHit,
  resetMetrikaForTests,
} from '../src/lib/metrika';
import { trafficPathGroup } from '../src/lib/traffic';

function clearMetrika(): void {
  resetMetrikaForTests();
  document.head
    .querySelectorAll('script[data-yandex-metrika]')
    .forEach((element) => element.remove());
  delete window.ym;
}

function ymCalls(): unknown[][] {
  return (window.ym?.a ?? []) as unknown[][];
}

function hitCalls(): unknown[][] {
  return ymCalls().filter((call) => call[1] === 'hit');
}

describe('Yandex Metrika build-time loader', () => {
  beforeEach(clearMetrika);

  it('accepts only a numeric counter id and never hardcodes one', () => {
    expect(metrikaCounterId('')).toBeNull();
    expect(metrikaCounterId(null)).toBeNull();
    expect(metrikaCounterId('R-A-20411736-1')).toBeNull();
    expect(metrikaCounterId('12345678')).toBe('12345678');
  });

  it('does nothing when the counter id is empty', () => {
    expect(installMetrika(null)).toBe(false);
    expect(document.querySelector('script[data-yandex-metrika]')).toBeNull();
    expect(window.ym).toBeUndefined();
  });

  it('injects tag.js exactly once and initialises with webvisor off', () => {
    expect(installMetrika('12345678')).toBe(true);
    expect(document.querySelectorAll('script[data-yandex-metrika]')).toHaveLength(1);
    expect(installMetrika('12345678')).toBe(false);
    expect(document.querySelectorAll('script[data-yandex-metrika]')).toHaveLength(1);

    const init = ymCalls().find((call) => call[1] === 'init');
    expect(init?.[0]).toBe('12345678');
    expect(init?.[2]).toMatchObject({
      defer: true,
      webvisor: false,
      trackHash: false,
    });
  });

  it('sends only a clean pathname and a coarse page_group', () => {
    metrikaHit('12345678', '/manga/abc?q=secret#frag', 'manga');
    const hit = hitCalls().at(-1);
    expect(hit?.[2]).toBe('/manga/abc');
    expect(hit?.[3]).toMatchObject({ params: { page_group: 'manga' } });
    expect(JSON.stringify(hit)).not.toContain('secret');
  });
});

describe('public route groups', () => {
  it.each([
    ['/', 'home'],
    ['/catalogue', 'catalogue'],
    ['/catalog/genres', 'catalogue'],
    ['/manga/abc-title', 'manga'],
    ['/collections/new', 'collection'],
    ['/sources', 'sources'],
    ['/privacy', 'legal'],
    ['/u/reader', 'profile'],
    ['/404', 'other'],
  ])('%s -> %s', (path, group) => {
    expect(trafficPathGroup(path)).toBe(group);
  });

  it.each(['/admin', '/read/abc', '/reader/abc', '/library', '/profile', '/login'])(
    'skips private route %s',
    (path) => {
      expect(trafficPathGroup(path)).toBeNull();
    },
  );
});

describe('TrafficTracker', () => {
  const sendBeacon = vi.fn(() => true);

  beforeEach(() => {
    clearMetrika();
    sendBeacon.mockClear();
    Object.defineProperty(navigator, 'sendBeacon', {
      configurable: true,
      value: sendBeacon,
    });
    Object.defineProperty(navigator, 'doNotTrack', {
      configurable: true,
      value: null,
    });
  });

  it('tracks a public SPA page once and sends no PII fields', async () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <TrafficTracker counterId={null} />
      </MemoryRouter>,
    );

    await waitFor(() => expect(sendBeacon).toHaveBeenCalledTimes(1));
    const [url, body] = sendBeacon.mock.calls[0] as [string, Blob];
    expect(url).toBe('/api/v1/traffic/visit');
    const payload = await body.text();
    expect(payload).toContain('"path_group":"home"');
    expect(payload).not.toMatch(/ip|user.?agent|email|token/i);
  });

  it('injects Metrika only when a counter id is provided', async () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <TrafficTracker counterId="12345678" />
      </MemoryRouter>,
    );

    await waitFor(() =>
      expect(document.querySelector('script[data-yandex-metrika]')).toBeTruthy(),
    );
    await waitFor(() => expect(hitCalls()).toHaveLength(1));

    const { unmount } = render(
      <MemoryRouter initialEntries={['/privacy']}>
        <TrafficTracker counterId={null} />
      </MemoryRouter>,
    );
    unmount();
    expect(document.querySelectorAll('script[data-yandex-metrika]')).toHaveLength(1);
  });

  it('sends a hit and a beacon on route change, but not for admin', async () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <TrafficTracker counterId="12345678" />
        <Link to="/catalogue">catalogue</Link>
        <Link to="/admin">admin</Link>
      </MemoryRouter>,
    );

    await waitFor(() => expect(sendBeacon).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByText('catalogue'));
    await waitFor(() => expect(sendBeacon).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(hitCalls()).toHaveLength(2));

    fireEvent.click(screen.getByText('admin'));
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(sendBeacon).toHaveBeenCalledTimes(2);
    expect(hitCalls()).toHaveLength(2);
  });

  it('honours Do Not Track for both Metrika and the beacon', async () => {
    Object.defineProperty(navigator, 'doNotTrack', {
      configurable: true,
      value: '1',
    });

    render(
      <MemoryRouter initialEntries={['/']}>
        <TrafficTracker counterId="12345678" />
      </MemoryRouter>,
    );

    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(sendBeacon).not.toHaveBeenCalled();
    expect(document.querySelector('script[data-yandex-metrika]')).toBeNull();
  });

  it('does not double count under StrictMode', async () => {
    render(
      <StrictMode>
        <MemoryRouter initialEntries={['/']}>
          <TrafficTracker counterId={null} />
        </MemoryRouter>
      </StrictMode>,
    );

    await waitFor(() => expect(sendBeacon).toHaveBeenCalledTimes(1));
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(sendBeacon).toHaveBeenCalledTimes(1);
  });
});
