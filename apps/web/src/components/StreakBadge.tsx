import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import { pluralRu } from '../lib/format';
import { useLocalStreak } from '../lib/useReading';
import { useAuthStore } from '../stores/auth';
import { Icon } from './Icon';

function browserTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch {
    return 'UTC';
  }
}

function daysLabel(value: number): string {
  return `${value} ${pluralRu(value, 'день', 'дня', 'дней')}`;
}

export function StreakBadge({ variant = 'pill' }: { variant?: 'pill' | 'card' }) {
  const user = useAuthStore((state) => state.user);
  const local = useLocalStreak();
  const timezone = browserTimezone();
  const query = useQuery({
    queryKey: ['streak', user?.id ?? 'anon', timezone],
    queryFn: ({ signal }) => api.getStreak(timezone, signal),
    enabled: Boolean(user),
    staleTime: 5 * 60_000,
  });
  const streak = query.data
    ? {
        current: query.data.current,
        longest: query.data.longest,
        readToday: query.data.read_today,
        days: query.data.days,
      }
    : local;

  if (variant === 'pill') {
    return (
      <span
        className={`streak-pill${streak.readToday ? ' is-today' : ''}`}
        title={
          streak.current > 0
            ? `Серия чтения: ${daysLabel(streak.current)}. Рекорд: ${daysLabel(streak.longest)}.`
            : 'Серия начнётся с первой прочитанной главы.'
        }
      >
        <Icon name="sparkles" size={14} />
        {streak.current > 0 ? (
          <>
            <strong>{daysLabel(streak.current)}</strong>
            <span>подряд</span>
          </>
        ) : (
          <span>Начните серию чтения</span>
        )}
      </span>
    );
  }

  const recent = new Set(streak.days.slice(-14));
  const cells = Array.from({ length: 14 }, (_, index) => {
    const date = new Date();
    date.setDate(date.getDate() - (13 - index));
    const key = new Intl.DateTimeFormat('en-US', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    })
      .formatToParts(date)
      .reduce<Record<string, string>>((acc, part) => {
        if (part.type !== 'literal') acc[part.type] = part.value;
        return acc;
      }, {});
    const dayKey = `${key.year}-${key.month}-${key.day}`;
    return { key: dayKey, active: recent.has(dayKey) };
  });

  return (
    <section className="streak-card" aria-label="Серия чтения">
      <div className="streak-card__head">
        <span className="streak-card__icon" aria-hidden="true">
          <Icon name="sparkles" size={18} />
        </span>
        <div>
          <strong>
            {streak.current > 0
              ? `${daysLabel(streak.current)} подряд`
              : 'Серия начнётся с первой главы'}
          </strong>
          <span>
            {streak.readToday
              ? 'Сегодняшнее чтение уже отмечено. Без давления — просто возвращайтесь, когда хочется.'
              : streak.current > 0
                ? 'Серия сохранится до конца дня. Можно продолжить позже.'
                : 'Читайте в своём темпе. Без штрафов и напоминаний.'}
          </span>
        </div>
        {streak.longest > 0 ? (
          <span className="streak-card__record">Рекорд: {daysLabel(streak.longest)}</span>
        ) : null}
      </div>
      <div className="streak-card__days" aria-hidden="true">
        {cells.map((cell) => (
          <span
            key={cell.key}
            className={`streak-card__day${cell.active ? ' is-active' : ''}`}
            title={cell.key}
          />
        ))}
      </div>
    </section>
  );
}
