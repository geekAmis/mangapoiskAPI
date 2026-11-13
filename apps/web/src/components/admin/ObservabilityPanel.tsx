import { useQuery } from '@tanstack/react-query';
import { adminApi, adminErrorMessage, type AdminObservabilityAlert } from '../../api/admin';
import { ErrorState } from '../ErrorState';
import { Icon } from '../Icon';
import { Skeleton } from '../Skeleton';
import { formatBytes, formatDateTime, formatDuration, formatInt } from '../../lib/format';

const SEVERITY_LABELS: Record<string, string> = {
  critical: 'Критично',
  high: 'Высокий',
  warning: 'Внимание',
  info: 'Инфо',
};

function severityClass(severity: string): string {
  if (severity === 'critical') return 'is-critical';
  if (severity === 'high') return 'is-high';
  if (severity === 'warning') return 'is-warning';
  return 'is-info';
}

function AlertRow({ alert }: { alert: AdminObservabilityAlert }) {
  return (
    <li className={`admin-observability-alert ${severityClass(alert.severity)}`}>
      <span className="admin-observability-alert__severity">
        {SEVERITY_LABELS[alert.severity] ?? alert.severity}
      </span>
      <div>
        <strong>{alert.summary}</strong>
        {alert.details ? <p>{alert.details}</p> : null}
      </div>
    </li>
  );
}

function percent(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  return `${(value * 100).toFixed(digits).replace('.', ',')}%`;
}

export function ObservabilityPanel() {
  const query = useQuery({
    queryKey: ['admin', 'observability'],
    queryFn: ({ signal }) => adminApi.getObservability(signal),
    refetchInterval: 15_000,
    staleTime: 5_000,
    retry: 1,
  });

  const data = query.data;
  const five = data?.http.windows['5m'];
  const hour = data?.http.windows['60m'];
  const backupAge = data?.backup.age_seconds;
  const services = Object.entries(data?.services ?? {});
  const alerts = data?.alerts ?? [];
  const lockServices = Object.entries(data?.db.by_service ?? {}).filter(
    ([, stats]) => stats.errors_5m > 0,
  );
  const media = data?.media;

  return (
    <section className="admin-panel admin-observability-panel" aria-labelledby="admin-observability-title">
      <div className="admin-panel__head">
        <div>
          <h2 id="admin-observability-title">HTTP, SQLite и алерты</h2>
          <p>
            p50/p95/p99, доля 5xx, блокировки SQLite, возраст бэкапа и активные
            предупреждения. Обновляется каждые 15 секунд.
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
        <div className="admin-crawler-grid" aria-hidden="true">
          <Skeleton height="150px" style={{ borderRadius: 12 }} />
          <Skeleton height="150px" style={{ borderRadius: 12 }} />
          <Skeleton height="150px" style={{ borderRadius: 12 }} />
        </div>
      ) : query.isError ? (
        <ErrorState
          title="Метрики недоступны"
          message={adminErrorMessage(query.error, 'Не удалось загрузить HTTP-метрики и алерты.')}
          onRetry={() => void query.refetch()}
        />
      ) : !data ? (
        <p className="admin-crawler-empty">Нет данных наблюдаемости.</p>
      ) : (
        <>
          <div className="admin-stats">
            <div className="admin-stat">
              <span>5xx за 5 минут</span>
              <strong>{percent(five?.error_rate)}</strong>
              <small>
                {formatInt(five?.errors_5xx)} из {formatInt(five?.requests)} запросов
              </small>
            </div>
            <div className="admin-stat">
              <span>p95 latency</span>
              <strong>{five ? `${Math.round(five.p95_ms)} мс` : '—'}</strong>
              <small>
                p50 {five ? `${Math.round(five.p50_ms)} мс` : '—'} · p99{' '}
                {five ? `${Math.round(five.p99_ms)} мс` : '—'}
              </small>
            </div>
            <div className="admin-stat">
              <span>SQLite locks</span>
              <strong>{formatInt(data.db.errors_5m)}</strong>
              <small>
                за 5 мин · retries {formatInt(data.db.retries_total)} · exhausted{' '}
                {formatInt(data.db.exhausted_total)}
              </small>
              {lockServices.length > 0 ? (
                <small>
                  по сервисам:{' '}
                  {lockServices
                    .map(([name, stats]) => `${name} ${formatInt(stats.errors_5m)}`)
                    .join(' · ')}
                </small>
              ) : null}
            </div>
            <div className="admin-stat">
              <span>Бэкап</span>
              <strong>
                {data.backup.configured
                  ? backupAge === null
                    ? 'нет'
                    : formatDuration(backupAge)
                  : 'не настроен'}
              </strong>
              <small>
                {data.backup.last_success_at
                  ? `успех ${formatDateTime(data.backup.last_success_at)}`
                  : 'успешных запусков нет'}
              </small>
            </div>
          </div>

          <div className="admin-observability-grid">
            <div className="admin-observability-card">
              <h3>Запросы за час</h3>
              <strong>{formatInt(hour?.requests)}</strong>
              <span>
                5xx {percent(hour?.error_rate)} · p95{' '}
                {hour ? `${Math.round(hour.p95_ms)} мс` : '—'}
              </span>
            </div>
            <div className="admin-observability-card">
              <h3>Сервисы</h3>
              <div className="admin-observability-services">
                {services.length === 0 ? (
                  <span className="admin-observability-muted">Нет health-данных</span>
                ) : (
                  services.map(([name, healthy]) => (
                    <span
                      key={name}
                      className={`admin-observability-service ${healthy ? 'is-ok' : 'is-bad'}`}
                      title={healthy ? 'health 200' : 'health недоступен'}
                    >
                      <span aria-hidden="true" />
                      {name}
                    </span>
                  ))
                )}
              </div>
            </div>
            <div className="admin-observability-card">
              <h3>Хранилище</h3>
              <strong>{formatBytes(media?.archive_done_bytes)}</strong>
              <span>
                архив{' '}
                {media?.archive_usage_percent != null
                  ? `${media.archive_usage_percent.toFixed(1).replace('.', ',')}%`
                  : '—'}{' '}
                · кэш {formatBytes(media?.image_cache_bytes)}
              </span>
            </div>
            <div className="admin-observability-card">
              <h3>Диск</h3>
              <strong>
                {data.disk.used_percent === null || data.disk.used_percent === undefined
                  ? '—'
                  : `${data.disk.used_percent.toFixed(0)}%`}
              </strong>
              <span>{data.disk.path ?? '/'} · свободно {formatBytes(data.disk.free_bytes)}</span>
            </div>
          </div>

          {alerts.length > 0 ? (
            <div className="admin-observability-alerts" role="status">
              <div className="admin-observability-alerts__title">
                <Icon name="alert" size={16} />
                <strong>Активные алерты ({alerts.length})</strong>
              </div>
              <ul>
                {alerts.map((alert) => (
                  <AlertRow key={alert.key} alert={alert} />
                ))}
              </ul>
            </div>
          ) : (
            <div className="admin-crawler-clear" role="status">
              <Icon name="check" size={16} />
              <span>Активных алертов нет.</span>
            </div>
          )}

          <p className="admin-crawler-updated">
            Снимок: {formatDateTime(data.generated_at)} · пороги: 5xx &gt; 2%, p95 &gt; 2 с,
            locks &gt; 5/мин, бэкап &gt; 26 ч.
          </p>
        </>
      )}
    </section>
  );
}
