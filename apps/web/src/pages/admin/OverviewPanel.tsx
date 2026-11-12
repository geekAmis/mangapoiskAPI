import type {
  AdminAuditEntry,
  AdminCatalogueHealth,
  AdminJob,
  AdminServer,
} from '../../api/admin';
import { ADMIN_SERVICES } from '../../api/admin';
import { Icon } from '../../components/Icon';
import { Skeleton } from '../../components/Skeleton';
import { formatDateTime, formatInt } from '../../lib/format';
import type { AdminTabId } from './tabs';

interface OverviewPanelProps {
  servers: AdminServer[];
  serversLoading: boolean;
  serversError: boolean;
  jobs: AdminJob[];
  jobsLoading: boolean;
  audit: AdminAuditEntry[];
  auditLoading: boolean;
  catalogue: AdminCatalogueHealth | undefined;
  onOpenTab: (tab: AdminTabId) => void;
  onOpenConsole: (serverId: string) => void;
}

const JOB_LABELS: Record<string, string> = {
  queued: 'В очереди',
  running: 'Выполняется',
  done: 'Готово',
  failed: 'Ошибка',
};

function serviceLabel(code: string): string {
  return ADMIN_SERVICES.find((service) => service.code === code)?.label ?? code;
}

export function OverviewPanel({
  servers,
  serversLoading,
  serversError,
  jobs,
  jobsLoading,
  audit,
  auditLoading,
  catalogue,
  onOpenTab,
  onOpenConsole,
}: OverviewPanelProps) {
  const httpServices = servers.flatMap((server) =>
    server.services.filter((service) => service.code !== 'scheduler'),
  );
  const healthyServices = httpServices.filter((service) => service.healthy).length;
  const activeJobs = jobs.filter((job) => job.status === 'queued' || job.status === 'running');
  const unhealthy = servers.flatMap((server) =>
    server.services
      .filter((service) => service.code !== 'scheduler' && !service.healthy)
      .map((service) => ({ server, service })),
  );
  const pendingEnrichment = catalogue?.enrichment.pending ?? 0;

  return (
    <div className="admin-panel-stack">
      <section className="admin-panel admin-overview-hero" aria-labelledby="admin-overview-title">
        <div className="admin-panel__head">
          <div>
            <span className="admin-kicker">Operations</span>
            <h2 id="admin-overview-title">Обзор контура</h2>
            <p>
              Сводка здоровья сервисов, активных задач и последних действий. Данные
              подгружаются только для открытых вкладок.
            </p>
          </div>
          <button type="button" className="btn btn--outline" onClick={() => onOpenTab('servers')}>
            <Icon name="server" size={16} />
            К серверам
          </button>
        </div>

        <div className="admin-stats admin-stats--overview">
          <button type="button" className="admin-stat admin-stat--link" onClick={() => onOpenTab('servers')}>
            <span>Серверы</span>
            <strong>{serversLoading ? '—' : formatInt(servers.length)}</strong>
            <small>{formatInt(servers.filter((server) => server.is_fallback).length)} в резерве</small>
          </button>
          <button type="button" className="admin-stat admin-stat--link" onClick={() => onOpenTab('servers')}>
            <span>Здоровые сервисы</span>
            <strong>
              {serversLoading ? '—' : formatInt(healthyServices)}
              <small className="admin-stat__fraction"> / {formatInt(httpServices.length)}</small>
            </strong>
            <small>HTTP-сервисы по inventory</small>
          </button>
          <button type="button" className="admin-stat admin-stat--link" onClick={() => onOpenTab('deploy')}>
            <span>Активные задачи</span>
            <strong>{jobsLoading ? '—' : formatInt(activeJobs.length)}</strong>
            <small>deploy / rollback в работе</small>
          </button>
          <button type="button" className="admin-stat admin-stat--link" onClick={() => onOpenTab('crawler')}>
            <span>Ждут обогащения</span>
            <strong>{catalogue ? formatInt(pendingEnrichment) : '—'}</strong>
            <small>{catalogue ? 'по данным каталога' : 'откроется на вкладке каталога'}</small>
          </button>
        </div>

        {serversError ? (
          <div className="admin-overview-warning" role="alert">
            <Icon name="alert" size={16} />
            Не удалось загрузить inventory серверов. Проверьте control-сервис.
          </div>
        ) : null}
      </section>

      <div className="admin-overview-grid">
        <section className="admin-panel" aria-labelledby="admin-overview-alerts">
          <div className="admin-panel__head">
            <div>
              <h2 id="admin-overview-alerts">Алерты</h2>
              <p>Сервисы, которые не отвечают на health-check.</p>
            </div>
            <span className={`badge ${unhealthy.length ? 'badge--danger' : 'badge--success'}`}>
              {unhealthy.length ? `${unhealthy.length} проблем` : 'всё здорово'}
            </span>
          </div>
          {serversLoading ? (
            <Skeleton height="100px" />
          ) : unhealthy.length === 0 ? (
            <p className="admin-overview-ok">
              <Icon name="check" size={16} />
              Все HTTP-сервисы отвечают. Scheduler проверяется отдельно.
            </p>
          ) : (
            <ul className="admin-overview-alert-list">
              {unhealthy.slice(0, 8).map(({ server, service }) => (
                <li key={`${server.id}-${service.code}`}>
                  <span className="admin-health-dot is-bad" />
                  <div>
                    <strong>{serviceLabel(service.code)}</strong>
                    <span>
                      {server.name} · :{service.port}
                      {service.last_error ? ` · ${service.last_error}` : ''}
                    </span>
                  </div>
                  <button
                    type="button"
                    className="btn btn--ghost btn--sm"
                    onClick={() => onOpenConsole(server.id)}
                  >
                    <Icon name="terminal" size={14} />
                    Консоль
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="admin-panel" aria-labelledby="admin-overview-jobs">
          <div className="admin-panel__head">
            <div>
              <h2 id="admin-overview-jobs">Задачи деплоя</h2>
              <p>Очередь и последние завершённые задачи.</p>
            </div>
            <button type="button" className="btn btn--ghost btn--sm" onClick={() => onOpenTab('deploy')}>
              Все задачи
            </button>
          </div>
          {jobsLoading ? (
            <Skeleton height="100px" />
          ) : jobs.length === 0 ? (
            <p className="admin-overview-empty">Задач пока нет.</p>
          ) : (
            <ul className="admin-overview-job-list">
              {jobs.slice(0, 5).map((job) => {
                const server = servers.find((item) => item.id === job.server_id);
                return (
                  <li key={job.id}>
                    <span className={`admin-status admin-status--${job.status}`}>
                      <span
                        className={`admin-health-dot ${
                          job.status === 'failed'
                            ? 'is-bad'
                            : job.status === 'done'
                              ? 'is-ok'
                              : 'is-wait'
                        }`}
                      />
                      {JOB_LABELS[job.status] ?? job.status}
                    </span>
                    <div>
                      <strong>{server?.name ?? job.server_id.slice(0, 8)}</strong>
                      <span>{job.created_at ? formatDateTime(job.created_at) : '—'}</span>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      </div>

      <section className="admin-panel" aria-labelledby="admin-overview-audit">
        <div className="admin-panel__head">
          <div>
            <h2 id="admin-overview-audit">Последние события</h2>
            <p>Аудит control-сервиса: серверы, деплой, консоль и реестр.</p>
          </div>
          <button type="button" className="btn btn--ghost btn--sm" onClick={() => onOpenTab('audit')}>
            Открыть аудит
          </button>
        </div>
        {auditLoading ? (
          <Skeleton height="120px" />
        ) : audit.length === 0 ? (
          <p className="admin-overview-empty">Событий пока нет.</p>
        ) : (
          <ul className="admin-overview-audit">
            {audit.slice(0, 8).map((entry) => (
              <li key={entry.id}>
                <code>{entry.action}</code>
                <span>{formatDateTime(entry.created_at)}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
