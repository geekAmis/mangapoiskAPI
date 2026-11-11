import { useState, type FormEvent } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom';
import { api } from '../api/client';
import { Icon } from '../components/Icon';
import { DancingSpinner } from '../components/DancingLoader';
import { AuthLayout } from '../components/AuthLayout';
import { authErrorMessage } from '../lib/errors';
import { safeNextPath } from '../lib/format';
import { useDocumentTitle } from '../lib/hooks';
import { useAuthStore } from '../stores/auth';
import { toast } from '../stores/toast';

interface FieldErrors {
  email?: string;
  password?: string;
  form?: string;
}

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export default function LoginPage() {
  useDocumentTitle('Вход — MangaPoisk Reborn');
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const accessToken = useAuthStore((state) => state.accessToken);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [errors, setErrors] = useState<FieldErrors>({});

  const nextPath = safeNextPath(searchParams.get('next'));
  const registerHref = nextPath !== '/' ? `/register?next=${encodeURIComponent(nextPath)}` : '/register';

  const mutation = useMutation({
    mutationFn: () => api.login({ email: email.trim(), password }),
    onSuccess: (pair) => {
      queryClient.clear();
      useAuthStore.getState().setSession(pair);
      toast.success('С возвращением!');
      navigate(nextPath, { replace: true });
    },
    onError: (error: unknown) => {
      setErrors({ form: authErrorMessage(error, 'login') });
    },
  });

  if (accessToken) {
    return <Navigate to={nextPath} replace />;
  }

  const validate = (): boolean => {
    const nextErrors: FieldErrors = {};
    if (!email.trim()) nextErrors.email = 'Введите email.';
    else if (!EMAIL_PATTERN.test(email.trim())) nextErrors.email = 'Похоже, это не email.';
    if (!password) nextErrors.password = 'Введите пароль.';
    setErrors(nextErrors);
    return Object.keys(nextErrors).length === 0;
  };

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!validate()) return;
    mutation.mutate();
  };

  return (
    <AuthLayout>
      <div className="auth-card">
        <div className="auth-card__head">
          <span className="eyebrow">Личный кабинет</span>
          <h1 className="auth-card__title">С возвращением</h1>
          <p className="auth-card__subtitle">
            Войдите, чтобы синхронизировать закладки, историю и настройки читалки.
          </p>
        </div>

        <form className="auth-form" onSubmit={onSubmit} noValidate>
          {errors.form ? (
            <div className="form-alert" role="alert">
              <Icon name="alert" size={17} />
              <span>{errors.form}</span>
            </div>
          ) : null}

          <div className="field">
            <label className="field__label" htmlFor="login-email">
              Email
            </label>
            <input
              id="login-email"
              className="input"
              type="email"
              inputMode="email"
              autoComplete="email"
              placeholder="you@example.com"
              value={email}
              onChange={(event) => {
                setEmail(event.target.value);
                setErrors((current) => ({ ...current, email: undefined, form: undefined }));
              }}
              aria-invalid={Boolean(errors.email)}
              aria-describedby={errors.email ? 'login-email-error' : undefined}
            />
            {errors.email ? (
              <span className="field__error" id="login-email-error">
                {errors.email}
              </span>
            ) : null}
          </div>

          <div className="field">
            <label className="field__label" htmlFor="login-password">
              Пароль
            </label>
            <div className="password-field">
              <input
                id="login-password"
                className="input"
                type={showPassword ? 'text' : 'password'}
                autoComplete="current-password"
                placeholder="Ваш пароль"
                value={password}
                onChange={(event) => {
                  setPassword(event.target.value);
                  setErrors((current) => ({ ...current, password: undefined, form: undefined }));
                }}
                aria-invalid={Boolean(errors.password)}
                aria-describedby={errors.password ? 'login-password-error' : undefined}
              />
              <button
                type="button"
                className="password-field__toggle"
                onClick={() => setShowPassword((value) => !value)}
                aria-label={showPassword ? 'Скрыть пароль' : 'Показать пароль'}
                aria-pressed={showPassword}
              >
                <Icon name={showPassword ? 'eye-off' : 'eye'} size={18} />
              </button>
            </div>
            {errors.password ? (
              <span className="field__error" id="login-password-error">
                {errors.password}
              </span>
            ) : null}
          </div>

          <button
            type="submit"
            className="btn btn--primary btn--lg btn--block"
            disabled={mutation.isPending}
          >
            {mutation.isPending ? (
              <>
                <DancingSpinner size={18} />
                Входим…
              </>
            ) : (
              <>
                <Icon name="lock" size={18} />
                Войти
              </>
            )}
          </button>
        </form>

        <div className="auth-switch">
          Нет аккаунта? <Link to={registerHref}>Создать бесплатно</Link>
        </div>
      </div>
    </AuthLayout>
  );
}
