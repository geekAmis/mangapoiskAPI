import { useMemo } from 'react';
import {
  ADMIN_SERVICES,
  healthErrorText,
  type AdminRegistry,
  type AdminRegistryEndpoint,
  type AdminServer,
} from '../../api/admin';
import { EmptyState } from '../../components/EmptyState';
import { ErrorState } from '../../components/ErrorState';
import { Icon } from '../../components/Icon';
import { DancingSpinner } from '../../components/DancingLoader';
import { Skeleton } from '../../components/Skeleton';
import { AdminServerCard } from '../../components/admin/AdminServerCard';
import { formatDateTime, formatInt } from '../../lib/format';

interface ServersPanelProps {
  servers: AdminServer[];
  lastDeployByServer: Map<string, string>;
  serversLoading: boolean;
  serversError: unknown;
  serversFetching: boolean;
  registry: AdminRegistry | undefined;
  registryLoading: boolean;
  registryError: unknown;
  updatePendingId: string | null;
  healthPendingId: string | null;
  syncPending: boolean;
  failoverPending: boolean;
  onRefresh: () => void;
  onSync: () => void;
  onFailover: () => void;
  onAdd: () => void;
  onEdit: (server: AdminServer) => void;
  onDeploy: (server: AdminServer) => void;
  onPromote: (server: AdminServer) => void;
  onDelete: (server: AdminServer) => void;
  onToggleEnabled: (server: AdminServer) => void;
  onToggleFallback: (server: AdminServer) => void;
  onHealth: (server: AdminServer) => void;
  onConsole: (server: AdminServer) => void;
  onRetryServers: () => void;
  onRetryRegistry: () => void;
}

const SERVICE_LABELS: Record<string, string> = Object.fromEntries(
  ADMIN_SERVICES.map((service) => [service.code, service.label]),
);

function RegistryRow({ endpoint, active }: { endpoint: AdminRegistryEndpoint; active: boolean }) {
  return (
    <div className={`admin-registry-row${active ? ' is-active' : ''}`}>
      <span className={`admin-health-dot ${endpoint.healthy ? 'is-ok' : 'is-bad'}`} />
      <div className="admin-registry-row__body">
        <div className="admin-registry-row__title">
          <strong>{endpoint.server_name}</strong>
          {active ? <span className="admin-active-badge">активный</span> : null}
          {endpoint.is_fallback ? <span className="badge">fallback</span> : null}
          {!endpoint.healthy ? <span className="badge badge--danger">недоступен</span> : null}
        </div>
        <code>{endpoint.url}</code>
        {endpoint.last_error ? (
          <span className="admin-registry-row__error">{healthErrorText(endpoint.last_error)}</span>
        ) : null}
      </div>
      <span className="admin-registry-row__checked">
        {endpoint.checked_at ? formatDateTime(endpoint.checked_at) : 'не проверялся'}
      </span>
    </div>
  );
}

