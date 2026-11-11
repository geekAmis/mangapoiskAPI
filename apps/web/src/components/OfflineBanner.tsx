import { useEffect, useState } from 'react';
import { Capacitor } from '@capacitor/core';
import { Network } from '@capacitor/network';
import { Icon } from './Icon';

/** Тонкая полоса «нет сети» только в нативном приложении. */
export function OfflineBanner() {
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    if (!Capacitor.isNativePlatform()) return;
    let removed = false;
    let removeListener: (() => void) | undefined;

    void Network.getStatus()
      .then((status) => {
        if (!removed) setOffline(!status.connected);
      })
      .catch(() => undefined);

    void Network.addListener('networkStatusChange', (status) => {
      setOffline(!status.connected);
    })
      .then((handle) => {
        if (removed) void handle.remove();
        else removeListener = () => void handle.remove();
      })
      .catch(() => undefined);

    return () => {
      removed = true;
      removeListener?.();
    };
  }, []);

  if (!offline) return null;

  return (
    <div className="offline-banner" role="status">
      <Icon name="alert" size={15} />
      <span>Нет сети — показаны сохранённые данные</span>
    </div>
  );
}
