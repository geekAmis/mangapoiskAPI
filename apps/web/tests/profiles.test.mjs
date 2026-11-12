import assert from 'node:assert/strict';
import { test } from 'node:test';
import { build } from 'esbuild';

const bundle = await build({
  entryPoints: ['src/lib/profileUi.ts'],
  bundle: true,
  format: 'esm',
  platform: 'node',
  target: 'es2022',
  write: false,
});
const code = bundle.outputFiles[0].text;
const profileUi = await import(
  `data:text/javascript;base64,${Buffer.from(code).toString('base64')}`
);

const PUBLIC = {
  is_private: false,
  show_stats: true,
  show_events: true,
  show_achievements: true,
  indexable: true,
};

test('public profile is indexable by default', () => {
  assert.equal(profileUi.profileRobots(true), 'index,follow');
  assert.equal(profileUi.profileRobots(false), 'noindex,nofollow');
  assert.equal(profileUi.profileCanonical('manga_fan'), '/u/manga_fan');
  assert.equal(profileUi.isProfileIndexable(PUBLIC), true);
  assert.equal(profileUi.isProfileGuestVisible(PUBLIC), true);
});

test('hiding any public section makes the card guest-hidden and noindex', () => {
  for (const key of ['show_stats', 'show_events', 'show_achievements']) {
    const privacy = { ...PUBLIC, [key]: false };
    assert.equal(profileUi.isProfileGuestVisible(privacy), false, key);
    assert.equal(profileUi.isProfileIndexable(privacy), false, key);
  }
  const hidden = { ...PUBLIC, is_private: true };
  assert.equal(profileUi.isProfileGuestVisible(hidden), false);
  assert.equal(profileUi.isProfileIndexable(hidden), false);
  const optOut = { ...PUBLIC, indexable: false };
  assert.equal(profileUi.isProfileGuestVisible(optOut), true);
  assert.equal(profileUi.isProfileIndexable(optOut), false);
});

test('level progress is clamped and handles the max level', () => {
  assert.equal(
    profileUi.xpProgressPercent({ level: 2, xp_into_level: 25, xp_for_next_level: 100 }),
    25,
  );
  assert.equal(
    profileUi.xpProgressPercent({ level: 2, xp_into_level: 200, xp_for_next_level: 100 }),
    100,
  );
  assert.equal(
    profileUi.xpProgressPercent({ level: 99, xp_into_level: 0, xp_for_next_level: 0 }),
    100,
  );
});

test('privacy summary and event labels stay human-readable', () => {
  assert.match(profileUi.privacySummary(PUBLIC), /индексируется/);
  assert.match(profileUi.privacySummary({ ...PUBLIC, indexable: false }), /не индексируется/);
  assert.equal(profileUi.eventKindLabel('chapter_read'), 'Глава прочитана');
  assert.equal(profileUi.eventKindLabel('title_finished'), 'Тайтл завершён');
  assert.equal(profileUi.eventKindLabel('achievement'), 'Достижение');
});
