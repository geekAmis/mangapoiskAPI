import { create } from 'zustand';
import { createJSONStorage, persist } from 'zustand/middleware';
import type { TokenPair, UserOut } from '../api/types';

interface AuthState {
  accessToken: string | null;
  refreshToken: string | null;
  user: UserOut | null;
  setSession: (pair: TokenPair) => void;
  setAccessToken: (token: string) => void;
  setUser: (user: UserOut) => void;
  clear: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      accessToken: null,
      refreshToken: null,
      user: null,
      setSession: (pair) =>
        set({
          accessToken: pair.access_token,
          refreshToken: pair.refresh_token,
          user: pair.user,
        }),
      setAccessToken: (token) => set({ accessToken: token }),
      setUser: (user) => set({ user }),
      clear: () => set({ accessToken: null, refreshToken: null, user: null }),
    }),
    {
      name: 'mp:auth',
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({
        accessToken: state.accessToken,
        refreshToken: state.refreshToken,
        user: state.user,
      }),
    },
  ),
);

export function isAuthenticated(): boolean {
  return Boolean(useAuthStore.getState().accessToken);
}
