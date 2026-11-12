import { useRef, type KeyboardEvent } from 'react';
import { Icon } from '../../components/Icon';
import { ADMIN_TABS, adminTabDefinition, type AdminTabId } from './tabs';

export interface AdminTabBadge {
  count: number;
  tone?: 'accent' | 'danger' | 'warning';
}

interface AdminTabsProps {
  active: AdminTabId;
  onChange: (tab: AdminTabId) => void;
  badges?: Partial<Record<AdminTabId, AdminTabBadge>>;
}

export function AdminTabs({ active, onChange, badges = {} }: AdminTabsProps) {
  const buttons = useRef<Partial<Record<AdminTabId, HTMLButtonElement | null>>>({});
  const current = adminTabDefinition(active);

  const move = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    let nextIndex: number | null = null;
    if (event.key === 'ArrowRight') nextIndex = (index + 1) % ADMIN_TABS.length;
    if (event.key === 'ArrowLeft') nextIndex = (index - 1 + ADMIN_TABS.length) % ADMIN_TABS.length;
    if (event.key === 'Home') nextIndex = 0;
    if (event.key === 'End') nextIndex = ADMIN_TABS.length - 1;
    if (nextIndex === null) return;
    event.preventDefault();
    const next = ADMIN_TABS[nextIndex];
    onChange(next.id);
    buttons.current[next.id]?.focus();
  };

  return (
    <div className="admin-tabs" aria-label="Разделы админки">
      <div className="admin-tabs__mobile">
        <label className="admin-tabs__select-label" htmlFor="admin-tab-select">
          Раздел
        </label>
        <div className="admin-tabs__select-wrap">
          <select
            id="admin-tab-select"
            className="input admin-tabs__select"
            value={active}
            onChange={(event) => onChange(event.target.value as AdminTabId)}
          >
            {ADMIN_TABS.map((tab) => {
              const badge = badges[tab.id];
              return (
                <option key={tab.id} value={tab.id}>
                  {tab.label}
                  {badge && badge.count > 0 ? ` (${badge.count})` : ''}
                </option>
              );
            })}
          </select>
          <Icon name="chevron-down" size={16} className="admin-tabs__select-icon" />
        </div>
      </div>

      <div className="admin-tabs__list" role="tablist" aria-orientation="horizontal">
        {ADMIN_TABS.map((tab, index) => {
          const selected = tab.id === active;
          const badge = badges[tab.id];
          return (
            <button
              key={tab.id}
              ref={(node) => {
                buttons.current[tab.id] = node;
              }}
              type="button"
              role="tab"
              id={`admin-tab-${tab.id}`}
              aria-selected={selected}
              aria-controls={`admin-panel-${tab.id}`}
              tabIndex={selected ? 0 : -1}
              className={`admin-tab${selected ? ' is-active' : ''}`}
              onClick={() => onChange(tab.id)}
              onKeyDown={(event) => move(event, index)}
            >
              <Icon name={tab.icon} size={16} />
              <span>{tab.label}</span>
              {badge && badge.count > 0 ? (
                <span className={`admin-tab__badge admin-tab__badge--${badge.tone ?? 'accent'}`}>
                  {badge.count > 99 ? '99+' : badge.count}
                </span>
              ) : null}
            </button>
          );
        })}
      </div>

      <p className="admin-tabs__hint">{current.description}</p>
    </div>
  );
}
