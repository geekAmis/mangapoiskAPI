import { useState, type FormEvent } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom';
import { api } from '../api/client';
import { Icon } from '../components/Icon';
import { DancingSpinner } from '../components/DancingLoader';
import { AuthLayout } from '../components/AuthLayout';
import { authErrorMessage } from '../lib/errors';
import { safeNextPath } from '../lib/format';
import { useSeo } from '../lib/seo';
import { useAuthStore } from '../stores/auth';
import { toast } from '../stores/toast';

interface FieldErrors {
  displayName?: string;
  email?: string;
  password?: string;
  confirm?: string;
  age?: string;
  terms?: string;
  form?: string;
}

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export default function RegisterPage() {
  useSeo({
    title: 'Регистрация — MangaPoisk Reborn',
    description: 'Создайте аккаунт MangaPoisk Reborn, чтобы сохранять закладки, историю чтения и прогресс на всех устройствах.',
    canonical: null,
    robots: 'noindex,nofollow',
  });
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const accessToken = useAuthStore((state) => state.accessToken);
  const [displayName, setDisplayName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [ageConfirmed, setAgeConfirmed] = useState(false);
  const [termsAccepted, setTermsAccepted] = useState(false);
  const [errors, setErrors] = useState<FieldErrors>({});

  const nextPath = safeNextPath(searchParams.get('next'));
  const loginHref = nextPath !== '/' ? `/login?next=${encodeURIComponent(nextPath)}` : '/login';

  const mutation = useMutation({
    mutationFn: () =>
      api.register({ email: email.trim(), password, display_name: displayName.trim() }),
    onSuccess: (pair) => {
      queryClient.clear();
      useAuthStore.getState().setSession(pair);
      toast.success('Аккаунт создан. Добро пожаловать!');
      navigate(nextPath, { replace: true });
    },
    onError: (error: unknown) => {
      setErrors({ form: authErrorMessage(error, 'register') });
    },
  });

  if (accessToken) {
    return <Navigate to={nextPath} replace />;
  }

  const validate = (): boolean => {
    const nextErrors: FieldErrors = {};
    const trimmedName = displayName.trim();
    if (!trimmedName) nextErrors.displayName = 'Введите имя или никнейм.';
    else if (trimmedName.length < 2) nextErrors.displayName = 'Минимум 2 символа.';
    else if (trimmedName.length > 64) nextErrors.displayName = 'Не больше 64 символов.';

    if (!email.trim()) nextErrors.email = 'Введите email.';
    else if (!EMAIL_PATTERN.test(email.trim())) nextErrors.email = 'Похоже, это не email.';

    if (!password) nextErrors.password = 'Придумайте пароль.';
    else if (password.length < 8) nextErrors.password = 'Пароль должен быть не короче 8 символов.';
    else if (password.length > 128) nextErrors.password = 'Пароль слишком длинный.';

    if (!confirm) nextErrors.confirm = 'Повторите пароль.';
    else if (confirm !== password) nextErrors.confirm = 'Пароли не совпадают.';

    if (!ageConfirmed) {
      nextErrors.age = 'Подтвердите, что вам 18 лет или больше.';
    }
    if (!termsAccepted) {
      nextErrors.terms =
        'Примите Пользовательское соглашение и Политику конфиденциальности.';
    }

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
          <span className="eyebrow">Новый читатель</span>
          <h1 className="auth-card__title">Создать аккаунт</h1>
          <p className="auth-card__subtitle">
            Закладки, история чтения и настройки будут доступны на всех ваших устройствах.
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
            <label className="field__label" htmlFor="register-name">
              Имя или никнейм
            </label>
            <input
              id="register-name"
              className="input"
              type="text"
              autoComplete="nickname"
              maxLength={64}
              placeholder="Как к вам обращаться?"
              value={displayName}
              onChange={(event) => {
                setDisplayName(event.target.value);
                setErrors((current) => ({ ...current, displayName: undefined, form: undefined }));
              }}
              aria-invalid={Boolean(errors.displayName)}
              aria-describedby={errors.displayName ? 'register-name-error' : undefined}
            />
            {errors.displayName ? (
              <span className="field__error" id="register-name-error">
                {errors.displayName}
              </span>
            ) : null}
          </div>

          <div className="field">
            <label className="field__label" htmlFor="register-email">
              Email
            </label>
            <input
              id="register-email"
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
              aria-describedby={errors.email ? 'register-email-error' : undefined}
            />
            {errors.email ? (
              <span className="field__error" id="register-email-error">
                {errors.email}
              </span>
            ) : null}
          </div>

          <div className="field-row">
            <div className="field">
              <label className="field__label" htmlFor="register-password">
                Пароль
              </label>
              <div className="password-field">
                <input
                  id="register-password"
                  className="input"
                  type={showPassword ? 'text' : 'password'}
                  autoComplete="new-password"
                  placeholder="Минимум 8 символов"
                  value={password}
                  onChange={(event) => {
                    setPassword(event.target.value);
                    setErrors((current) => ({ ...current, password: undefined, form: undefined }));
                  }}
                  aria-invalid={Boolean(errors.password)}
                  aria-describedby={errors.password ? 'register-password-error' : 'register-password-hint'}
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
                <span className="field__error" id="register-password-error">
                  {errors.password}
                </span>
              ) : (
                <span className="field__hint" id="register-password-hint">
                  Не менее 8 символов
                </span>
              )}
            </div>

            <div className="field">
              <label className="field__label" htmlFor="register-confirm">
                Повторите пароль
              </label>
              <input
                id="register-confirm"
                className="input"
                type={showPassword ? 'text' : 'password'}
                autoComplete="new-password"
                placeholder="Ещё раз"
                value={confirm}
                onChange={(event) => {
                  setConfirm(event.target.value);
                  setErrors((current) => ({ ...current, confirm: undefined, form: undefined }));
                }}
                aria-invalid={Boolean(errors.confirm)}
                aria-describedby={errors.confirm ? 'register-confirm-error' : undefined}
              />
              {errors.confirm ? (
                <span className="field__error" id="register-confirm-error">
                  {errors.confirm}
                </span>
              ) : null}
            </div>
          </div>

          <div className="auth-consents">
            <div className="auth-consent">
              <label className="checkbox" htmlFor="register-age">
                <input
                  id="register-age"
                  type="checkbox"
                  checked={ageConfirmed}
                  onChange={(event) => {
                    setAgeConfirmed(event.target.checked);
                    setErrors((current) => ({ ...current, age: undefined, form: undefined }));
                  }}
                  aria-invalid={Boolean(errors.age)}
                  aria-describedby={errors.age ? 'register-age-error' : undefined}
                />
                <span>
                  Мне 18 лет или больше. Я понимаю, что на сайте есть контент для
                  взрослых.
                </span>
              </label>
              {errors.age ? (
                <span className="field__error" id="register-age-error" role="alert">
                  {errors.age}
                </span>
              ) : null}
            </div>

            <div className="auth-consent">
              <label className="checkbox" htmlFor="register-terms">
                <input
                  id="register-terms"
                  type="checkbox"
                  checked={termsAccepted}
                  onChange={(event) => {
                    setTermsAccepted(event.target.checked);
                    setErrors((current) => ({ ...current, terms: undefined, form: undefined }));
                  }}
                  aria-invalid={Boolean(errors.terms)}
                  aria-describedby={errors.terms ? 'register-terms-error' : 'register-terms-links'}
                />
                <span>
                  Я принимаю условия использования и политику конфиденциальности.
                </span>
              </label>
              {errors.terms ? (
                <span className="field__error" id="register-terms-error" role="alert">
                  {errors.terms}
                </span>
              ) : null}
              <p className="auth-consent__links" id="register-terms-links">
                <Link to="/terms" target="_blank" rel="noopener noreferrer">
                  Пользовательское соглашение
                </Link>
                <span aria-hidden="true">·</span>
                <Link to="/privacy" target="_blank" rel="noopener noreferrer">
                  Политика конфиденциальности
                </Link>
                <span aria-hidden="true">·</span>
                <Link to="/age" target="_blank" rel="noopener noreferrer">
                  Правила 18+
                </Link>
              </p>
            </div>
          </div>

          <button
            type="submit"
            className="btn btn--primary btn--lg btn--block"
            disabled={mutation.isPending}
          >
            {mutation.isPending ? (
              <>
                <DancingSpinner size={18} />
                Создаём аккаунт…
              </>
            ) : (
              <>
                <Icon name="user" size={18} />
                Зарегистрироваться
              </>
            )}
          </button>

          <div className="auth-security">
            <Icon name="shield" size={16} />
            <span>Пароль передаётся по HTTPS и хранится только в виде Argon2id-хэша.</span>
          </div>
        </form>

        <div className="auth-switch">
          Уже есть аккаунт? <Link to={loginHref}>Войти</Link>
        </div>
      </div>
    </AuthLayout>
  );
}
