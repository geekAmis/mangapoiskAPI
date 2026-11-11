import { create } from 'zustand';
import { createJSONStorage, persist } from 'zustand/middleware';

export const THEMES = [
  {
    id: 'midnight',
    name: 'Полночь',
    description: 'Неоновый дождь, лёд и электричество',
    accent: '#5ec8ff',
    bg: '#060b12',
    glyph: '雨',
  },
  {
    id: 'noir',
    name: 'Нуар',
    description: 'Готика, слоновая кость и серебро',
    accent: '#e3d6bb',
    bg: '#08080a',
    glyph: '夜',
  },
  {
    id: 'oni',
    name: 'Они',
    description: 'Маска демона, уголь и кровь',
    accent: '#ff6252',
    bg: '#100b0b',
    glyph: '鬼',
  },
  {
    id: 'crimson',
    name: 'Багрянец',
    description: 'Минимализм, тьма и алый акцент',
    accent: '#ff506e',
    bg: '#0a090c',
    glyph: '紅',
  },
  {
    id: 'sunset',
    name: 'Закат',
    description: 'Слива, коралл и янтарь',
    accent: '#ff9166',
    bg: '#160f1d',
    glyph: '寺',
  },
  {
    id: 'paper',
    name: 'Бумага',
    description: 'Светлая укиё-э, тушь и вермильон',
    accent: '#b13a1e',
    bg: '#f1ece2',
    glyph: '紙',
  },
] as const;

export type ThemeId = (typeof THEMES)[number]['id'];

const THEME_IDS = new Set<string>(THEMES.map((theme) => theme.id));

export function isThemeId(value: unknown): value is ThemeId {
  return typeof value === 'string' && THEME_IDS.has(value);
}

export function getThemeMeta(id: ThemeId) {
  return THEMES.find((theme) => theme.id === id) ?? THEMES[0];
}

function detectInitialTheme(): ThemeId {
  if (typeof window === 'undefined') return 'midnight';
  try {
    const raw =
      window.localStorage.getItem('mp-theme') ?? window.localStorage.getItem('mp:theme');
    if (raw) {
      const parsed: unknown = JSON.parse(raw);
      if (typeof parsed === 'object' && parsed !== null && 'state' in parsed) {
        const state = (parsed as { state?: unknown }).state;
        if (typeof state === 'object' && state !== null && 'theme' in state) {
          const stored = (state as { theme?: unknown }).theme;
          if (isThemeId(stored)) return stored;
        }
      }
    }
  } catch {
    /* приватный режим или повреждённое значение */
  }
  return window.matchMedia('(prefers-color-scheme: light)').matches ? 'paper' : 'midnight';
}

interface ThemeState {
  theme: ThemeId;
  setTheme: (theme: ThemeId) => void;
}

export const useThemeStore = create<ThemeState>()(
  persist(
    (set) => ({
      theme: detectInitialTheme(),
      setTheme: (theme) => set({ theme }),
    }),
    {
      name: 'mp-theme',
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({ theme: state.theme }),
    },
  ),
);

export function isLightTheme(theme: ThemeId): boolean {
  return theme === 'paper';
}
