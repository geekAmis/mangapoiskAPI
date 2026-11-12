import { useEffect, useRef, useState } from 'react';
import { Link, NavLink, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { useOnClickOutside } from '../../lib/hooks';
import { useLogout } from '../../lib/useLogout';
import { useAuthStore } from '../../stores/auth';
import { initials } from '../../lib/format';
import { Brand } from '../Brand';
import { Icon } from '../Icon';
import { NotificationsBell } from '../NotificationsBell';
import { SearchBox } from '../SearchBox';
import { ThemeSwitcher } from '../ThemeSwitcher';

const NAV_ITEMS: Array<{ to: string; label: string; end?: boolean }> = [
  { to: '/', label: 'Главная', end: true },
  { to: '/catalogue', label: 'Каталог' },
  { to: '/library', label: 'Библиотека' },
  { to: '/sources', label: 'Источники' },
];

export function Header() {
  const user = useAuthStore((state) => state.user);
  const location = useLocation();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const logout = useLogout();
  const [mobileSearchOpen, setMobileSearchOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useOnClickOutside(menuRef, () => setMenuOpen(false), menuOpen);

  useEffect(() => {
    setMenuOpen(false);
    setMobileSearchOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    if (!mobileSearchOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setMobileSearchOpen(false);
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [mobileSearchOpen]);

  const isCataloguePath = location.pathname === '/catalogue' || location.pathname === '/catalog';
  const currentQuery = isCataloguePath ? (searchParams.get('q') ?? '') : '';

  const submitSearch = (value: string) => {
    setMobileSearchOpen(false);
    if (value) {
      navigate(`/catalogue?q=${encodeURIComponent(value)}`);
    } else {
      navigate('/catalogue');
    }
  };

  return (
    <header className="site-header">
      <div className="site-header__inner">
        <Brand />

        <nav className="site-nav" aria-label="Основная навигация">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `site-nav__link${
                  isActive || (item.to === '/catalogue' && isCataloguePath) ? ' is-active' : ''
                }`
              }
              aria-current={item.to === '/catalogue' && isCataloguePath ? 'page' : undefined}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="site-header__search">
          <SearchBox value={currentQuery} onSubmit={submitSearch} ariaLabel="Поиск по каталогу" />
        </div>

        <div className="site-header__actions">
          <ThemeSwitcher />

          <button
            type="button"
            className="btn btn--ghost btn--icon mobile-search-toggle"
            onClick={() => setMobileSearchOpen((value) => !value)}
            aria-label={mobileSearchOpen ? 'Закрыть поиск' : 'Открыть поиск'}
            aria-expanded={mobileSearchOpen}
          >
            <Icon name={mobileSearchOpen ? 'close' : 'search'} size={20} />
          </button>

          {user ? (
            <>
              <NotificationsBell />
              <div className="account-menu" ref={menuRef}>
              <button
                type="button"
                className="account-button"
                onClick={() => setMenuOpen((value) => !value)}
                aria-haspopup="menu"
                aria-expanded={menuOpen}
                aria-label="Меню аккаунта"
              >
                <span className="avatar" aria-hidden="true">
                  {initials(user.display_name)}
                </span>
                <span className="account-button__name">{user.display_name}</span>
                <Icon name="chevron-down" size={15} className="account-button__chevron" />
              </button>
              {menuOpen ? (
                <div className="account-popover" role="menu" aria-label="Аккаунт">
                  <div className="account-popover__head">
                    <span className="account-popover__name">{user.display_name}</span>
                    <span className="account-popover__email">{user.email}</span>
                  </div>
                  <Link to="/profile" className="account-popover__item" role="menuitem">
                    <Icon name="user" size={17} />
                    Профиль и настройки
                  </Link>
                  <Link to="/library" className="account-popover__item" role="menuitem">
                    <Icon name="bookmark" size={17} />
                    Моя библиотека
                  </Link>
                  <button
                    type="button"
                    className="account-popover__item account-popover__item--danger"
                    role="menuitem"
                    onClick={() => {
                      setMenuOpen(false);
                      void logout();
                    }}
                  >
                    <Icon name="logout" size={17} />
                    Выйти
                  </button>
                </div>
              ) : null}
            </div>
            </>
          ) : (
            <Link to="/login" className="btn btn--outline btn--sm header-login">
              <Icon name="user" size={16} />
              <span>Войти</span>
            </Link>
          )}
        </div>
      </div>

      {mobileSearchOpen ? (
        <div className="mobile-search">
          <SearchBox
            value={currentQuery}
            onSubmit={submitSearch}
            autoFocus
            ariaLabel="Поиск по каталогу"
            placeholder="Что будем читать?"
          />
          <button
            type="button"
            className="btn btn--ghost btn--icon"
            onClick={() => setMobileSearchOpen(false)}
            aria-label="Закрыть поиск"
          >
            <Icon name="close" size={20} />
          </button>
        </div>
      ) : null}
    </header>
  );
}
