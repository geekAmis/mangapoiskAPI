import { useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { hydrateQueryCache, startQueryCachePersistence } from '../api/cache';

/**
 * Восстанавливает устройство-локальный кэш при старте и сохраняет свежие
 * публичные ответы. Компонент ничего не рисует и безопасен на вебе.
 */
export function QueryCacheBridge() {
  const queryClient = useQueryClient();

  useEffect(() => {
    let active = true;
    void hydrateQueryCache(queryClient).then(() => {
      if (active) startQueryCachePersistence(queryClient);
    });
    return () => {
      active = false;
    };
  }, [queryClient]);

  return null;
}
