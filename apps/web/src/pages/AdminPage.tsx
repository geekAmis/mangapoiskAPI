import {
  lazy,
  Suspense,
  useEffect,
  useLayoutEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ADMIN_UNAUTHORIZED_EVENT,
  adminApi,
  adminErrorMessage,
  getAdminToken,
  isAdminUnauthorized,
  setAdminToken,
  type AdminRegistry,
  type AdminServer,
} from '../api/admin';
import { Icon } from '../components/Icon';
import { DancingSpinner } from '../components/DancingLoader';
import { Modal } from '../components/Modal';
import { Skeleton } from '../components/Skeleton';
import { AdminLogin } from '../components/admin/AdminLogin';
import { DeployModal } from '../components/admin/DeployModal';
import { ServerFormModal } from '../components/admin/ServerFormModal';
import { useDocumentTitle } from '../lib/hooks';
import { toast } from '../stores/toast';
import { AdminTabs, type AdminTabBadge } from './admin/AdminTabs';
import { adminTabDefinition, parseAdminTab, type AdminTabId } from './admin/tabs';
import '../styles/admin.css';

const OverviewPanel = lazy(() =>
  import('./admin/OverviewPanel').then((module) => ({ default: module.OverviewPanel })),
);
const ServersPanel = lazy(() =>
  import('./admin/ServersPanel').then((module) => ({ default: module.ServersPanel })),
);
const DeployPanel = lazy(() =>
  import('./admin/DeployPanel').then((module) => ({ default: module.DeployPanel })),
);
const CrawlerPanel = lazy(() =>
  import('./admin/CrawlerPanel').then((module) => ({ default: module.CrawlerPanel })),
);
const MediaStoragePanel = lazy(() =>
  import('../components/admin/MediaStoragePanel').then((module) => ({
    default: module.MediaStoragePanel,
  })),
);
const AdsPanel = lazy(() =>
  import('../components/admin/AdsPanel').then((module) => ({ default: module.AdsPanel })),
);
const CommentsPanel = lazy(() =>
  import('./admin/CommentsPanel').then((module) => ({ default: module.CommentsPanel })),
);
const IntegrationsPanel = lazy(() =>
  import('./admin/IntegrationsPanel').then((module) => ({ default: module.IntegrationsPanel })),
);
const AuditPanel = lazy(() =>
  import('./admin/AuditPanel').then((module) => ({ default: module.AuditPanel })),
);
const TerminalPanel = lazy(() =>
  import('./admin/TerminalPanel').then((module) => ({ default: module.TerminalPanel })),
);

function PanelFallback() {
  return (
    <div className="admin-panel" aria-hidden="true">
      <Skeleton height="220px" style={{ borderRadius: 14 }} />
    </div>
  );
}

function TabPanel({
  id,
  active,
  children,
}: {
  id: AdminTabId;
  active: boolean;
  children: ReactNode;
}) {
  return (
    <div
      id={`admin-panel-${id}`}
      role="tabpanel"
      aria-labelledby={`admin-tab-${id}`}
      hidden={!active}
    >
      <Suspense fallback={<PanelFallback />}>{children}</Suspense>
    </div>
  );
}

