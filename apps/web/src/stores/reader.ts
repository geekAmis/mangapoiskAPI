import { create } from 'zustand';
import { createJSONStorage, persist } from 'zustand/middleware';

export type ReaderMode = 'vertical' | 'horizontal';
export type PageFit = 'width' | 'height' | 'original';
export type ReaderGap = 0 | 8 | 16 | 24 | 32;

export interface ReaderPreferences {
  mode: ReaderMode;
  pageFit: PageFit;
  gap: ReaderGap;
  autoScroll: boolean;
  autoScrollSpeed: number;
  showPageNumbers: boolean;
  blurAdultPosters: boolean;
}

export const DEFAULT_READER_PREFERENCES: ReaderPreferences = {
  mode: 'vertical',
  pageFit: 'width',
  gap: 8,
  autoScroll: false,
  autoScrollSpeed: 30,
  showPageNumbers: true,
  blurAdultPosters: true,
};

interface ReaderState extends ReaderPreferences {
  update: (patch: Partial<ReaderPreferences>) => void;
  reset: () => void;
}

export const useReaderStore = create<ReaderState>()(
  persist(
    (set) => ({
      ...DEFAULT_READER_PREFERENCES,
      update: (patch) => set(patch),
      reset: () => set(DEFAULT_READER_PREFERENCES),
    }),
    {
      name: 'mp:reader',
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({
        mode: state.mode,
        pageFit: state.pageFit,
        gap: state.gap,
        autoScroll: state.autoScroll,
        autoScrollSpeed: state.autoScrollSpeed,
        showPageNumbers: state.showPageNumbers,
        blurAdultPosters: state.blurAdultPosters,
      }),
    },
  ),
);

export function clampSpeed(value: number): number {
  if (!Number.isFinite(value)) return DEFAULT_READER_PREFERENCES.autoScrollSpeed;
  return Math.min(200, Math.max(5, Math.round(value)));
}
