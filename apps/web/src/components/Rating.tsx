import { formatInt, formatRating } from '../lib/format';
import { Icon } from './Icon';

interface RatingProps {
  value: number | null | undefined;
  count?: number | null;
  compact?: boolean;
}

export function Rating({ value, count, compact = false }: RatingProps) {
  if (value === null || value === undefined) {
    return (
      <span className="rating rating--empty" title="Рейтинг пока не выставлен">
        <Icon name="star" size={compact ? 14 : 16} />
        <span>—</span>
      </span>
    );
  }

  const label = `Рейтинг ${formatRating(value)} из 10${
    count ? `, ${formatInt(count)} оценок` : ''
  }`;

  return (
    <span className={`rating${compact ? ' rating--compact' : ''}`} aria-label={label} title={label}>
      <Icon name="star" size={compact ? 14 : 16} />
      <span className="rating__value">{formatRating(value)}</span>
      {!compact && count ? <span className="rating__count">{formatInt(count)}</span> : null}
    </span>
  );
}
