import assert from 'node:assert/strict';
import { test } from 'node:test';
import { build } from 'esbuild';

const bundle = await build({
  entryPoints: ['src/lib/progress.ts'],
  bundle: true,
  format: 'esm',
  platform: 'node',
  target: 'es2022',
  write: false,
});
const code = bundle.outputFiles[0].text;
const progress = await import(
  `data:text/javascript;base64,${Buffer.from(code).toString('base64')}`
);

class MemoryStorage {
  #data = new Map();
  getItem(key) {
    return this.#data.has(key) ? this.#data.get(key) : null;
  }
  setItem(key, value) {
    this.#data.set(key, String(value));
  }
  removeItem(key) {
    this.#data.delete(key);
  }
  clear() {
    this.#data.clear();
  }
}

function installWindow() {
  const events = new EventTarget();
  const fakeWindow = {
    localStorage: new MemoryStorage(),
    addEventListener: events.addEventListener.bind(events),
    removeEventListener: events.removeEventListener.bind(events),
    dispatchEvent: events.dispatchEvent.bind(events),
  };
  globalThis.window = fakeWindow;
  return fakeWindow;
}

function localItem(mangaId, page, { owner = null, updatedAt, title } = {}) {
  return {
    manga_id: mangaId,
    chapter_id: `chapter-${mangaId}`,
    page,
    total_pages: 20,
    owner_id: owner,
    updated_at: updatedAt ?? new Date().toISOString(),
    finished: false,
    manga: {
      id: mangaId,
      title: title ?? `Тайтл ${mangaId}`,
      poster_url: null,
      source: 'test',
      adult: false,
      genres: ['Фэнтези'],
      rating: 7,
      chapters_count: 10,
      status: 'ongoing',
    },
    chapter: {
      id: `chapter-${mangaId}`,
      volume: null,
      number: '1',
      title: 'Глава 1',
      page_count: 20,
    },
  };
}

test('local progress dedupes 5 read titles and keeps newest position', () => {
  const browser = installWindow();
  const base = Date.now() - 60_000;
  for (let index = 0; index < 5; index += 1) {
    progress.saveLocalProgress(
      localItem(`manga-${index}`, index + 1, {
        updatedAt: new Date(base + index * 1000).toISOString(),
      }),
    );
  }
  progress.saveLocalProgress(
    localItem('manga-0', 9, {
      updatedAt: new Date(base + 10_000).toISOString(),
    }),
  );

  const items = progress.readLocalProgress();
  assert.equal(items.length, 5);
  assert.equal(new Set(items.map((item) => item.manga_id)).size, 5);
  assert.equal(items.find((item) => item.manga_id === 'manga-0').page, 9);
  assert.equal(items[0].manga_id, 'manga-0');

  browser.localStorage.setItem('mp:progress:v1', '{broken json');
  assert.deepEqual(progress.readLocalProgress(), []);
});

test('anonymous and account copies are isolated but mergeable', () => {
  installWindow();
  progress.saveLocalProgress(localItem('anon-title', 3, { owner: null }));
  progress.saveLocalProgress(localItem('account-title', 4, { owner: 'user-a' }));

  assert.deepEqual(
    progress.readLocalProgress(null).map((item) => item.manga_id),
    ['anon-title'],
  );
  assert.deepEqual(
    progress.readLocalProgress('user-a').map((item) => item.manga_id).sort(),
    ['account-title', 'anon-title'],
  );
  assert.deepEqual(
    progress.readLocalProgress('user-b').map((item) => item.manga_id),
    ['anon-title'],
  );
});

test('mergeResumes has no duplicates and respects last-read ordering', () => {
  const remote = [
    {
      manga_id: 'a',
      chapter_id: 'remote-a',
      page: 2,
      total_pages: 20,
      updated_at: '2026-05-01T10:00:00.000Z',
      title: 'A',
      poster_url: null,
      source: 'test',
      chapter: { volume: null, number: '1', title: '', page_count: 20 },
      finished: false,
    },
    {
      manga_id: 'b',
      chapter_id: 'remote-b',
      page: 5,
      total_pages: 10,
      updated_at: '2026-05-02T10:00:00.000Z',
      title: 'B',
      poster_url: null,
      source: 'test',
      chapter: { volume: null, number: '2', title: '', page_count: 10 },
      finished: false,
    },
  ];
  const local = [
    {
      manga_id: 'a',
      chapter_id: 'local-a',
      page: 8,
      total_pages: 20,
      updated_at: '2026-05-03T10:00:00.000Z',
      title: 'A',
      poster_url: null,
      source: 'test',
      chapter: { volume: null, number: '1', title: '', page_count: 20 },
      finished: false,
    },
    {
      manga_id: 'c',
      chapter_id: 'local-c',
      page: 1,
      total_pages: 30,
      updated_at: '2026-05-02T12:00:00.000Z',
      title: 'C',
      poster_url: null,
      source: 'test',
      chapter: { volume: null, number: '1', title: '', page_count: 30 },
      finished: false,
    },
  ];
  const merged = progress.mergeResumes(local, remote);
  assert.deepEqual(merged.map((item) => item.manga_id), ['a', 'c', 'b']);
  assert.equal(merged[0].page, 8);
  assert.equal(new Set(merged.map((item) => item.manga_id)).size, merged.length);
});

test('local streak handles grace day and timezone boundary', () => {
  const moscow = progress.computeLocalStreak(
    [
      '2026-05-08T10:00:00.000Z',
      '2026-05-09T10:00:00.000Z',
      '2026-05-10T10:00:00.000Z',
    ],
    'Europe/Moscow',
    new Date('2026-05-10T12:00:00.000Z'),
  );
  assert.equal(moscow.current, 3);
  assert.equal(moscow.readToday, true);

  const grace = progress.computeLocalStreak(
    ['2026-05-08T10:00:00.000Z', '2026-05-09T10:00:00.000Z'],
    'Europe/Moscow',
    new Date('2026-05-10T12:00:00.000Z'),
  );
  assert.equal(grace.current, 2);
  assert.equal(grace.readToday, false);

  const tokyo = progress.computeLocalStreak(
    ['2026-01-01T14:00:00.000Z', '2026-01-01T15:00:00.000Z'],
    'Asia/Tokyo',
    new Date('2026-01-02T00:30:00.000Z'),
  );
  assert.equal(tokyo.current, 2);

  const empty = progress.computeLocalStreak([], 'Europe/Moscow', new Date());
  assert.equal(empty.current, 0);
  assert.equal(empty.longest, 0);
});
