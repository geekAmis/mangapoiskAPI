import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api, yandexStartUrl } from '../api/client';
import { DancingSpinner } from './DancingLoader';

/**
 * "Войти через Яндекс" button.
 *
 * The button is only rendered when the backend reports that all Yandex OAuth
 * settings are present.  A disabled placeholder keeps the card height stable
 * while the provider flag is loading, so configured deployments do not jump.
 */
export function YandexAuthButton({ nextPath }: { nextPath: string }) {
  const [redirecting, setRedirecting] = useState(false);
  const providers = useQuery({
    queryKey: ['auth', 'providers'],
    queryFn: ({ signal }) => api.authProviders(signal),
    staleTime: 5 * 60_000,
    retry: 1,
    refetchOnWindowFocus: false,
  });

  if (!providers.isLoading && !providers.data?.yandex) return null;

  const enabled = Boolean(providers.data?.yandex);
  const onClick = () => {
    if (!enabled || redirecting) return;
    setRedirecting(true);
    // A top-level navigation is required: the start endpoint answers with a
    // 302 to oauth.yandex.ru and must not be followed by fetch().
    window.location.assign(yandexStartUrl(nextPath));
  };

  return (
    <div className="auth-oauth">
      <div className="auth-oauth__divider" aria-hidden="true">
        <span>или</span>
      </div>
      <button
        type="button"
        className="btn btn--yandex btn--lg btn--block"
        onClick={onClick}
        disabled={!enabled || redirecting}
        aria-busy={redirecting}
      >
        {redirecting ? (
          <DancingSpinner size={18} />
        ) : (
          <span className="auth-oauth__mark" aria-hidden="true">
            Я
          </span>
        )}
        {redirecting ? 'Переходим в Яндекс…' : 'Войти через Яндекс'}
      </button>
    </div>
  );
}
