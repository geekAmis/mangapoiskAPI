import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import App from '../src/App';
import RegisterPage from '../src/pages/RegisterPage';
import { legalConfigFromValues, legalDisplayValue } from '../src/lib/legal';

function renderAt(path: string) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function renderRegister() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/register']}>
        <RegisterPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('legal routes', () => {
  it.each([
    ['/terms', 'Пользовательское соглашение'],
    ['/privacy', 'Политика конфиденциальности'],
    ['/dmca', 'Правообладателям и DMCA'],
    ['/contacts', 'Контакты и реквизиты'],
    ['/age', 'Возрастное ограничение 18+'],
  ])('renders %s with a single level-1 heading', (path, heading) => {
    renderAt(path);
    expect(screen.getByRole('heading', { level: 1, name: heading })).toBeTruthy();
  });

  it('keeps footer legal links available on every layout route', () => {
    renderAt('/terms');
    const footer = document.querySelector<HTMLElement>('.site-footer');
    expect(footer).toBeTruthy();
    const expected: Array<[string, string]> = [
      ['Пользовательское соглашение', '/terms'],
      ['Политика конфиденциальности', '/privacy'],
      ['Правообладателям / DMCA', '/dmca'],
      ['Контакты и реквизиты', '/contacts'],
      ['Возрастное ограничение 18+', '/age'],
    ];

    for (const [label, href] of expected) {
      const link = within(footer as HTMLElement).getByRole('link', { name: label });
      expect(link.getAttribute('href')).toBe(href);
    }
  });

  it('uses an explicit env placeholder instead of a fake contact', () => {
    const empty = legalConfigFromValues({
      contactEmail: '',
      ownerName: '   ',
      jurisdiction: '',
    });
    expect(empty.contactEmail).toBeNull();
    expect(empty.ownerName).toBeNull();

    const contact = legalDisplayValue(empty.contactEmail, 'LEGAL_CONTACT_EMAIL');
    expect(contact.isPlaceholder).toBe(true);
    expect(contact.text).toContain('LEGAL_CONTACT_EMAIL');
    expect(contact.text).toContain('Не указано');

    renderAt('/contacts');
    expect(screen.getAllByText(/LEGAL_CONTACT_EMAIL/).length).toBeGreaterThan(0);
    expect(document.body.textContent).not.toMatch(/[^\s@]+@[^\s@]+\.[^\s@]+/);
  });

  it('sets title, canonical, robots and WebPage JSON-LD for a legal page', async () => {
    renderAt('/privacy');

    await waitFor(() => {
      expect(document.title).toBe('Политика конфиденциальности — MangaPoisk Reborn');
    });
    expect(document.querySelector('link[rel="canonical"]')?.getAttribute('href')).toContain(
      '/privacy',
    );
    expect(document.querySelector('meta[name="robots"]')?.getAttribute('content')).toBe(
      'index,follow',
    );

    const jsonLd = document.querySelector('script[data-seo="json-ld"]')?.textContent;
    expect(jsonLd).toBeTruthy();
    const parsed = JSON.parse(jsonLd ?? '{}') as Record<string, unknown>;
    expect(parsed['@type']).toBe('WebPage');
    expect(parsed.inLanguage).toBe('ru');
    expect(parsed.url).toContain('/privacy');
  });

  it('keeps /age indexable and shows the 18+ warning', async () => {
    renderAt('/age');
    expect(screen.getByText(/Внимание: контент 18\+/)).toBeTruthy();
    await waitFor(() => {
      expect(document.querySelector('meta[name="robots"]')?.getAttribute('content')).toBe(
        'index,follow',
      );
    });
  });
});

describe('registration consent', () => {
  it('requires the 18+ confirmation and terms/privacy acceptance', () => {
    renderRegister();

    fireEvent.change(screen.getByLabelText('Имя или никнейм'), {
      target: { value: 'Тестовый читатель' },
    });
    fireEvent.change(screen.getByLabelText('Email'), {
      target: { value: 'reader@example.test' },
    });
    fireEvent.change(screen.getByLabelText('Пароль'), {
      target: { value: 'long-password-123' },
    });
    fireEvent.change(screen.getByLabelText('Повторите пароль'), {
      target: { value: 'long-password-123' },
    });
    fireEvent.click(screen.getByRole('button', { name: /Зарегистрироваться/ }));

    expect(screen.getByText('Подтвердите, что вам 18 лет или больше.')).toBeTruthy();
    expect(
      screen.getByText(
        'Примите Пользовательское соглашение и Политику конфиденциальности.',
      ),
    ).toBeTruthy();
    const requestedUrls = vi.mocked(fetch).mock.calls.map(([url]) => String(url));
    expect(requestedUrls.some((url) => url.includes('/auth/register'))).toBe(false);
  });

  it('submits once both consents are checked', async () => {
    renderRegister();

    fireEvent.change(screen.getByLabelText('Имя или никнейм'), {
      target: { value: 'Тестовый читатель' },
    });
    fireEvent.change(screen.getByLabelText('Email'), {
      target: { value: 'reader@example.test' },
    });
    fireEvent.change(screen.getByLabelText('Пароль'), {
      target: { value: 'long-password-123' },
    });
    fireEvent.change(screen.getByLabelText('Повторите пароль'), {
      target: { value: 'long-password-123' },
    });
    fireEvent.click(screen.getByLabelText(/Мне 18 лет или больше/));
    fireEvent.click(screen.getByLabelText(/Я принимаю условия использования/));
    fireEvent.click(screen.getByRole('button', { name: /Зарегистрироваться/ }));

    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalled());
  });
});
