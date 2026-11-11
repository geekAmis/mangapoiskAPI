import { useCallback } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import { useAuthStore } from '../stores/auth';
import { toast } from '../stores/toast';

export function useLogout() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const refreshToken = useAuthStore((state) => state.refreshToken);

  return useCallback(async () => {
    if (refreshToken) {
      try {
        await api.logout(refreshToken);
      } catch {
        /* даже при недоступном сервере локальная сессия должна завершиться */
      }
    }
    useAuthStore.getState().clear();
    queryClient.clear();
    toast.info('Вы вышли из аккаунта');
    navigate('/');
  }, [navigate, queryClient, refreshToken]);
}
