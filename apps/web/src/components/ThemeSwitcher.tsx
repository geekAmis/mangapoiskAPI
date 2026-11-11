import { useState, type CSSProperties } from 'react';
import { getThemeMeta, THEMES, useThemeStore, type ThemeId } from '../stores/theme';
import { Icon } from './Icon';
import { Modal } from './Modal';

function themeStyle(theme: ThemeId): CSSProperties {
  const meta = getThemeMeta(theme);
  return {
    '--swatch-bg': meta.bg,
    '--swatch-accent': meta.accent,
  } as CSSProperties;
}

export function ThemeSwitcher() {
  const theme = useThemeStore((state) => state.theme);
  const [open, setOpen] = useState(false);
  const meta = getThemeMeta(theme);

  return (
    <>
      <button
        type="button"
        className="btn btn--ghost btn--icon theme-switcher__trigger"
        onClick={() => setOpen(true)}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={`Сменить оформление: ${meta.name}`}
        title={`Оформление: ${meta.name}`}
      >
        <Icon name="palette" size={20} />
      </button>
      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="Оформление"
        description="Шесть настроений для чтения. Тема применяется сразу и сохраняется в профиле."
        size="theme"
        variant="sheet"
        footer={
          <button type="button" className="btn btn--primary" onClick={() => setOpen(false)}>
            Готово
          </button>
        }
      >
        <div className="theme-dialog">
          <ThemePicker />
          <p className="theme-dialog__note">
            <Icon name="palette" size={15} />
            Иллюстрация темы используется только на главной, страницах входа и 404 — никогда за
            текстом или в читалке.
          </p>
        </div>
      </Modal>
    </>
  );
}

export function ThemePicker({ compact = false }: { compact?: boolean }) {
  const theme = useThemeStore((state) => state.theme);
  const setTheme = useThemeStore((state) => state.setTheme);

  return (
    <div className={`theme-grid${compact ? ' theme-grid--compact' : ''}`} role="radiogroup" aria-label="Тема оформления">
      {THEMES.map((option) => (
        <button
          key={option.id}
          type="button"
          className={`theme-card${option.id === theme ? ' is-active' : ''}`}
          role="radio"
          aria-checked={option.id === theme}
          onClick={() => setTheme(option.id)}
        >
          <span className="theme-card__swatch" style={themeStyle(option.id)} aria-hidden="true">
            <span className="theme-card__glow" />
          </span>
          <span className="theme-card__label">
            <span>{option.name}</span>
            {!compact ? <span className="theme-card__desc">{option.description}</span> : null}
          </span>
          {option.id === theme ? (
            <span className="theme-card__check" aria-hidden="true">
              <Icon name="check" size={14} />
            </span>
          ) : null}
        </button>
      ))}
    </div>
  );
}