export function ServersPanel({
  servers,
  lastDeployByServer,
  serversLoading,
  serversError,
  serversFetching,
  registry,
  registryLoading,
  registryError,
  updatePendingId,
  healthPendingId,
  syncPending,
  failoverPending,
  onRefresh,
  onSync,
  onFailover,
  onAdd,
  onEdit,
  onDeploy,
  onPromote,
  onDelete,
  onToggleEnabled,
  onToggleFallback,
  onHealth,
  onConsole,
  onRetryServers,
  onRetryRegistry,
}: ServersPanelProps) {
  const stats = useMemo(() => {
    const httpServices = servers.flatMap((server) =>
      server.services.filter((service) => service.code !== 'scheduler'),
    );
    return {
      servers: servers.length,
      healthyServices: httpServices.filter((service) => service.healthy).length,
      totalServices: httpServices.length,
      fallback: servers.filter((server) => server.is_fallback).length,
    };
  }, [servers]);

  const registryGroups = useMemo(() => {
    if (!registry) return [];
    const codes = Object.keys(registry.services);
    const ordered = [
      ...ADMIN_SERVICES.map((service) => service.code).filter((code) => codes.includes(code)),
      ...codes.filter((code) => !ADMIN_SERVICES.some((service) => service.code === code)),
    ];
    return ordered
      .map((code) => ({
        code,
        label: SERVICE_LABELS[code] ?? code,
        endpoints: [...(registry.services[code] ?? [])].sort(
          (a, b) =>
            Number(a.is_fallback) - Number(b.is_fallback) ||
            Number(b.healthy) - Number(a.healthy) ||
            (a.priority ?? 100) - (b.priority ?? 100),
        ),
      }))
      .filter((group) => group.endpoints.length > 0);
  }, [registry]);

  return (
    <div className="admin-panel-stack">
      <section className="admin-panel" aria-labelledby="admin-servers-title">
        <div className="admin-panel__head">
          <div>
            <h2 id="admin-servers-title">Инвентарь серверов</h2>
            <p>
              Health-check, развёртывание и SSH-доступ. «Консоль» открывает
              ограниченный терминал выбранного узла.
            </p>
          </div>
          <div className="admin-actions">
            <button type="button" className="btn btn--outline" onClick={onSync} disabled={syncPending}>
              {syncPending ? <DancingSpinner size={16} /> : <Icon name="refresh" size={16} />}
              Синхронизировать маршруты
            </button>
            <button type="button" className="btn btn--danger-ghost" onClick={onFailover} disabled={failoverPending}>
              <Icon name="alert" size={16} />
              Failover
            </button>
            <button
              type="button"
              className="btn btn--ghost btn--icon"
              onClick={onRefresh}
              disabled={serversFetching}
              aria-label="Обновить данные"
              title="Обновить данные"
            >
              {serversFetching ? <DancingSpinner size={18} /> : <Icon name="refresh" size={18} />}
            </button>
            <button type="button" className="btn btn--primary" onClick={onAdd}>
              <Icon name="plus" size={16} />
              Добавить сервер
            </button>
          </div>
        </div>

        <div className="admin-stats">
          <div className="admin-stat">
            <span>Серверы</span>
            <strong>{formatInt(stats.servers)}</strong>
            <small>{formatInt(stats.fallback)} в резерве</small>
          </div>
          <div className="admin-stat">
            <span>Здоровые сервисы</span>
            <strong>
              {formatInt(stats.healthyServices)}
              <small className="admin-stat__fraction"> / {formatInt(stats.totalServices)}</small>
            </strong>
            <small>HTTP-сервисы по inventory</small>
          </div>
          <div className="admin-stat">
            <span>Реестр gateway</span>
            <strong>{formatInt(registryGroups.length)}</strong>
            <small>
              {formatInt(registryGroups.reduce((sum, group) => sum + group.endpoints.length, 0))} endpoint
            </small>
          </div>
        </div>

        {serversLoading ? (
          <div className="admin-server-grid" aria-hidden="true">
            {Array.from({ length: 2 }, (_, index) => (
              <Skeleton key={index} height="340px" style={{ borderRadius: 14 }} />
            ))}
          </div>
        ) : serversError ? (
          <ErrorState
            title="Не удалось загрузить серверы"
            message="Проверьте control-сервис и повторите запрос."
            onRetry={onRetryServers}
          />
        ) : servers.length === 0 ? (
          <EmptyState
            icon="server"
            title="Серверов пока нет"
            description="Добавьте первый узел, назначьте сервисы и запустите развёртывание."
            action={
              <button type="button" className="btn btn--primary" onClick={onAdd}>
                <Icon name="plus" size={16} />
                Добавить сервер
              </button>
            }
          />
        ) : (
          <div className="admin-server-grid">
            {servers.map((server) => (
              <AdminServerCard
                key={server.id}
                server={server}
                lastDeployAt={lastDeployByServer.get(server.id) ?? null}
                updatePending={updatePendingId === server.id}
                healthPending={healthPendingId === server.id}
                onEdit={onEdit}
                onDeploy={onDeploy}
                onPromote={onPromote}
                onDelete={onDelete}
                onToggleEnabled={onToggleEnabled}
                onToggleFallback={onToggleFallback}
                onHealth={onHealth}
                onConsole={onConsole}
              />
            ))}
          </div>
        )}
      </section>

      <section className="admin-panel" aria-labelledby="admin-registry-title">
        <div className="admin-panel__head">
          <div>
            <h2 id="admin-registry-title">Реестр gateway</h2>
            <p>Активный маршрут для каждого сервиса и состояние резервных endpoint.</p>
          </div>
          <button type="button" className="btn btn--outline btn--sm" onClick={onSync} disabled={syncPending}>
            {syncPending ? <DancingSpinner size={15} /> : <Icon name="refresh" size={15} />}
            Синхронизировать
          </button>
        </div>

        {registryLoading ? (
          <div className="admin-registry-grid" aria-hidden="true">
            {Array.from({ length: 4 }, (_, index) => (
              <Skeleton key={index} height="150px" style={{ borderRadius: 12 }} />
            ))}
          </div>
        ) : registryError ? (
          <ErrorState
            title="Реестр недоступен"
            message="Не удалось получить маршруты gateway."
            onRetry={onRetryRegistry}
          />
        ) : registryGroups.length === 0 ? (
          <EmptyState
            compact
            icon="link"
            title="Маршруты ещё не настроены"
            description="Добавьте серверы с сервисами и синхронизируйте реестр — gateway подхватит здоровые узлы."
          />
        ) : (
          <div className="admin-registry-grid">
            {registryGroups.map((group) => {
              const activeEndpoint = group.endpoints.find((endpoint) => endpoint.healthy);
              return (
                <div className="admin-registry-group" key={group.code}>
                  <header>
                    <div>
                      <h3>{group.label}</h3>
                      <span>{group.endpoints.length} endpoint</span>
                    </div>
                    <span className={`badge ${activeEndpoint ? 'badge--success' : 'badge--danger'}`}>
                      {activeEndpoint ? 'Есть активный' : 'Нет здоровых'}
                    </span>
                  </header>
                  <div className="admin-registry-list">
                    {group.endpoints.map((endpoint) => (
                      <RegistryRow
                        key={`${group.code}-${endpoint.server_id}`}
                        endpoint={endpoint}
                        active={activeEndpoint?.server_id === endpoint.server_id}
                      />
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>

    </div>
  );
}
