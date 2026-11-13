import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  adminApi,
  adminErrorMessage,
  type AdminJob,
  type AdminServer,
} from '../../api/admin';
import { EmptyState } from '../../components/EmptyState';
import { ErrorState } from '../../components/ErrorState';
import { Icon } from '../../components/Icon';
import { DancingSpinner } from '../../components/DancingLoader';
import { Modal } from '../../components/Modal';
import { Skeleton } from '../../components/Skeleton';
import { formatDateTime } from '../../lib/format';

interface DeployPanelProps {
  jobs: AdminJob[];
  loading: boolean;
  error: unknown;
  servers: AdminServer[];
  active: boolean;
  onRetry: () => void;
}

const STATUS_LABELS: Record<string, string> = {
  queued: 'В очереди',
  running: 'Выполняется',
  done: 'Готово',
  failed: 'Ошибка',
};

function requestedServices(job: AdminJob): string {
  const services = job.requested?.services;
  if (!Array.isArray(services)) return '—';
  return services
    .map((item) => {
      if (typeof item === 'object' && item !== null && 'code' in item) {
        return String((item as { code: unknown }).code);
      }
      return String(item);
    })
    .join(', ');
}

export function DeployPanel({ jobs, loading, error, servers, active, onRetry }: DeployPanelProps) {
  const [jobId, setJobId] = useState<string | null>(null);
  const jobQuery = useQuery({
    queryKey: ['admin', 'job', jobId ?? 'none'],
    queryFn: ({ signal }) => adminApi.getJob(jobId ?? '', signal),
    enabled: Boolean(jobId) && active,
    retry: 1,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === 'queued' || status === 'running' ? 2000 : false;
    },
  });
  const job = jobQuery.data;
  const serverName = (serverId: string) =>
    servers.find((server) => server.id === serverId)?.name ?? serverId.slice(0, 8);

  return (
    <div className="admin-panel-stack">
      <section className="admin-panel" aria-labelledby="admin-deploy-title">
        <div className="admin-panel__head">
          <div>
            <h2 id="admin-deploy-title">Задачи деплоя</h2>
            <p>
              Очередь control-сервиса. Развёртывание и rollback запускаются из
              inventory или серверной консоли; здесь виден журнал каждой задачи.
            </p>
          </div>
          <button type="button" className="btn btn--outline btn--sm" onClick={onRetry} disabled={loading}>
            {loading ? <DancingSpinner size={15} /> : <Icon name="refresh" size={15} />}
            Обновить
          </button>
        </div>

        {loading ? (
          <Skeleton height="180px" />
        ) : error ? (
          <ErrorState
            title="Задачи недоступны"
            message="Не удалось получить список deployment jobs."
            onRetry={onRetry}
          />
        ) : jobs.length === 0 ? (
          <EmptyState
            compact
            icon="download"
            title="Задач пока нет"
            description="Запустите развёртывание из карточки сервера или через консоль."
          />
        ) : (
          <div className="admin-table-wrap">
            <table className="admin-table admin-jobs-table">
              <thead>
                <tr>
                  <th>Статус</th>
                  <th>Сервер</th>
                  <th>Сервисы</th>
                  <th>Создана</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {jobs.map((item) => (
                  <tr key={item.id}>
                    <td>
                      <span className={`admin-status admin-status--${item.status}`}>
                        <span
                          className={`admin-health-dot ${
                            item.status === 'failed'
                              ? 'is-bad'
                              : item.status === 'done'
                                ? 'is-ok'
                                : 'is-wait'
                          }`}
                        />
                        {STATUS_LABELS[item.status] ?? item.status}
                      </span>
                    </td>
                    <td>{serverName(item.server_id)}</td>
                    <td>
                      <code className="admin-audit-details">{requestedServices(item)}</code>
                    </td>
                    <td className="admin-table__time">{formatDateTime(item.created_at)}</td>
                    <td>
                      <button
                        type="button"
                        className="btn btn--ghost btn--sm"
                        onClick={() => setJobId(item.id)}
                      >
                        <Icon name="terminal" size={14} />
                        Журнал
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="admin-panel" aria-labelledby="admin-supervisor-title">
        <div className="admin-panel__head">
          <div>
            <h2 id="admin-supervisor-title">AI supervisor</h2>
            <p>
              Слот для отчёта supervisor из ветки деплоя. Пока показывает
              последний журнал и предупреждения control-сервиса.
            </p>
          </div>
          <span className="badge">скоро</span>
        </div>
        <p className="admin-overview-empty">
          Отчёт появится после подключения supervisor. Журнал задачи уже доступен
          в таблице выше.
        </p>
      </section>

      <Modal
        open={Boolean(jobId)}
        onClose={() => setJobId(null)}
        title="Журнал задачи"
        description={job ? `${serverName(job.server_id)} · ${job.id.slice(0, 8)}` : undefined}
        size="lg"
        variant="sheet"
        footer={
          <button type="button" className="btn btn--primary" onClick={() => setJobId(null)}>
            Закрыть
          </button>
        }
      >
        {jobQuery.isLoading ? (
          <Skeleton height="200px" />
        ) : jobQuery.isError ? (
          <ErrorState
            title="Журнал недоступен"
            message={adminErrorMessage(jobQuery.error, 'Не удалось получить задачу.')}
            onRetry={() => void jobQuery.refetch()}
          />
        ) : job ? (
          <div className="admin-deploy">
            <div className="admin-deploy__status">
              <span className={`admin-status admin-status--${job.status}`}>
                <span
                  className={`admin-health-dot ${
                    job.status === 'failed' ? 'is-bad' : job.status === 'done' ? 'is-ok' : 'is-wait'
                  }`}
                />
                {STATUS_LABELS[job.status] ?? job.status}
              </span>
              <span className="field__hint">
                {job.updated_at ? `обновлено ${formatDateTime(job.updated_at)}` : '—'}
              </span>
            </div>
            {job.error ? (
              <div className="form-alert" role="alert">
                <Icon name="alert" size={17} />
                <span>{job.error}</span>
              </div>
            ) : null}
            <div className="admin-terminal" aria-label="Лог задачи" aria-live="polite">
              <pre>{job.log || 'Журнал пуст.'}</pre>
            </div>
          </div>
        ) : null}
      </Modal>
    </div>
  );
}
