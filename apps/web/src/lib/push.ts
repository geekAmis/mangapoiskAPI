import { isNativePlatform } from '../api/cache';
import { notificationsApi } from '../api/notifications';

export type PushSupportReason =
  | 'native'
  | 'insecure'
  | 'unsupported'
  | 'service_worker'
  | null;

export interface PushSupport {
  supported: boolean;
  reason: PushSupportReason;
  message: string;
}

export class PushUnavailableError extends Error {
  readonly reason: PushSupportReason;
  constructor(message: string, reason: PushSupportReason) {
    super(message);
    this.name = 'PushUnavailableError';
    this.reason = reason;
  }
}

/**
 * Android WebView (Capacitor) does not expose the Web Push API: Service Workers
 * exist, but `PushManager` requires a native FCM integration and a notification
 * channel.  We never fake native push here — the in-app bell is the fallback.
 */
export function pushSupport(): PushSupport {
  if (isNativePlatform) {
    return {
      supported: false,
      reason: 'native',
      message:
        'В Android-приложении системные Web Push недоступны. Новые главы приходят в колокольчик приложения.',
    };
  }
  if (typeof window === 'undefined') {
    return { supported: false, reason: 'unsupported', message: 'Push недоступен в этом окружении.' };
  }
  if (!window.isSecureContext) {
    return {
      supported: false,
      reason: 'insecure',
      message: 'Web Push работает только по HTTPS (или на localhost).',
    };
  }
  if (
    !('serviceWorker' in navigator) ||
    !('PushManager' in window) ||
    !('Notification' in window)
  ) {
    return {
      supported: false,
      reason: 'unsupported',
      message: 'Браузер не поддерживает Web Push. Уведомления останутся в колокольчике.',
    };
  }
  return { supported: true, reason: null, message: '' };
}

export function notificationPermission(): NotificationPermission | 'unsupported' {
  if (typeof window === 'undefined' || !('Notification' in window)) return 'unsupported';
  return Notification.permission;
}

export function urlBase64ToUint8Array(base64String: string): Uint8Array<ArrayBuffer> {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
  const rawData = window.atob(base64);
  const output = new Uint8Array(new ArrayBuffer(rawData.length));
  for (let index = 0; index < rawData.length; index += 1) {
    output[index] = rawData.charCodeAt(index);
  }
  return output;
}

async function ensureServiceWorker(): Promise<ServiceWorkerRegistration> {
  const existing = await navigator.serviceWorker.getRegistration('/');
  if (existing) return existing;
  if (!import.meta.env.PROD) {
    throw new PushUnavailableError(
      'Web Push проверяется в production-сборке: dev-сервер не регистрирует service worker.',
      'service_worker',
    );
  }
  return navigator.serviceWorker.register('/sw.js', { scope: '/' });
}

async function currentSubscription(): Promise<PushSubscription | null> {
  if (!('serviceWorker' in navigator)) return null;
  const registration = await navigator.serviceWorker.getRegistration('/');
  if (!registration) return null;
  return registration.pushManager.getSubscription();
}

export interface PushState {
  permission: NotificationPermission | 'unsupported';
  subscribed: boolean;
  endpoint: string | null;
}

export async function getPushState(): Promise<PushState> {
  const subscription = await currentSubscription().catch(() => null);
  return {
    permission: notificationPermission(),
    subscribed: Boolean(subscription),
    endpoint: subscription?.endpoint ?? null,
  };
}

export async function subscribeToPush(): Promise<PushSubscription> {
  const support = pushSupport();
  if (!support.supported) {
    throw new PushUnavailableError(support.message, support.reason);
  }

  let permission = Notification.permission;
  if (permission === 'default') {
    permission = await Notification.requestPermission();
  }
  if (permission !== 'granted') {
    throw new PushUnavailableError(
      permission === 'denied'
        ? 'Уведомления запрещены в настройках браузера. Разрешите их для MangaPoisk Reborn и попробуйте снова.'
        : 'Разрешение на уведомления не выдано.',
      'unsupported',
    );
  }

  const config = await notificationsApi.pushConfig();
  if (!config.enabled || !config.public_key) {
    throw new PushUnavailableError(
      'Web Push не настроен на сервере: администратор должен задать VAPID-ключи.',
      'unsupported',
    );
  }

  const registration = await ensureServiceWorker();
  let subscription = await registration.pushManager.getSubscription();
  if (!subscription) {
    subscription = await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(config.public_key),
    });
  }

  await notificationsApi.subscribePush(subscription.toJSON());
  return subscription;
}

export async function unsubscribeFromPush(): Promise<void> {
  const subscription = await currentSubscription();
  if (!subscription) return;
  let serverError: unknown = null;
  try {
    await notificationsApi.unsubscribePush(subscription.endpoint);
  } catch (error) {
    serverError = error;
  }
  await subscription.unsubscribe();
  if (serverError) throw serverError;
}