export default function AdminPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const activeTab = parseAdminTab(searchParams.get('tab'));
  const selectedServerId = searchParams.get('server');
  const currentTab = adminTabDefinition(activeTab);
  useDocumentTitle(`Control — ${currentTab.label} — MangaPoisk Reborn`);

  const queryClient = useQueryClient();
  const [token, setTokenState] = useState<string | null>(() => getAdminToken());
  const [visited, setVisited] = useState<Set<AdminTabId>>(() => new Set([activeTab]));
  const [formOpen, setFormOpen] = useState(false);
  const [editingServer, setEditingServer] = useState<AdminServer | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<AdminServer | null>(null);
  const [promoteTarget, setPromoteTarget] = useState<AdminServer | null>(null);
  const [deployTarget, setDeployTarget] = useState<AdminServer | null>(null);
  const [failoverOpen, setFailoverOpen] = useState(false);

  useEffect(() => {
    setVisited((previous) => {
      if (previous.has(activeTab)) return previous;
      const next = new Set(previous);
      next.add(activeTab);
      return next;
    });
  }, [activeTab]);

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

  const jobsQuery = useQuery({
    queryKey: ['admin', 'jobs'],
    queryFn: ({ signal }) => adminApi.listJobs(30, signal),
    enabled: Boolean(token),
    retry: 1,
    refetchInterval: 15_000,
  });

  const registryQuery = useQuery({
    queryKey: ['admin', 'registry'],
    queryFn: ({ signal }) => adminApi.getRegistry(signal),
    enabled: Boolean(token) && activeTab === 'servers',
    retry: 1,
  });

  const auditQuery = useQuery({
    queryKey: ['admin', 'audit'],
    queryFn: ({ signal }) => adminApi.getAudit(100, signal),
    enabled: Boolean(token) && (activeTab === 'audit' || activeTab === 'overview'),
    retry: 1,
  });

  const catalogueQuery = useQuery({
    queryKey: ['admin', 'catalogue'],
    queryFn: ({ signal }) => adminApi.getCatalogueHealth(signal),
    enabled: Boolean(token) && (activeTab === 'crawler' || activeTab === 'overview'),
    retry: 1,
    refetchInterval: 60_000,
  });

  const servers = serversQuery.data ?? [];
  const jobs = jobsQuery.data ?? [];
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
    onError: (error: unknown) =>
      toast.error(adminErrorMessage(error, 'Не удалось синхронизировать маршруты.')),
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
    mutationFn: (variables: {
      server: AdminServer;
      patch: { enabled?: boolean; is_fallback?: boolean };
    }) => adminApi.updateServer(variables.server.id, variables.patch),
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
      const unhealthy = health.services.filter(
        (service) => service.code !== 'scheduler' && !service.healthy,
      ).length;
      if (health.healthy) toast.success(`${health.name}: все сервисы здоровы`);
      else toast.error(`${health.name}: проблемных сервисов — ${unhealthy}`);
      void queryClient.invalidateQueries({ queryKey: ['admin', 'servers'] });
      void queryClient.invalidateQueries({ queryKey: ['admin', 'audit'] });
    },
    onError: (error: unknown) => toast.error(adminErrorMessage(error, 'Health-check не удался.')),
  });

  const promoteMutation = useMutation({
    mutationFn: (server: AdminServer) => adminApi.promoteReplica(server.id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['admin', 'servers'] });
      void queryClient.invalidateQueries({ queryKey: ['admin', 'registry'] });
      void queryClient.invalidateQueries({ queryKey: ['admin', 'audit'] });
      toast.success('Данные восстановлены из последней реплики');
      setPromoteTarget(null);
    },
    onError: (error: unknown) => {
      toast.error(adminErrorMessage(error, 'Не удалось восстановить данные из реплики.'));
      setPromoteTarget(null);
    },
  });

  const changeTab = (tab: AdminTabId) => {
    setSearchParams(
      (previous) => {
        const next = new URLSearchParams(previous);
        next.set('tab', tab);
        // Keep `server` so returning to the terminal restores the selected
        // server and its in-memory command draft instead of losing it.
        return next;
      },
      { replace: false },
    );
  };

  const openConsole = (serverId: string) => {
    setSearchParams(
      (previous) => {
        const next = new URLSearchParams(previous);
        next.set('tab', 'terminal');
        next.set('server', serverId);
        return next;
      },
      { replace: false },
    );
  };

  const selectConsoleServer = (serverId: string | null) => {
    setSearchParams(
      (previous) => {
        const next = new URLSearchParams(previous);
        next.set('tab', 'terminal');
        if (serverId) next.set('server', serverId);
        else next.delete('server');
        return next;
      },
      { replace: true },
    );
  };

  const refreshAll = () => {
    void serversQuery.refetch();
    void jobsQuery.refetch();
    if (activeTab === 'servers') void registryQuery.refetch();
    if (activeTab === 'audit' || activeTab === 'overview') void auditQuery.refetch();
    if (activeTab === 'crawler' || activeTab === 'overview') void catalogueQuery.refetch();
    void meQuery.refetch();
  };

  const logout = () => {
    setAdminToken(null);
    setTokenState(null);
    queryClient.removeQueries({ queryKey: ['admin'] });
    toast.info('Вы вышли из Control');
  };

  const lastDeployByServer = useMemo(() => {
    const result = new Map<string, string>();
    for (const job of jobs) {
      if (job.status !== 'done' || !job.created_at) continue;
      const current = result.get(job.server_id);
      if (!current || job.created_at > current) result.set(job.server_id, job.created_at);
    }
    return result;
  }, [jobs]);

  const badges = useMemo<Partial<Record<AdminTabId, AdminTabBadge>>>(() => {
    const httpServices = servers.flatMap((server) =>
      server.services.filter((service) => service.code !== 'scheduler'),
    );
    const unhealthy = httpServices.filter((service) => !service.healthy).length;
    const activeJobs = jobs.filter(
      (job) => job.status === 'queued' || job.status === 'running',
    ).length;
    const next: Partial<Record<AdminTabId, AdminTabBadge>> = {};
    if (unhealthy > 0) next.servers = { count: unhealthy, tone: 'danger' };
    if (activeJobs > 0) next.deploy = { count: activeJobs, tone: 'accent' };
    if (catalogueQuery.data) {
      const warnings =
        catalogueQuery.data.enrichment.failed +
        catalogueQuery.data.crawl_states.filter((state) => state.status === 'blocked').length;
      if (warnings > 0) next.crawler = { count: warnings, tone: 'warning' };
    }
    return next;
  }, [servers, jobs, catalogueQuery.data]);

  const refreshing =
    serversQuery.isFetching || jobsQuery.isFetching || registryQuery.isFetching || auditQuery.isFetching;

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
            <h1>{currentTab.label}</h1>
            <p>{currentTab.description}</p>
          </div>
          <div className="admin-actions">
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
          </div>
        </div>

        <AdminTabs active={activeTab} onChange={changeTab} badges={badges} />

        {meQuery.isError && !isAdminUnauthorized(meQuery.error) ? (
          <div className="admin-inline-error">
            <Icon name="alert" size={15} />
            Не удалось проверить сессию администратора.
          </div>
        ) : null}

        {visited.has('overview') ? (
          <TabPanel id="overview" active={activeTab === 'overview'}>
            <OverviewPanel
              servers={servers}
              serversLoading={serversQuery.isLoading}
              serversError={serversQuery.isError}
              jobs={jobs}
              jobsLoading={jobsQuery.isLoading}
              audit={audit}
              auditLoading={auditQuery.isLoading}
              catalogue={catalogueQuery.data}
              onOpenTab={changeTab}
              onOpenConsole={openConsole}
            />
          </TabPanel>
        ) : null}

        {visited.has('servers') ? (
          <TabPanel id="servers" active={activeTab === 'servers'}>
            <ServersPanel
              servers={servers}
              lastDeployByServer={lastDeployByServer}
              serversLoading={serversQuery.isLoading}
              serversError={serversQuery.isError}
              serversFetching={serversQuery.isFetching}
              registry={registry}
              registryLoading={registryQuery.isLoading}
              registryError={registryQuery.isError}
              updatePendingId={updateMutation.isPending ? updateMutation.variables?.server.id ?? null : null}
              healthPendingId={healthMutation.isPending ? healthMutation.variables?.id ?? null : null}
              syncPending={syncMutation.isPending}
              failoverPending={failoverMutation.isPending}
              onRefresh={() => {
                void serversQuery.refetch();
                void registryQuery.refetch();
              }}
              onSync={() => syncMutation.mutate()}
              onFailover={() => setFailoverOpen(true)}
              onAdd={() => {
                setEditingServer(null);
                setFormOpen(true);
              }}
              onEdit={(target) => {
                setEditingServer(target);
                setFormOpen(true);
              }}
              onDeploy={setDeployTarget}
              onPromote={setPromoteTarget}
              onDelete={setDeleteTarget}
              onToggleEnabled={(target) =>
                updateMutation.mutate({ server: target, patch: { enabled: !target.enabled } })
              }
              onToggleFallback={(target) =>
                updateMutation.mutate({ server: target, patch: { is_fallback: !target.is_fallback } })
              }
              onHealth={(target) => healthMutation.mutate(target)}
              onConsole={(target) => openConsole(target.id)}
              onRetryServers={() => void serversQuery.refetch()}
              onRetryRegistry={() => void registryQuery.refetch()}
            />
          </TabPanel>
        ) : null}

        {visited.has('deploy') ? (
          <TabPanel id="deploy" active={activeTab === 'deploy'}>
            <DeployPanel
              jobs={jobs}
              loading={jobsQuery.isLoading}
              error={jobsQuery.isError}
              servers={servers}
              active={activeTab === 'deploy'}
              onRetry={() => void jobsQuery.refetch()}
            />
          </TabPanel>
        ) : null}

        {visited.has('crawler') ? (
          <TabPanel id="crawler" active={activeTab === 'crawler'}>
            <CrawlerPanel
              catalogue={catalogueQuery.data}
              catalogueLoading={catalogueQuery.isLoading}
              catalogueError={catalogueQuery.isError}
              catalogueFetching={catalogueQuery.isFetching}
              active={activeTab === 'crawler'}
              onRetry={() => void catalogueQuery.refetch()}
            />
          </TabPanel>
        ) : null}

        {visited.has('media') ? (
          <TabPanel id="media" active={activeTab === 'media'}>
            <MediaStoragePanel active={activeTab === 'media'} />
          </TabPanel>
        ) : null}

        {visited.has('ads') ? (
          <TabPanel id="ads" active={activeTab === 'ads'}>
            <AdsPanel />
          </TabPanel>
        ) : null}

        {visited.has('comments') ? (
          <TabPanel id="comments" active={activeTab === 'comments'}>
            <CommentsPanel />
          </TabPanel>
        ) : null}

        {visited.has('integrations') ? (
          <TabPanel id="integrations" active={activeTab === 'integrations'}>
            <IntegrationsPanel />
          </TabPanel>
        ) : null}

        {visited.has('audit') ? (
          <TabPanel id="audit" active={activeTab === 'audit'}>
            <AuditPanel
              audit={audit}
              loading={auditQuery.isLoading}
              error={auditQuery.isError}
              servers={servers}
              onRetry={() => void auditQuery.refetch()}
            />
          </TabPanel>
        ) : null}

        {visited.has('terminal') ? (
          <TabPanel id="terminal" active={activeTab === 'terminal'}>
            <TerminalPanel
              servers={servers}
              serversLoading={serversQuery.isLoading}
              serversError={serversQuery.isError}
              selectedServerId={selectedServerId}
              active={activeTab === 'terminal'}
              onSelectServer={selectConsoleServer}
              onOpenDeploy={() => changeTab('deploy')}
              onRetryServers={() => void serversQuery.refetch()}
            />
          </TabPanel>
        ) : null}

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
        open={Boolean(promoteTarget)}
        onClose={() => (promoteMutation.isPending ? undefined : setPromoteTarget(null))}
        title="Восстановить данные из реплики?"
        size="sm"
        footer={
          <>
            <button
              type="button"
              className="btn btn--ghost"
              onClick={() => setPromoteTarget(null)}
              disabled={promoteMutation.isPending}
            >
              Отмена
            </button>
            <button
              type="button"
              className="btn btn--primary"
              onClick={() => promoteTarget && promoteMutation.mutate(promoteTarget)}
              disabled={promoteMutation.isPending}
            >
              {promoteMutation.isPending ? (
                <>
                  <DancingSpinner size={16} />
                  Восстанавливаем…
                </>
              ) : (
                <>
                  <Icon name="refresh" size={16} />
                  Восстановить
                </>
              )}
            </button>
          </>
        }
      >
        <p className="field__hint">
          Control остановит <code>catalog</code>, <code>library</code> и <code>media</code> на сервере{' '}
          <strong>{promoteTarget?.name}</strong>, скопирует последнюю реплику баз в рабочие файлы и
          запустит сервисы снова. Операция занимает несколько секунд; сессия админки не прерывается.
        </p>
      </Modal>

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
