import { useEffect, useLayoutEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ADMIN_SERVICES,
  ADMIN_UNAUTHORIZED_EVENT,
  adminApi,
  adminErrorMessage,
  getAdminToken,
  healthErrorText,
  isAdminUnauthorized,
  setAdminToken,
  type AdminAuditEntry,
  type AdminRegistry,
  type AdminRegistryEndpoint,
  type AdminServer,
} from '../api/admin';
import { EmptyState } from '../components/EmptyState';
import { ErrorState, InlineError } from '../components/ErrorState';
import { Icon } from '../components/Icon';
import { DancingSpinner } from '../components/DancingLoader';
import { Modal } from '../components/Modal';
import { Skeleton } from '../components/Skeleton';
import { AdminLogin } from '../components/admin/AdminLogin';
import { AdminServerCard } from '../components/admin/AdminServerCard';
import { DeployModal } from '../components/admin/DeployModal';
import { ServerFormModal } from '../components/admin/ServerFormModal';
import { formatDateTime, formatInt } from '../lib/format';
import { useDocumentTitle } from '../lib/hooks';
import { toast } from '../stores/toast';
import '../styles/admin.css';

const SERVICE_LABELS: Record<string, string> = Object.fromEntries(
  ADMIN_SERVICES.map((service) => [service.code, service.label]),
);

const AUDIT_LABELS: Record<string, string> = {
  create_server: 'Создан сервер',
  update_server: 'Обновлён сервер',
  delete_server: 'Удалён сервер',
  deploy: 'Развёртывание',
  deploy_started: 'Запущено развёртывание',
  health_check: 'Health-check',
  registry_sync: 'Синхронизация маршрутов',
  failover: 'Failover',
  server_created: 'Создан сервер',
  server_updated: 'Обновлён сервер',
  server_deleted: 'Удалён сервер',
  'server.created': 'Создан сервер',
  'server.updated': 'Обновлён сервер',
  'server.deleted': 'Удалён сервер',
  'deployment.started': 'Запущено развёртывание',
  'deployment.finished': 'Развёртывание завершено',
  'deployment.failed': 'Ошибка развёртывания',
  'registry.synced': 'Маршруты синхронизированы',
  'registry.sync': 'Маршруты синхронизированы',
  'failover.applied': 'Failover выполнен',
  'health.checked': 'Health-check',
};

function detailsSummary(entry: AdminAuditEntry): string {
  const details = entry.details ?? {};
  const preferred = ['service', 'services', 'job_id', 'host', 'port', 'url', 'name'];
  const parts: string[] = [];
  const sensitive = /pass|secret|token/i;
  const renderValue = (key: string, value: unknown) => {
    if (value === undefined || value === null || value === '') return null;
    if (sensitive.test(key)) return `${key}: [скрыто]`;
    return `${key}: ${typeof value === 'object' ? JSON.stringify(value) : String(value)}`;
  };
  for (const key of preferred) {
    const rendered = renderValue(key, details[key]);
    if (rendered) parts.push(rendered);
  }
  if (parts.length === 0) {
    for (const [key, value] of Object.entries(details)) {
      const rendered = renderValue(key, value);
      if (!rendered) continue;
      parts.push(rendered);
      if (parts.length >= 4) break;
    }
  }
  const text = parts.join(' · ') || '—';
  return text.length > 140 ? `${text.slice(0, 139)}…` : text;
}

