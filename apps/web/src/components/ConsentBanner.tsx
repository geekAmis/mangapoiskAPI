import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ADS_CONSENT_OPEN_EVENT, setAdsConsent, useAdsConsent } from '../api/ads';

/**
 * Small first-party cookie/statistics banner.  It is intentionally not a
 * modal and does not lock scrolling: reading stays available while the reader
 * decides.  The choice is stored in localStorage['mp-ads-consent'] for
 * compatibility; ads are not gated globally, only slots with
 * require_consent=true respect it.
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
    <aside className="consent-banner" role="region" aria-label="Cookie и статистика">
      <div className="consent-banner__body">
        <strong>Cookie</strong>
        <p>
          Используем cookie для входа, настроек и статистики.{' '}
          <Link to="/privacy">Политика</Link>.
        </p>
      </div>
      <div className="consent-banner__actions">
        <button type="button" className="btn btn--primary btn--sm" onClick={() => choose(true)}>
          Принять
        </button>
        <button type="button" className="btn btn--outline btn--sm" onClick={() => choose(false)}>
          Только необходимые
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
      ? 'Разрешено'
      : consent === 'denied'
        ? 'Только необходимые'
        : 'Выбор не сделан';

  return (
    <div className="consent-controls">
      <div className="consent-controls__status">
        <strong>Cookie и статистика</strong>
        <span>{label}. Выбор хранится только в этом браузере.</span>
      </div>
      <div className="consent-controls__actions">
        <button
          type="button"
          className="btn btn--primary btn--sm"
          onClick={() => setAdsConsent(true)}
        >
          Разрешить
        </button>
        <button
          type="button"
          className="btn btn--outline btn--sm"
          onClick={() => setAdsConsent(false)}
        >
          Только необходимые
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
