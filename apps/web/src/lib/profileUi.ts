import type { ProfilePrivacyOut, PublicProfileOut } from '../api/types';

/** Robots directive for the public profile page and the API response header. */
export function profileRobots(indexable: boolean): string {
  return indexable ? 'index,follow' : 'noindex,nofollow';
}

/** Canonical path for a public profile. Handles are already URL-safe. */
export function profileCanonical(username: string): string {
  return `/u/${encodeURIComponent(username)}`;
}

/** Clamp server-provided level progress into a CSS-safe percentage. */
export function xpProgressPercent(
  profile: Pick<PublicProfileOut, 'level' | 'xp_into_level' | 'xp_for_next_level'>,
): number {
  if (profile.xp_for_next_level <= 0) return 100;
  const ratio = profile.xp_into_level / profile.xp_for_next_level;
  return Math.round(Math.min(1, Math.max(0, ratio)) * 100);
}

/**
 * A profile is guest-visible only when every public section is enabled.
 * Owners can always open their own page. Keep this in sync with
 * `profile_sections_visible` in the library service.
 */
export function isProfileGuestVisible(privacy: ProfilePrivacyOut): boolean {
  return !privacy.is_private && privacy.show_stats && privacy.show_events && privacy.show_achievements;
}

/** Whether the card should be submitted to search engines. */
export function isProfileIndexable(privacy: ProfilePrivacyOut): boolean {
  return privacy.indexable && isProfileGuestVisible(privacy);
}

export function privacySummary(privacy: ProfilePrivacyOut): string {
  if (privacy.is_private) return 'Профиль скрыт от гостей';
  if (!isProfileGuestVisible(privacy)) return 'Один из разделов скрыт — профиль недоступен гостям';
  if (!privacy.indexable) return 'Профиль открыт, но не индексируется';
  return 'Профиль открыт и индексируется';
}

export function eventKindLabel(kind: string): string {
  if (kind === 'chapter_read') return 'Глава прочитана';
  if (kind === 'title_finished') return 'Тайтл завершён';
  if (kind === 'achievement') return 'Достижение';
  return 'Событие';
}