export default function AdminPage() {
  useDocumentTitle('Control — MangaPoisk Reborn');
  const queryClient = useQueryClient();
  const [token, setTokenState] = useState<string | null>(() => getAdminToken());
  const [formOpen, setFormOpen] = useState(false);
  const [editingServer, setEditingServer] = useState<AdminServer | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<AdminServer | null>(null);
  const [deployTarget, setDeployTarget] = useState<AdminServer | null>(null);
  const [failoverOpen, setFailoverOpen] = useState(false);

  useLayoutEffect(() => {
    const root = document.documentElement;
    root.dataset.admin = 'true';
    return () => {
      delete root.dataset.admin;
    };
  }, []);

  useEffect(() => {
    const meta = document.createElement('meta');
    meta.name = 'robots';
    meta.content = 'noindex,nofollow';
    document.head.appendChild(meta);
    return () => meta.remove();
  }, []);

  useEffect(() => {
    const onUnauthorized = (event: Event) => {
      setTokenState(null);
      queryClient.removeQueries({ queryKey: ['admin'] });
      const detail = (event as CustomEvent<string>).detail;
      if (detail) toast.error(detail);
    };
    window.addEventListener(ADMIN_UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(ADMIN_UNAUTHORIZED_EVENT, onUnauthorized);
  }, [queryClient]);

  const meQuery = useQuery({
    queryKey: ['admin', 'me'],
    queryFn: ({ signal }) => adminApi.me(signal),
    enabled: Boolean(token),
    retry: false,
  });

  const serversQuery = useQuery({
    queryKey: ['admin', 'servers'],
    queryFn: ({ signal }) => adminApi.listServers(signal),
    enabled: Boolean(token),
    retry: 1,
  });

  const registryQuery = useQuery({
    queryKey: ['admin', 'registry'],
    queryFn: ({ signal }) => adminApi.getRegistry(signal),
    enabled: Boolean(token),
    retry: 1,
  });

  const auditQuery = useQuery({
    queryKey: ['admin', 'audit'],
    queryFn: ({ signal }) => adminApi.getAudit(100, signal),
    enabled: Boolean(token),
    retry: 1,
  });

  const servers = serversQuery.data ?? [];
  const registry = registryQuery.data;
  const audit = auditQuery.data ?? [];

  const applyRegistryResult = (nextRegistry: AdminRegistry, message: string) => {
    queryClient.setQueryData(['admin', 'registry'], nextRegistry);
    void queryClient.invalidateQueries({ queryKey: ['admin', 'audit'] });
    void queryClient.invalidateQueries({ queryKey: ['admin', 'servers'] });
    toast.success(message);
  };

  const syncMutation = useMutation({
    mutationFn: () => adminApi.syncRegistry(),
    onSuccess: (result) => {
      const count = Object.keys(result.updated).length;
      applyRegistryResult(
        result.registry,
        count > 0 ? `Маршруты обновлены: ${count}` : 'Здоровых узлов для обновления не найдено',
      );
    },
    onError: (error: unknown) => toast.error(adminErrorMessage(error, 'Не удалось синхронизировать маршруты.')),
  });

  const failoverMutation = useMutation({
    mutationFn: () => adminApi.failover(),
    onSuccess: (result) => {
      const count = Object.keys(result.updated).length;
      applyRegistryResult(
        result.registry,
        count > 0 ? `Failover выполнен: ${count} сервисов переключено` : 'Нет доступных резервных узлов',
      );
      setFailoverOpen(false);
    },
    onError: (error: unknown) => {
      toast.error(adminErrorMessage(error, 'Не удалось выполнить failover.'));
      setFailoverOpen(false);
    },
  });

  const updateMutation = useMutation({
    mutationFn: (variables: { server: AdminServer; patch: { enabled?: boolean; is_fallback?: boolean } }) =>
      adminApi.updateServer(variables.server.id, variables.patch),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['admin', 'servers'] });
      void queryClient.invalidateQueries({ queryKey: ['admin', 'registry'] });
      void queryClient.invalidateQueries({ queryKey: ['admin', 'audit'] });
      toast.success('Сервер обновлён');
    },
    onError: (error: unknown) => toast.error(adminErrorMessage(error, 'Не удалось обновить сервер.')),
  });

  const deleteMutation = useMutation({
    mutationFn: (server: AdminServer) => adminApi.deleteServer(server.id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['admin', 'servers'] });
      void queryClient.invalidateQueries({ queryKey: ['admin', 'registry'] });
      void queryClient.invalidateQueries({ queryKey: ['admin', 'audit'] });
      toast.success('Сервер удалён');
      setDeleteTarget(null);
    },
    onError: (error: unknown) => toast.error(adminErrorMessage(error, 'Не удалось удалить сервер.')),
  });

  const healthMutation = useMutation({
    mutationFn: (server: AdminServer) => adminApi.getServerHealth(server.id),
    onSuccess: (health) => {
      const unhealthy = health.services.filter((service) => service.code !== 'scheduler' && !service.healthy).length;
      if (health.healthy) toast.success(`${health.name}: все сервисы здоровы`);
      else toast.error(`${health.name}: проблемных сервисов — ${unhealthy}`);
      void queryClient.invalidateQueries({ queryKey: ['admin', 'servers'] });
      void queryClient.invalidateQueries({ queryKey: ['admin', 'audit'] });
    },
    onError: (error: unknown) => toast.error(adminErrorMessage(error, 'Health-check не удался.')),
  });

  const refreshAll = () => {
    void serversQuery.refetch();
    void registryQuery.refetch();
    void auditQuery.refetch();
    void meQuery.refetch();
  };

  const logout = () => {
    setAdminToken(null);
    setTokenState(null);
    queryClient.removeQueries({ queryKey: ['admin'] });
    toast.info('Вы вышли из Control');
  };

  const stats = useMemo(() => {
    const httpServices = servers.flatMap((server) =>
      server.services.filter((service) => service.code !== 'scheduler'),
    );
    return {
      servers: servers.length,
      healthyServices: httpServices.filter((service) => service.healthy).length,
      totalServices: httpServices.length,
      fallback: servers.filter((server) => server.is_fallback).length,
      audit: audit.length,
    };
  }, [servers, audit.length]);

  const serverNames = useMemo(
    () => new Map(servers.map((server) => [server.id, server.name])),
    [servers],
  );

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
          (a, b) => Number(a.is_fallback) - Number(b.is_fallback) || Number(b.healthy) - Number(a.healthy),
        ),
      }))
      .filter((group) => group.endpoints.length > 0);
  }, [registry]);

  const refreshing = serversQuery.isFetching || registryQuery.isFetching || auditQuery.isFetching;
  const updatePendingId = updateMutation.isPending ? updateMutation.variables?.server.id : null;
  const healthPendingId = healthMutation.isPending ? healthMutation.variables?.id : null;

  if (!token) {
    return (
      <AdminLogin
        onAuthenticated={(nextToken) => {
          queryClient.removeQueries({ queryKey: ['admin'] });
          setTokenState(nextToken);
        }}
      />
    );
  }

  return (
    <div className="admin-shell">
      <header className="admin-topbar">
        <div className="admin-topbar__inner">
          <div className="admin-brand">
            <span className="admin-brand-mark" aria-hidden="true">
              <Icon name="server" size={21} />
            </span>
            <span className="admin-brand__name">
              MangaPoisk <span className="admin-brand__badge">Control</span>
            </span>
          </div>
          <div className="admin-topbar__right">
            <span className="admin-user">
              <Icon name="user" size={15} />
              {meQuery.data?.username ?? 'admin'}
            </span>
            <Link to="/" className="admin-site-link" aria-label="Открыть публичный сайт">
              <Icon name="external" size={14} />
              <span>Открыть сайт</span>
            </Link>
            <button type="button" className="btn btn--ghost btn--icon" onClick={logout} aria-label="Выйти">
              <Icon name="logout" size={18} />
            </button>
          </div>
        </div>
      </header>

      <main className="admin-main">
        <div className="admin-page-head">
          <div>
            <span className="admin-kicker">Operations</span>
            <h1>Серверы</h1>
            <p>Inventory, SSH-развёртывание, health-check и маршрутизация gateway.</p>
          </div>
          <div className="admin-actions">
            <button
              type="button"
              className="btn btn--outline"
              onClick={() => syncMutation.mutate()}
              disabled={syncMutation.isPending}
            >
              {syncMutation.isPending ? (
                <DancingSpinner size={16} />
              ) : (
                <Icon name="refresh" size={16} />
              )}
              Синхронизировать маршруты
            </button>
            <button
              type="button"
              className="btn btn--danger-ghost"
              onClick={() => setFailoverOpen(true)}
              disabled={failoverMutation.isPending}
            >
              <Icon name="alert" size={16} />
              Failover
            </button>
            <button
              type="button"
              className="btn btn--ghost btn--icon"
              onClick={refreshAll}
              disabled={refreshing}
              aria-label="Обновить данные"
              title="Обновить данные"
            >
              {refreshing ? <DancingSpinner size={18} /> : <Icon name="refresh" size={18} />}
            </button>
            <button
              type="button"
              className="btn btn--primary"
              onClick={() => {
                setEditingServer(null);
                setFormOpen(true);
              }}
            >
              <Icon name="plus" size={16} />
              Добавить сервер
            </button>
          </div>
        </div>

        {meQuery.isError && !isAdminUnauthorized(meQuery.error) ? (
          <div style={{ marginBottom: 16 }}>
            <InlineError
              message={adminErrorMessage(meQuery.error, 'Не удалось проверить сессию администратора.')}
              onRetry={() => void meQuery.refetch()}
            />
          </div>
        ) : null}

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
            <small>{formatInt(registryGroups.reduce((sum, group) => sum + group.endpoints.length, 0))} endpoint</small>
          </div>
          <div className="admin-stat">
            <span>События аудита</span>
            <strong>{formatInt(stats.audit)}</strong>
            <small>последние 100 записей</small>
          </div>
        </div>

        <section className="admin-panel" aria-labelledby="admin-servers-title">
          <div className="admin-panel__head">
            <div>
              <h2 id="admin-servers-title">Инвентарь</h2>
              <p>Нажмите «Развернуть», чтобы запустить задачу с логом в реальном времени.</p>
            </div>
          </div>

          {serversQuery.isLoading ? (
            <div className="admin-server-grid" aria-hidden="true">
              {Array.from({ length: 2 }, (_, index) => (
                <Skeleton key={index} height="340px" style={{ borderRadius: 14 }} />
              ))}
            </div>
          ) : serversQuery.isError ? (
            <ErrorState
              title="Не удалось загрузить серверы"
              message={adminErrorMessage(serversQuery.error)}
              onRetry={() => void serversQuery.refetch()}
            />
          ) : servers.length === 0 ? (
            <EmptyState
              icon="server"
              title="Серверов пока нет"
              description="Добавьте первый узел, назначьте сервисы и запустите развёртывание."
              action={
                <button
                  type="button"
                  className="btn btn--primary"
                  onClick={() => {
                    setEditingServer(null);
                    setFormOpen(true);
                  }}
                >
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
                  updatePending={updatePendingId === server.id}
                  healthPending={healthPendingId === server.id}
                  onEdit={(target) => {
                    setEditingServer(target);
                    setFormOpen(true);
                  }}
                  onDeploy={setDeployTarget}
                  onDelete={setDeleteTarget}
                  onToggleEnabled={(target) =>
                    updateMutation.mutate({ server: target, patch: { enabled: !target.enabled } })
                  }
                  onToggleFallback={(target) =>
                    updateMutation.mutate({ server: target, patch: { is_fallback: !target.is_fallback } })
                  }
                  onHealth={(target) => healthMutation.mutate(target)}
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
            <button
              type="button"
              className="btn btn--outline btn--sm"
              onClick={() => syncMutation.mutate()}
              disabled={syncMutation.isPending}
            >
              {syncMutation.isPending ? (
                <DancingSpinner size={15} />
              ) : (
                <Icon name="refresh" size={15} />
              )}
              Синхронизировать
            </button>
          </div>

          {registryQuery.isLoading ? (
            <div className="admin-registry-grid" aria-hidden="true">
              {Array.from({ length: 4 }, (_, index) => (
                <Skeleton key={index} height="150px" style={{ borderRadius: 12 }} />
              ))}
            </div>
          ) : registryQuery.isError ? (
            <ErrorState
              title="Реестр недоступен"
              message={adminErrorMessage(registryQuery.error)}
              onRetry={() => void registryQuery.refetch()}
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

        <section className="admin-panel" aria-labelledby="admin-audit-title">
          <div className="admin-panel__head">
            <div>
              <h2 id="admin-audit-title">Аудит</h2>
              <p>Последние 100 действий control-сервиса.</p>
            </div>
          </div>
          {auditQuery.isLoading ? (
            <Skeleton height="180px" />
          ) : auditQuery.isError ? (
            <ErrorState
              title="Аудит недоступен"
              message={adminErrorMessage(auditQuery.error)}
              onRetry={() => void auditQuery.refetch()}
            />
          ) : audit.length === 0 ? (
            <EmptyState compact icon="list" title="Событий пока нет" description="Здесь появятся действия с серверами и маршрутами." />
          ) : (
            <div className="admin-table-wrap">
              <table className="admin-table">
                <thead>
                  <tr>
                    <th>Действие</th>
                    <th>Сервер</th>
                    <th>Время</th>
                    <th>Детали</th>
                  </tr>
                </thead>
                <tbody>
                  {audit.map((entry) => (
                    <tr key={entry.id}>
                      <td>
                        <span className="admin-audit-action">{AUDIT_LABELS[entry.action] ?? entry.action}</span>
                      </td>
                      <td>
                        {entry.server_id ? serverNames.get(entry.server_id) ?? entry.server_id.slice(0, 8) : '—'}
                      </td>
                      <td className="admin-table__time">{formatDateTime(entry.created_at)}</td>
                      <td>
                        <code className="admin-audit-details">{detailsSummary(entry)}</code>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <footer className="admin-footer">
          MangaPoisk Reborn · Control · сессия администратора только в этой вкладке
        </footer>
      </main>

      <ServerFormModal
        open={formOpen}
        server={editingServer}
        servers={servers}
        onClose={() => {
          setFormOpen(false);
          setEditingServer(null);
        }}
      />
      <DeployModal open={Boolean(deployTarget)} server={deployTarget} onClose={() => setDeployTarget(null)} />

      <Modal
        open={Boolean(deleteTarget)}
        onClose={() => setDeleteTarget(null)}
        title="Удалить сервер?"
        size="sm"
        footer={
          <>
            <button type="button" className="btn btn--ghost" onClick={() => setDeleteTarget(null)}>
              Отмена
            </button>
            <button
              type="button"
              className="btn btn--danger"
              onClick={() => deleteTarget && deleteMutation.mutate(deleteTarget)}
              disabled={deleteMutation.isPending}
            >
              {deleteMutation.isPending ? (
                <>
                  <DancingSpinner size={16} />
                  Удаляем…
                </>
              ) : (
                <>
                  <Icon name="trash" size={16} />
                  Удалить
                </>
              )}
            </button>
          </>
        }
      >
        <p className="admin-confirm__text">
          Сервер <strong>{deleteTarget?.name}</strong> и его inventory будут удалены. Уже запущенные
          процессы на самом узле это действие не останавливает.
        </p>
      </Modal>

      <Modal
        open={failoverOpen}
        onClose={() => setFailoverOpen(false)}
        title="Failover маршрутов?"
        size="sm"
        footer={
          <>
            <button type="button" className="btn btn--ghost" onClick={() => setFailoverOpen(false)}>
              Отмена
            </button>
            <button
              type="button"
              className="btn btn--danger"
              onClick={() => failoverMutation.mutate()}
              disabled={failoverMutation.isPending}
            >
              {failoverMutation.isPending ? (
                <>
                  <DancingSpinner size={16} />
                  Переключаем…
                </>
              ) : (
                <>
                  <Icon name="alert" size={16} />
                  Выполнить failover
                </>
              )}
            </button>
          </>
        }
      >
        <p className="admin-confirm__text">
          Gateway принудительно выберет первые здоровые резервные endpoint для parser, catalog,
          library и media. Используйте, если основной контур недоступен.
        </p>
      </Modal>
    </div>
  );
}

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
        {endpoint.last_error ? <span className="admin-registry-row__error">{healthErrorText(endpoint.last_error)}</span> : null}
      </div>
      <span className="admin-registry-row__checked">
        {endpoint.checked_at ? formatDateTime(endpoint.checked_at) : 'не проверялся'}
      </span>
    </div>
  );
}
