import type { AdminServer } from '../../api/admin';
import { ADMIN_SERVICES, healthErrorText } from '../../api/admin';
import { formatRelative } from '../../lib/format';
import { Icon } from '../Icon';
import { DancingSpinner } from '../DancingLoader';

interface AdminServerCardProps {
  server: AdminServer;
  lastDeployAt: string | null;
  updatePending: boolean;
  healthPending: boolean;
  onEdit: (server: AdminServer) => void;
  onDeploy: (server: AdminServer) => void;
  onPromote: (server: AdminServer) => void;
  onDelete: (server: AdminServer) => void;
  onToggleEnabled: (server: AdminServer) => void;
  onToggleFallback: (server: AdminServer) => void;
  onHealth: (server: AdminServer) => void;
  onConsole: (server: AdminServer) => void;
}

function serviceLabel(code: string): string {
  return ADMIN_SERVICES.find((service) => service.code === code)?.label ?? code;
}

export function AdminServerCard({
  server,
  lastDeployAt,
  updatePending,
  healthPending,
  onEdit,
  onDeploy,
  onPromote,
  onDelete,
  onToggleEnabled,
  onToggleFallback,
  onHealth,
  onConsole,
}: AdminServerCardProps) {
  // Scheduler не имеет HTTP health-check: он не входит ни в числитель, ни
  // в знаменатель. Replica — обычный HTTP-сервис и считается как все.
  const httpServices = server.services.filter((service) => service.code !== 'scheduler');
  const healthy = httpServices.filter((service) => service.healthy).length;
  const checked = httpServices.length;
  const lastCheck = server.services
    .map((service) => service.checked_at)
    .filter((value): value is string => Boolean(value))
    .sort()
    .at(-1);

  return (
    <article className={`admin-server-card${server.enabled ? '' : ' is-disabled'}`}>
      <header className="admin-server-card__head">
        <div>
          <h3>{server.name}</h3>
          <div className="admin-server-card__host">
            <Icon name="server" size={14} />
            <code>
              {server.username}@{server.host}:{server.ssh_port}
            </code>
          </div>
        </div>
        <div className="admin-badges">
          <span className={`badge ${server.enabled ? 'badge--success' : 'badge--danger'}`}>
            {server.enabled ? 'Включён' : 'Отключён'}
          </span>
          {server.is_fallback ? <span className="badge badge--accent">Резерв</span> : null}
          {server.is_jump ? <span className="badge">Jump</span> : null}
          <span className="badge" title="Приоритет: меньшее число важнее">
            P{server.priority}
          </span>
        </div>
      </header>

      <div className="admin-server-card__meta">
        <div>
          <span>Public host</span>
          <strong>{server.public_host || '—'}</strong>
        </div>
        <div>
          <span>Bind host</span>
          <strong>{server.bind_host}</strong>
        </div>
        <div>
          <span>Jump</span>
          <strong>{server.jump_server_name || '—'}</strong>
        </div>
        <div>
          <span>Здоровье</span>
          <strong>
            {healthy} / {checked}{' '}
            {lastCheck ? <span className="admin-server-card__since">· {formatRelative(lastCheck)}</span> : null}
          </strong>
        </div>
        <div>
          <span>Последний деплой</span>
          <strong>{lastDeployAt ? formatRelative(lastDeployAt) : '—'}</strong>
        </div>
      </div>

      {server.notes ? <p className="admin-server-card__notes">{server.notes}</p> : null}

      <div className="admin-server-card__services">
        {server.services.length > 0 ? (
          server.services.map((service) => (
            <span
              key={service.code}
              className="admin-service-pill"
              title={
                service.code === 'scheduler'
                  ? 'Scheduler не имеет HTTP health-check'
                  : service.last_error
                    ? healthErrorText(service.last_error)
                    : service.checked_at
                      ? `Проверено ${formatRelative(service.checked_at)}`
                      : 'Ещё не проверялся'
              }
            >
              <span
                className={`admin-health-dot ${
                  service.code === 'scheduler' ? 'is-wait' : service.healthy ? 'is-ok' : 'is-bad'
                }`}
              />
              {serviceLabel(service.code)}
              <code>:{service.port}</code>
            </span>
          ))
        ) : (
          <span className="field__hint">Сервисы не назначены</span>
        )}
      </div>

      <div className="admin-server-card__actions">
        <button
          type="button"
          className="btn btn--primary btn--sm"
          onClick={() => onDeploy(server)}
          title="Установить выбранные сервисы через SSH"
        >
          <Icon name="download" size={15} />
          Развернуть
        </button>
        <button
          type="button"
          className="btn btn--outline btn--sm"
          onClick={() => onEdit(server)}
        >
          <Icon name="edit" size={15} />
          Изменить
        </button>
        <button
          type="button"
          className="btn btn--soft btn--sm"
          onClick={() => onConsole(server)}
          title="Открыть ограниченную серверную консоль"
        >
          <Icon name="terminal" size={15} />
          Консоль
        </button>
        <button
          type="button"
          className="btn btn--ghost btn--sm"
          onClick={() => onPromote(server)}
          title="Скопировать последнюю реплику БД в рабочие файлы и перезапустить сервисы"
        >
          <Icon name="refresh" size={15} />
          Восстановить
        </button>
        <button
          type="button"
          className="btn btn--ghost btn--sm"
          onClick={() => onHealth(server)}
          disabled={healthPending}
          title="Запросить health-check"
        >
          {healthPending ? <DancingSpinner size={15} /> : <Icon name="shield" size={15} />}
          Проверить
        </button>
        <button
          type="button"
          className="btn btn--ghost btn--sm"
          onClick={() => onToggleEnabled(server)}
          disabled={updatePending}
          aria-pressed={server.enabled}
        >
          <Icon name="power" size={15} />
          {server.enabled ? 'Выключить' : 'Включить'}
        </button>
        <button
          type="button"
          className={`btn btn--sm ${server.is_fallback ? 'btn--soft' : 'btn--ghost'}`}
          onClick={() => onToggleFallback(server)}
          disabled={updatePending}
          aria-pressed={server.is_fallback}
        >
          <Icon name="shield" size={15} />
          {server.is_fallback ? 'Резервный' : 'В резерв'}
        </button>
        <button
          type="button"
          className="btn btn--ghost btn--icon btn--sm admin-server-card__delete"
          onClick={() => onDelete(server)}
          aria-label={`Удалить сервер ${server.name}`}
          title="Удалить сервер"
        >
          <Icon name="trash" size={16} />
        </button>
      </div>
    </article>
  );
}
