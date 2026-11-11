import type { ReaderSettings } from '../api/types';
import type { ReaderPreferences, ReaderMode, PageFit, ReaderGap } from '../stores/reader';
import { clampSpeed, useReaderStore } from '../stores/reader';
import { isThemeId, useThemeStore, type ThemeId } from '../stores/theme';

export function settingsFromStores(theme: ThemeId, prefs: ReaderPreferences): ReaderSettings {
  return {
    theme,
    reader_mode: prefs.mode,
    page_fit: prefs.pageFit,
    auto_scroll: prefs.autoScroll,
    auto_scroll_speed: clampSpeed(prefs.autoScrollSpeed),
    show_page_numbers: prefs.showPageNumbers,
    blur_adult_posters: prefs.blurAdultPosters,
  };
}

export function settingsEqual(a: ReaderSettings, b: ReaderSettings): boolean {
  return (
    a.theme === b.theme &&
    a.reader_mode === b.reader_mode &&
    a.page_fit === b.page_fit &&
    a.auto_scroll === b.auto_scroll &&
    a.auto_scroll_speed === b.auto_scroll_speed &&
    a.show_page_numbers === b.show_page_numbers &&
    a.blur_adult_posters === b.blur_adult_posters
  );
}

function normalizeMode(mode: string): ReaderMode {
  return mode === 'horizontal' ? 'horizontal' : 'vertical';
}

function normalizeFit(fit: string): PageFit {
  if (fit === 'height' || fit === 'original') return fit;
  return 'width';
}

function normalizeGap(value: number): ReaderGap {
  if (value >= 32) return 32;
  if (value >= 24) return 24;
  if (value >= 16) return 16;
  if (value >= 8) return 8;
  return 0;
}

/** Применяет настройки из профиля, не затирая локальный отступ между страницами. */
export function applySettingsToStores(settings: ReaderSettings): void {
  if (isThemeId(settings.theme)) {
    useThemeStore.getState().setTheme(settings.theme);
  }

  const current = useReaderStore.getState();
  useReaderStore.getState().update({
    mode: normalizeMode(settings.reader_mode),
    pageFit: normalizeFit(settings.page_fit),
    autoScroll: Boolean(settings.auto_scroll),
    autoScrollSpeed: clampSpeed(settings.auto_scroll_speed),
    showPageNumbers: settings.show_page_numbers !== false,
    blurAdultPosters: settings.blur_adult_posters !== false,
    gap: normalizeGap(current.gap),
  });
}
