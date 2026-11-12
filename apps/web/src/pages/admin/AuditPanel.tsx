import type { AdminAuditEntry, AdminServer } from '../../api/admin';
import { EmptyState } from '../../components/EmptyState';
import { ErrorState } from '../../components/ErrorState';
import { Skeleton } from '../../components/Skeleton';
import { formatDateTime } from '../../lib/format';

interface AuditPanelProps {
  audit: AdminAuditEntry[];
  loading: boolean;
  error: unknown;
  servers: AdminServer[];
  onRetry: () => void;
}

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
  'deployment.rollback_started': 'Запущен rollback',
  'deployment.rollback_finished': 'Rollback завершён',
  'registry.synced': 'Маршруты синхронизированы',
  'registry.sync': 'Маршруты синхронизированы',
  'failover.applied': 'Failover выполнен',
  'health.checked': 'Health-check',
  'ads.provider_created': 'Добавлена рекламная интеграция',
  'ads.provider_updated': 'Обновлена рекламная интеграция',
  'ads.provider_deleted': 'Удалена рекламная интеграция',
  'ads.secret_set': 'Рекламный ключ сохранён',
  'ads.secret_deleted': 'Рекламный ключ удалён',
  'console.command': 'Консоль: команда',
  'console.action': 'Консоль: действие',
};

function detailsSummary(entry: AdminAuditEntry): string {
  const details = entry.details ?? {};
  const preferred = [
    'admin',
    'command',
    'action',
    'service',
    'services',
    'job_id',
    'host',
    'port',
    'url',
    'name',
    'exit_code',
    'output_hash',
    'rejected',
    'duration_ms',
  ];
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
  return text.length > 180 ? `${text.slice(0, 179)}…` : text;
}

export function AuditPanel({ audit, loading, error, servers, onRetry }: AuditPanelProps) {
  const serverNames = new Map(servers.map((server) => [server.id, server.name]));

  return (
    <section className="admin-panel" aria-labelledby="admin-audit-title">
      <div className="admin-panel__head">
        <div>
          <h2 id="admin-audit-title">Аудит</h2>
          <p>
            Последние 100 действий control-сервиса. Для консоли сохраняются
            администратор, сервер, команда/действие, exit code и хеш вывода.
          </p>
        </div>
      </div>
      {loading ? (
        <Skeleton height="180px" />
      ) : error ? (
        <ErrorState
          title="Аудит недоступен"
          message="Не удалось получить журнал control-сервиса."
          onRetry={onRetry}
        />
      ) : audit.length === 0 ? (
        <EmptyState
          compact
          icon="list"
          title="Событий пока нет"
          description="Здесь появятся действия с серверами, маршрутами и консолью."
        />
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
                    <span className="admin-audit-action">
                      {AUDIT_LABELS[entry.action] ?? entry.action}
                    </span>
                  </td>
                  <td>
                    {entry.server_id
                      ? serverNames.get(entry.server_id) ?? entry.server_id.slice(0, 8)
                      : '—'}
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
  );
}
