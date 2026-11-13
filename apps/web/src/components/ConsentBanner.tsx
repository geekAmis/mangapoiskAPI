import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ADS_CONSENT_OPEN_EVENT, setAdsConsent, useAdsConsent } from '../api/ads';

/**
 * Small first-party consent banner.  It is intentionally not a modal and does
 * not lock scrolling: reading stays available while the reader decides.
 * The choice is stored in localStorage['mp-ads-consent'] and ad slots with
 * require_consent=true stay hidden until it is "granted".
 */
export function ConsentBanner() {
  const consent = useAdsConsent();
  const [forceOpen, setForceOpen] = useState(false);

  useEffect(() => {
    const open = () => setForceOpen(true);
    window.addEventListener(ADS_CONSENT_OPEN_EVENT, open);
    return () => window.removeEventListener(ADS_CONSENT_OPEN_EVENT, open);
  }, []);

  const visible = forceOpen || consent === null;

  useEffect(() => {
    if (!visible) return;
    document.body.classList.add('has-consent-banner');
    return () => document.body.classList.remove('has-consent-banner');
  }, [visible]);

  if (!visible) return null;

  const choose = (granted: boolean) => {
    setAdsConsent(granted);
    setForceOpen(false);
  };

  return (
    <aside className="consent-banner" role="region" aria-label="Согласие на cookie и рекламу">
      <div className="consent-banner__body">
        <strong>Cookie и реклама</strong>
        <p>
          Мы используем необходимые cookie и локальное хранилище для входа,
          настроек и анонимной статистики. Рекламные блоки, которым нужно
          согласие, показываются только после вашего разрешения.{' '}
          <Link to="/privacy">Подробнее в политике</Link>.
        </p>
      </div>
      <div className="consent-banner__actions">
        <button type="button" className="btn btn--primary btn--sm" onClick={() => choose(true)}>
          Принять
        </button>
        <button type="button" className="btn btn--outline btn--sm" onClick={() => choose(false)}>
          Отклонить
        </button>
      </div>
    </aside>
  );
}

/** Reusable controls for the privacy page: change or revoke a stored choice. */
export function ConsentControls() {
  const consent = useAdsConsent();
  const label =
    consent === 'granted'
      ? 'Реклама разрешена'
      : consent === 'denied'
        ? 'Реклама отклонена'
        : 'Выбор ещё не сделан';

  return (
    <div className="consent-controls">
      <div className="consent-controls__status">
        <strong>Реклама и cookie</strong>
        <span>{label}. Выбор хранится только в этом браузере.</span>
      </div>
      <div className="consent-controls__actions">
        <button
          type="button"
          className="btn btn--primary btn--sm"
          onClick={() => setAdsConsent(true)}
        >
          Разрешить рекламу
        </button>
        <button
          type="button"
          className="btn btn--outline btn--sm"
          onClick={() => setAdsConsent(false)}
        >
          Отозвать согласие
        </button>
        <button
          type="button"
          className="btn btn--ghost btn--sm"
          onClick={() => {
            window.dispatchEvent(new Event(ADS_CONSENT_OPEN_EVENT));
          }}
        >
          Показать баннер
        </button>
      </div>
    </div>
  );
}
