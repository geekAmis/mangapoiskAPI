import { useEffect } from 'react';
import { getThemeMeta, useThemeStore } from '../stores/theme';

const META_COLORS: Record<string, string> = {
  midnight: '#060b12',
  noir: '#08080a',
  oni: '#100b0b',
  crimson: '#0a090c',
  sunset: '#160f1d',
  paper: '#f1ece2',
};

export function ThemeEffects() {
  const theme = useThemeStore((state) => state.theme);

  useEffect(() => {
    const root = document.documentElement;
    root.dataset.theme = theme;

    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute('content', META_COLORS[theme] ?? getThemeMeta(theme).bg);
  }, [theme]);

  return null;
}
