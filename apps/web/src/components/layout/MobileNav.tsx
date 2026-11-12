import { NavLink, useLocation } from 'react-router-dom';
import { Icon, type IconName } from '../Icon';

const ITEMS: Array<{ to: string; label: string; icon: IconName; end?: boolean }> = [
  { to: '/', label: 'Главная', icon: 'home', end: true },
  { to: '/catalogue', label: 'Каталог', icon: 'grid' },
  { to: '/library', label: 'Библиотека', icon: 'bookmark' },
  { to: '/sources', label: 'Источники', icon: 'compass' },
  { to: '/profile', label: 'Профиль', icon: 'user' },
];

export function MobileNav() {
  const location = useLocation();
  const isCataloguePath = location.pathname === '/catalogue' || location.pathname === '/catalog';

  return (
    <nav className="mobile-nav" aria-label="Мобильная навигация">
      {ITEMS.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.end}
          className={({ isActive }) =>
            `mobile-nav__item${
              isActive || (item.to === '/catalogue' && isCataloguePath) ? ' is-active' : ''
            }`
          }
          aria-label={item.label}
          title={item.label}
          aria-current={item.to === '/catalogue' && isCataloguePath ? 'page' : undefined}
        >
          <span className="mobile-nav__icon">
            <Icon name={item.icon} size={22} />
          </span>
          <span className="mobile-nav__label">{item.label}</span>
        </NavLink>
      ))}
    </nav>
  );
}
