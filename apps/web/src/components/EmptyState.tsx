import type { ReactNode } from 'react';
import { Icon, type IconName } from './Icon';

interface EmptyStateProps {
  icon?: IconName;
  title: string;
  description?: string;
  action?: ReactNode;
  secondaryAction?: ReactNode;
  className?: string;
  compact?: boolean;
}

export function EmptyState({
  icon = 'sparkles',
  title,
  description,
  action,
  secondaryAction,
  className,
  compact = false,
}: EmptyStateProps) {
  return (
    <div className={`empty-state${compact ? ' empty-state--compact' : ''}${className ? ` ${className}` : ''}`}>
      <span className="empty-state__icon" aria-hidden="true">
        <Icon name={icon} size={compact ? 24 : 30} />
      </span>
      <h2 className="empty-state__title">{title}</h2>
      {description ? <p className="empty-state__text">{description}</p> : null}
      {action || secondaryAction ? (
        <div className="empty-state__actions">
          {action}
          {secondaryAction}
        </div>
      ) : null}
    </div>
  );
}
