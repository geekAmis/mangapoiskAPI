import { useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { api, isApiError } from '../api/client';
import { AuthLayout } from '../components/AuthLayout';
import { DancingSpinner } from '../components/DancingLoader';
import { Icon } from '../components/Icon';
import { safeNextPath } from '../lib/format';
import { useSeo } from '../lib/seo';
import { useAuthStore } from '../stores/auth';
import { toast } from '../stores/toast';

const ERROR_MESSAGES: Record<string, string> = {
  access_denied: 'Вы отменили вход через Яндекс. Можно попробовать снова или войти по email.',
  state_invalid: 'Ссылка входа устарела или уже использована. Начните вход заново.',
  code_invalid: 'Код входа Яндекса истёк. Начните вход заново.',
  email_missing:
    'Яндекс не вернул подтверждённый email. Разрешите доступ к email в настройках Яндекс ID и попробуйте снова.',
  account_conflict:
    'Этот email уже привязан к другому аккаунту. Войдите по email или обратитесь в поддержку.',
  account_disabled: 'Аккаунт отключён. Обратитесь в поддержку.',
  yandex_unavailable: 'Яндекс временно недоступен. Попробуйте через минуту.',
  not_configured: 'Вход через Яндекс сейчас недоступен. Используйте вход по email.',
  invalid_request: 'Некорректная ссылка входа. Начните вход заново.',
  handoff_invalid: 'Ссылка входа устарела. Начните вход заново.',
  yandex_failed: 'Не удалось войти через Яндекс. Попробуйте ещё раз.',
};

function finishErrorMessage(error: unknown, fallbackCode: string | null): string {
  if (isApiError(error)) {
    if (error.status === 0) {
      return 'Нет соединения с сервером. Проверьте интернет и попробуйте снова.';
    }
    if (error.code && ERROR_MESSAGES[error.code]) return ERROR_MESSAGES[error.code];
    if (error.status === 429) {
      return 'Слишком много попыток входа. Подождите минуту и попробуйте снова.';
    }
    if (error.status >= 500) {
      return 'Сервер временно недоступен. Попробуйте чуть позже.';
    }
  }
  return (fallbackCode && ERROR_MESSAGES[fallbackCode]) || ERROR_MESSAGES.yandex_failed;
}

export default function YandexFinishPage() {
  useSeo({
    title: 'Вход через Яндекс — MangaPoisk Reborn',
    description: 'Завершаем вход через Яндекс ID.',
    canonical: null,
    robots: 'noindex,nofollow',
  });

  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const started = useRef(false);
  const [status, setStatus] = useState<'pending' | 'error'>('pending');
  const [message, setMessage] = useState('');

  const code = searchParams.get('code');
  const errorCode = searchParams.get('error');
  const nextPath = safeNextPath(searchParams.get('next'));
  const loginHref =
    nextPath !== '/' ? `/login?next=${encodeURIComponent(nextPath)}` : '/login';

  useEffect(() => {
    // React StrictMode runs effects twice in development.  A handoff code is
    // single-use, so the second exchange must never be sent.
    if (started.current) return;
    started.current = true;

    if (errorCode) {
      const text = ERROR_MESSAGES[errorCode] || ERROR_MESSAGES.yandex_failed;
      setStatus('error');
      setMessage(text);
      toast.error(text);
      return;
    }
    if (!code) {
      const text = ERROR_MESSAGES.invalid_request;
      setStatus('error');
      setMessage(text);
      toast.error(text);
      return;
    }

    api
      .yandexExchange(code)
      .then((pair) => {
        queryClient.clear();
        useAuthStore.getState().setSession(pair);
        toast.success('Вы вошли через Яндекс');
        navigate(nextPath, { replace: true });
      })
      .catch((error: unknown) => {
        const text = finishErrorMessage(error, errorCode);
        setStatus('error');
        setMessage(text);
        toast.error(text);
      });
  }, [code, errorCode, nextPath, navigate, queryClient]);

  return (
    <AuthLayout>
      <div className="auth-card auth-finish">
        {status === 'pending' ? (
          <>
            <div className="auth-finish__icon" aria-hidden="true">
              <DancingSpinner size={30} />
            </div>
            <h1 className="auth-card__title">Завершаем вход</h1>
            <p className="auth-card__subtitle">
              Проверяем ответ Яндекса и создаём вашу сессию. Это займёт пару секунд.
            </p>
          </>
        ) : (
          <>
            <div className="auth-finish__icon auth-finish__icon--error" aria-hidden="true">
              <Icon name="alert" size={26} />
            </div>
            <h1 className="auth-card__title">Не удалось войти</h1>
            <p className="auth-card__subtitle" role="alert">
              {message}
            </p>
            <div className="auth-finish__actions">
              <Link className="btn btn--primary btn--lg btn--block" to={loginHref}>
                <Icon name="arrow-left" size={18} />
                Вернуться ко входу
              </Link>
              <Link className="btn btn--outline btn--lg btn--block" to="/">
                На главную
              </Link>
            </div>
          </>
        )}
      </div>
    </AuthLayout>
  );
}
