import { act, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../src/api/client';
import type { ChapterDetailOut, MangaDetailOut, ProgressOut } from '../src/api/types';
import ReaderPage from '../src/pages/ReaderPage';
import { useAuthStore } from '../src/stores/auth';
import { useReaderStore } from '../src/stores/reader';

const CHAPTER: ChapterDetailOut = {
  id: 'chapter-1',
  manga_id: 'manga-1',
  source: 'test',
  source_id: 'chapter-1',
  volume: null,
  number: '1',
  title: 'Test chapter',
  published_at: null,
  page_count: 5,
  url: null,
  is_external: false,
  created_at: null,
  updated_at: null,
  pages: Array.from({ length: 5 }, (_, index) => ({
    number: index + 1,
    url: `/page-${index + 1}.jpg`,
    width: 800,
    height: 1200,
  })),
  prev_chapter_id: null,
  next_chapter_id: null,
  is_horizontal: false,
};

const MANGA = {
  id: 'manga-1',
  source: 'test',
  source_id: 'manga-1',
  slug: 'test',
  title: 'Test manga',
  title_en: null,
  title_alt: null,
  description: null,
  poster_url: null,
  adult: false,
  genres: [],
  rating: null,
  chapters_count: 1,
  status: 'ongoing',
  url_slug: 'test',
  chapters: [],
} as unknown as MangaDetailOut;

const PROGRESS: ProgressOut = {
  manga_id: 'manga-1',
  chapter_id: 'chapter-1',
  page: 4,
  total_pages: 5,
  updated_at: new Date().toISOString(),
  manga: MANGA as never,
  chapter: null,
};

function renderReader() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/reader/chapter-1']}>
        <Routes>
          <Route path="/reader/:chapterId" element={<ReaderPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn();
  useReaderStore.setState({ mode: 'vertical', autoScroll: false });
  useAuthStore.setState({
    accessToken: 'token',
    refreshToken: 'refresh',
    user: { id: 'user-1', username: 'tester' } as never,
  });
  vi.spyOn(api, 'getChapter').mockResolvedValue(CHAPTER);
  vi.spyOn(api, 'getManga').mockResolvedValue(MANGA);
  vi.spyOn(api, 'getBookmarks').mockResolvedValue([]);
  vi.spyOn(api, 'upsertProgress').mockResolvedValue(PROGRESS);
});

afterEach(() => {
  useAuthStore.setState({ accessToken: null, refreshToken: null, user: null });
});

describe('ReaderPage resume prompt', () => {
  it('does not show the prompt when progress resolves after the reader scrolled', async () => {
    let resolveProgress!: (value: { items: ProgressOut[] }) => void;
    const progress = new Promise<{ items: ProgressOut[] }>((resolve) => {
      resolveProgress = resolve;
    });
    vi.spyOn(api, 'getProgress').mockReturnValue(progress);

    renderReader();
    await waitFor(() => expect(screen.getByRole('progressbar', { name: 'Прогресс главы' })).toBeTruthy());

    // Let the initial programmatic scroll guard expire, then read.
    await new Promise((resolve) => setTimeout(resolve, 350));
    act(() => {
      window.dispatchEvent(new Event('scroll'));
    });

    act(() => {
      resolveProgress({ items: [PROGRESS] });
    });

    // The grace period has elapsed and the slow progress data has arrived.
    await new Promise((resolve) => setTimeout(resolve, 1900));
    expect(screen.queryByText(/Продолжить со страницы/)).toBeNull();
  }, 10_000);

  it('shows the prompt for an idle reader and Continue jumps to the saved page', async () => {
    vi.spyOn(api, 'getProgress').mockResolvedValue({ items: [PROGRESS] });

    renderReader();
    await waitFor(() => expect(screen.getByRole('progressbar', { name: 'Прогресс главы' })).toBeTruthy());

    const prompt = await screen.findByText('Продолжить со страницы 4?', undefined, {
      timeout: 3000,
    });
    expect(prompt).toBeTruthy();

    act(() => {
      screen.getByRole('button', { name: 'Продолжить' }).click();
    });

    await waitFor(() => {
      expect(
        screen.getByRole('progressbar', { name: 'Прогресс главы' }).getAttribute('aria-valuenow'),
      ).toBe('4');
    });
    expect(screen.queryByText(/Продолжить со страницы/)).toBeNull();
  }, 10_000);

  it('dismisses the prompt when the reader starts over', async () => {
    vi.spyOn(api, 'getProgress').mockResolvedValue({ items: [PROGRESS] });

    renderReader();
    await screen.findByText('Продолжить со страницы 4?', undefined, { timeout: 3000 });

    act(() => {
      screen.getByRole('button', { name: 'С начала' }).click();
    });

    await waitFor(() => expect(screen.queryByText(/Продолжить со страницы/)).toBeNull());
    expect(
      screen.getByRole('progressbar', { name: 'Прогресс главы' }).getAttribute('aria-valuenow'),
    ).toBe('1');
  }, 10_000);
});
