import { useQuery } from '@tanstack/react-query';
import { adminApi, adminErrorMessage } from '../../api/admin';
import { ErrorState } from '../ErrorState';
import { Icon } from '../Icon';
import { Skeleton } from '../Skeleton';
import { formatDateTime, formatInt } from '../../lib/format';

const GROUP_LABELS: Record<string, string> = {
  home: 'Главная',
  catalogue: 'Каталог',
  manga: 'Тайтлы',
  collection: 'Подборки',
  sources: 'Источники',
  legal: 'Правовые',
  profile: 'Публичные профили',
  other: 'Прочее',
};

function shortDay(day: string): string {
  const parsed = new Date(`${day}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return day;
  return new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    timeZone: 'UTC',
  }).format(parsed);
}

export function TrafficPanel() {
  const query = useQuery({
    queryKey: ['admin', 'traffic'],
    queryFn: ({ signal }) => adminApi.getTraffic(signal),
    refetchInterval: 60_000,
    staleTime: 30_000,
    retry: 1,
  });

  const data = query.data;
  const goal = data?.weekly_goal ?? 100;
  const week = data?.unique_visitors_7d ?? 0;
  const progress = Math.max(0, Math.min(100, data?.progress_percent ?? 0));
  const recentDays = (data?.daily ?? []).slice(-14);
  const maxDay = Math.max(1, ...recentDays.map((item) => item.unique_visitors));
  const groups = (data?.path_groups ?? []).slice(0, 5);

  return (
    <section className="admin-panel admin-traffic-panel" aria-labelledby="admin-traffic-title">
      <div className="admin-panel__head">
        <div>
          <h2 id="admin-traffic-title">Трафик</h2>
          <p>
            Уникальные посетители за 7 и 30 дней по обезличенным визитам без IP и
            user-agent. Цель для повторной модерации РСЯ — {formatInt(goal)} в неделю.
          </p>
        </div>
        <button
          type="button"
          className="btn btn--outline btn--sm"
          onClick={() => void query.refetch()}
          disabled={query.isFetching}
        >
          <Icon name="refresh" size={15} />
          {query.isFetching ? 'Обновляем…' : 'Обновить'}
        </button>
      </div>

      {query.isLoading ? (
        <div className="admin-stats" aria-hidden="true">
          <Skeleton height="110px" style={{ borderRadius: 12 }} />
          <Skeleton height="110px" style={{ borderRadius: 12 }} />
          <Skeleton height="110px" style={{ borderRadius: 12 }} />
          <Skeleton height="110px" style={{ borderRadius: 12 }} />
        </div>
      ) : query.isError ? (
        <ErrorState
          title="Статистика трафика недоступна"
          message={adminErrorMessage(query.error, 'Не удалось загрузить счётчик посетителей.')}
          onRetry={() => void query.refetch()}
        />
      ) : !data ? (
        <p className="admin-crawler-empty">Данных о визитах пока нет.</p>
      ) : (
        <>
          <div className="admin-stats">
            <div className="admin-stat">
              <span>Уникальных за 7 дней</span>
              <strong>{formatInt(week)}</strong>
              <small>из {formatInt(goal)} для цели недели</small>
            </div>
            <div className="admin-stat">
              <span>Уникальных за 30 дней</span>
              <strong>{formatInt(data.unique_visitors_30d)}</strong>
              <small>скользящее окно, UTC</small>
            </div>
            <div className="admin-stat">
              <span>Сегодня</span>
              <strong>{formatInt(data.unique_visitors_today)}</strong>
              <small>уникальных посетителей</small>
            </div>
            <div className="admin-stat">
              <span>Последний визит</span>
              <strong className="admin-traffic-last">
                {data.last_visit_at ? formatDateTime(data.last_visit_at) : '—'}
              </strong>
              <small>хранение {formatInt(data.retention_days)} дней</small>
            </div>
          </div>

          <div className="admin-traffic-goal">
            <div className="admin-traffic-goal__head">
              <span>Прогресс к 100 уникальных в неделю</span>
              <strong>{progress.toFixed(1).replace('.', ',')}%</strong>
            </div>
            <div
              className="admin-crawler-progress__track"
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={progress}
              aria-label="Прогресс к 100 уникальных посетителей в неделю"
            >
              <span style={{ width: `${progress}%` }} />
            </div>
          </div>

          <div className="admin-traffic-grid">
            <div>
              <h3 className="admin-traffic-subtitle">Последние 14 дней</h3>
              <div className="admin-traffic-days" aria-label="Уникальные посетители по дням">
                {recentDays.map((item) => (
                  <div
                    className="admin-traffic-day"
                    key={item.day}
                    title={`${shortDay(item.day)}: ${formatInt(item.unique_visitors)}`}
                  >
                    <span
                      className="admin-traffic-day__bar"
                      style={{
                        height: `${Math.max(
                          item.unique_visitors > 0 ? 8 : 2,
                          Math.round((item.unique_visitors / maxDay) * 100),
                        )}%`,
                      }}
                    />
                    <small>{shortDay(item.day)}</small>
                  </div>
                ))}
              </div>
            </div>
            <div>
              <h3 className="admin-traffic-subtitle">Разделы за 7 дней</h3>
              {groups.length === 0 ? (
                <p className="admin-crawler-empty">Пока нет визитов.</p>
              ) : (
                <ul className="admin-traffic-groups">
                  {groups.map((item) => (
                    <li key={item.path_group}>
                      <span>{GROUP_LABELS[item.path_group] ?? item.path_group}</span>
                      <strong>{formatInt(item.unique_visitors)}</strong>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </>
      )}
    </section>
  );
}
