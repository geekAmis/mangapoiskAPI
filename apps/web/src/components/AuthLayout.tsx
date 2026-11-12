import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { Brand } from './Brand';
import { ConsentBanner } from './ConsentBanner';
import { Icon } from './Icon';

export function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="auth-page">
      <div className="auth-page__media" aria-hidden="true" />
      <div className="auth-page__media-caption">
        <strong>Шесть настроений. Одна библиотека.</strong>
        <span>Атмосфера, которая не мешает читать: выберите тему и оставайтесь в ней.</span>
      </div>
      <div className="auth-page__content">
        <div className="auth-shell">
          <div className="auth-shell__brand">
            <Brand />
            <Link to="/" className="auth-back">
              <Icon name="arrow-left" size={15} />
              На главную
            </Link>
          </div>
          {children}
          <p className="auth-legal">
            MangaPoisk Reborn хранит только email, имя и настройки чтения. Пароль защищён
            Argon2id на сервере, токены — в этом браузере. Используя сервис, вы принимаете{' '}
            <Link to="/terms">Пользовательское соглашение</Link> и{' '}
            <Link to="/privacy">Политику конфиденциальности</Link>. Сервис предназначен для
            пользователей <Link to="/age">18+</Link>.
          </p>
        </div>
      </div>
      <ConsentBanner />
    </div>
  );
}
