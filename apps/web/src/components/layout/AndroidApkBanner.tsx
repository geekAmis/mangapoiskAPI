import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Icon } from '../Icon';

const APK_URL =
  'https://github.com/geekAmis/mangapoiskAPI/releases/latest/download/mangapoisk-reborn.apk';
const DISMISS_KEY = 'mp:android-apk-banner';
const DISMISS_MS = 7 * 24 * 60 * 60 * 1000;

export function AndroidApkBanner() {
  const [visible, setVisible] = useState(false);
  const bannerRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!/Android/i.test(navigator.userAgent)) return;
    try {
      const dismissedAt = Number(localStorage.getItem(DISMISS_KEY) || 0);
      if (dismissedAt && Date.now() - dismissedAt < DISMISS_MS) return;
    } catch {
      /* приватный режим: показываем баннер */
    }
    const timer = window.setTimeout(() => setVisible(true), 1400);
    return () => window.clearTimeout(timer);
  }, []);

  // Пока баннер виден, резервируем место под него в конце страницы —
  // фиксированная плашка не должна перекрывать нижние действия. Высоту
  // измеряем, чтобы padding совпадал с фактическим размером на 360/390px.
  useLayoutEffect(() => {
    if (!visible) return;
    const body = document.body;
    const root = document.documentElement;
    const banner = bannerRef.current;
    body.classList.add('has-apk-banner');

    const syncHeight = () => {
      if (!banner) return;
      root.style.setProperty(
        '--apk-banner-height',
        `${Math.ceil(banner.getBoundingClientRect().height)}px`,
      );
    };

    syncHeight();
    const observer =
      typeof ResizeObserver === 'function' ? new ResizeObserver(syncHeight) : null;
    if (banner && observer) observer.observe(banner);
    window.addEventListener('resize', syncHeight);

    return () => {
      observer?.disconnect();
      window.removeEventListener('resize', syncHeight);
      body.classList.remove('has-apk-banner');
      root.style.removeProperty('--apk-banner-height');
    };
  }, [visible]);

  if (!visible) return null;

  const dismiss = () => {
    setVisible(false);
    try {
      localStorage.setItem(DISMISS_KEY, String(Date.now()));
    } catch {
      /* ignore */
    }
  };

  return (
    <aside
      ref={bannerRef}
      className="apk-banner"
      role="complementary"
      aria-label="Android-приложение"
    >
      <span className="apk-banner__mark" aria-hidden="true">
        <Icon name="download" size={20} />
      </span>
      <div className="apk-banner__body">
        <strong>Есть Android-приложение</strong>
        <span>Свежий APK на GitHub. Офлайн-главы хранятся в памяти приложения.</span>
      </div>
      <a
        className="btn btn--primary btn--sm apk-banner__action"
        href={APK_URL}
        target="_blank"
        rel="noopener noreferrer"
        onClick={dismiss}
      >
        <Icon name="download" size={15} />
        Скачать APK
      </a>
      <button
        type="button"
        className="apk-banner__close"
        onClick={dismiss}
        aria-label="Закрыть уведомление"
        title="Закрыть"
      >
        <Icon name="close" size={16} />
      </button>
    </aside>
  );
}
