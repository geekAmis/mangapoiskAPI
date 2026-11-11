import type { ReactNode } from 'react';
import { Icon } from './Icon';

interface ErrorStateProps {
  title?: string;
  message?: string;
  onRetry?: () => void;
  retryLabel?: string;
  action?: ReactNode;
  compact?: boolean;
}

export function ErrorState({
  title = 'Не удалось загрузить данные',
  message,
  onRetry,
  retryLabel = 'Повторить',
  action,
  compact = false,
}: ErrorStateProps) {
  return (
    <div className={`error-state${compact ? ' error-state--compact' : ''}`} role="alert">
      <span className="error-state__icon" aria-hidden="true">
        <Icon name="alert" size={compact ? 22 : 28} />
      </span>
      <div className="error-state__body">
        <h2 className="error-state__title">{title}</h2>
        {message ? <p className="error-state__text">{message}</p> : null}
      </div>
      <div className="error-state__actions">
        {onRetry ? (
          <button type="button" className="btn btn--outline btn--sm" onClick={onRetry}>
            <Icon name="refresh" size={16} />
            {retryLabel}
          </button>
        ) : null}
        {action}
      </div>
    </div>
  );
}

export function InlineError({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="inline-error" role="alert">
      <Icon name="alert" size={18} />
      <span>{message}</span>
      {onRetry ? (
        <button type="button" className="inline-error__retry" onClick={onRetry}>
          Повторить
        </button>
      ) : null}
    </div>
  );
}
