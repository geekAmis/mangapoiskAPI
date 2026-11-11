import { useEffect, useState } from 'react';
import { Icon } from './Icon';

interface SearchBoxProps {
  value?: string;
  defaultValue?: string;
  onChange?: (value: string) => void;
  onSubmit?: (value: string) => void;
  onClear?: () => void;
  placeholder?: string;
  ariaLabel?: string;
  autoFocus?: boolean;
  className?: string;
  size?: 'md' | 'lg';
}

export function SearchBox({
  value,
  defaultValue = '',
  onChange,
  onSubmit,
  onClear,
  placeholder = 'Название манги или автор…',
  ariaLabel = 'Поиск манги',
  autoFocus = false,
  className,
  size = 'md',
}: SearchBoxProps) {
  const [local, setLocal] = useState(value ?? defaultValue);

  useEffect(() => {
    if (value !== undefined) setLocal(value);
  }, [value]);

  const update = (next: string) => {
    setLocal(next);
    onChange?.(next);
  };

  return (
    <form
      className={`searchbox${size === 'lg' ? ' searchbox--lg' : ''}${className ? ` ${className}` : ''}`}
      role="search"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit?.(local.trim());
      }}
    >
      <span className="searchbox__icon" aria-hidden="true">
        <Icon name="search" size={19} />
      </span>
      <input
        type="search"
        className="searchbox__input"
        value={local}
        onChange={(event) => update(event.target.value)}
        placeholder={placeholder}
        aria-label={ariaLabel}
        autoFocus={autoFocus}
        enterKeyHint="search"
        autoComplete="off"
        spellCheck={false}
      />
      {local ? (
        <button
          type="button"
          className="searchbox__clear"
          aria-label="Очистить поиск"
          onClick={() => {
            update('');
            onClear?.();
          }}
        >
          <Icon name="close" size={16} />
        </button>
      ) : null}
      <button type="submit" className="searchbox__submit" aria-label="Найти">
        <Icon name="search" size={18} />
      </button>
    </form>
  );
}
