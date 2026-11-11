import { useState, type FormEvent } from 'react';
import { useMutation } from '@tanstack/react-query';
import { adminApi, adminErrorMessage, isAdminUnauthorized, setAdminToken } from '../../api/admin';
import { Icon } from '../Icon';
import { DancingSpinner } from '../DancingLoader';

interface AdminLoginProps {
  onAuthenticated: (token: string) => void;
}

export function AdminLogin({ onAuthenticated }: AdminLoginProps) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState('');

  const mutation = useMutation({
    mutationFn: () => adminApi.login(username.trim(), password),
    onSuccess: (result) => {
      setAdminToken(result.access_token);
      setError('');
      onAuthenticated(result.access_token);
    },
    onError: (mutationError: unknown) => {
      setError(
        isAdminUnauthorized(mutationError)
          ? 'Неверный логин или пароль.'
          : adminErrorMessage(mutationError, 'Не удалось войти в панель управления.'),
      );
    },
  });

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!username.trim() || !password) {
      setError('Введите логин и пароль.');
      return;
    }
    mutation.mutate();
  };

  return (
    <div className="admin-login">
      <div className="admin-login__glow" aria-hidden="true" />
      <div className="admin-login__card">
        <div className="admin-login__brand">
          <span className="admin-brand-mark" aria-hidden="true">
            <Icon name="server" size={22} />
          </span>
          <div>
            <strong>MangaPoisk</strong>
            <span>Control</span>
          </div>
        </div>

        <div className="admin-login__head">
          <span className="admin-kicker">Закрытый контур</span>
          <h1>Панель управления</h1>
          <p>Серверы, развёртывание, health-check и маршруты gateway.</p>
        </div>

        <form className="admin-login__form" onSubmit={onSubmit}>
          {error ? (
            <div className="form-alert" role="alert">
              <Icon name="alert" size={17} />
              <span>{error}</span>
            </div>
          ) : null}

          <div className="field">
            <label className="field__label" htmlFor="admin-username">
              Логин
            </label>
            <input
              id="admin-username"
              className="input"
              autoComplete="username"
              value={username}
              onChange={(event) => {
                setUsername(event.target.value);
                setError('');
              }}
              placeholder="admin"
              aria-invalid={Boolean(error)}
              autoFocus
            />
          </div>

          <div className="field">
            <label className="field__label" htmlFor="admin-password">
              Пароль
            </label>
            <div className="password-field">
              <input
                id="admin-password"
                className="input"
                type={showPassword ? 'text' : 'password'}
                autoComplete="current-password"
                value={password}
                onChange={(event) => {
                  setPassword(event.target.value);
                  setError('');
                }}
                placeholder="Пароль администратора"
                aria-invalid={Boolean(error)}
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
          </div>

          <button type="submit" className="btn btn--primary btn--lg btn--block" disabled={mutation.isPending}>
            {mutation.isPending ? (
              <>
                <DancingSpinner size={18} />
                Проверяем…
              </>
            ) : (
              <>
                <Icon name="lock" size={18} />
                Войти
              </>
            )}
          </button>
        </form>

        <div className="admin-login__note">
          <Icon name="shield" size={15} />
          <span>
            Токен администратора хранится только в sessionStorage этой вкладки и не пересекается с
            аккаунтом читателя.
          </span>
        </div>
      </div>
      <p className="admin-login__footer">MangaPoisk Reborn · Control</p>
    </div>
  );
}
