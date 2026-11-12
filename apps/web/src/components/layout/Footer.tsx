import { Link } from 'react-router-dom';
import { Brand } from '../Brand';

export function Footer() {
  return (
    <footer className="site-footer">
      <div className="site-footer__inner">
        <div className="site-footer__brand">
          <Brand />
          <p>
            Русский каталог манги и манхвы. Читайте онлайн, сохраняйте закладки и скачивайте главы
            на устройство для чтения без интернета.
          </p>
        </div>
        <nav className="site-footer__nav" aria-label="Навигация в подвале">
          <div>
            <span className="site-footer__heading">Читать</span>
            <Link to="/catalogue">Каталог</Link>
            <Link to="/sources">Источники</Link>
            <Link to="/library">Библиотека</Link>
          </div>
          <div>
            <span className="site-footer__heading">Аккаунт</span>
            <Link to="/login">Вход</Link>
            <Link to="/register">Регистрация</Link>
            <Link to="/profile">Настройки</Link>
          </div>
        </nav>
      </div>
      <div className="site-footer__legal">
        <span>© {new Date().getFullYear()} MangaPoisk Reborn</span>
        <span>
          Каталог хранит метаданные и ссылки на страницы. Права на произведения принадлежат их
          авторам и правообладателям.
        </span>
      </div>
    </footer>
  );
}
