import { useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ADMIN_SERVICES,
  adminApi,
  adminErrorMessage,
  type AdminConsoleResult,
  type AdminServer,
} from '../../api/admin';
import { EmptyState } from '../../components/EmptyState';
import { ErrorState } from '../../components/ErrorState';
import { Icon } from '../../components/Icon';
import { DancingSpinner } from '../../components/DancingLoader';
import { Skeleton } from '../../components/Skeleton';
import { formatDateTime, formatInt } from '../../lib/format';
import { toast } from '../../stores/toast';

interface TerminalPanelProps {
  servers: AdminServer[];
  serversLoading: boolean;
  serversError: unknown;
  selectedServerId: string | null;
  active: boolean;
  onSelectServer: (serverId: string | null) => void;
  onOpenDeploy: () => void;
  onRetryServers: () => void;
}

const HISTORY_LIMIT = 40;

function storageKey(serverId: string): string {
  return `mp-admin-console-history:${serverId}`;
}

function loadHistory(serverId: string | null): string[] {
  if (!serverId) return [];
  try {
    const raw = window.localStorage.getItem(storageKey(serverId));
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    return Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === 'string') : [];
  } catch {
    return [];
  }
}

function saveHistory(serverId: string, values: string[]): void {
  try {
    window.localStorage.setItem(storageKey(serverId), JSON.stringify(values.slice(0, HISTORY_LIMIT)));
  } catch {
    /* приватный режим: история останется в памяти вкладки */
  }
}

function serviceLabel(code: string): string {
  return ADMIN_SERVICES.find((service) => service.code === code)?.label ?? code;
}

function serviceHttp(code: string): boolean {
  return ADMIN_SERVICES.find((service) => service.code === code)?.http ?? false;
}

function resultClass(result: AdminConsoleResult | null): string {
  if (!result) return '';
  if (result.timed_out) return 'is-timeout';
  return result.ok ? 'is-ok' : 'is-bad';
}

export function TerminalPanel({
  servers,
  serversLoading,
  serversError,
  selectedServerId,
  active,
  onSelectServer,
  onOpenDeploy,
  onRetryServers,
}: TerminalPanelProps) {
  const queryClient = useQueryClient();
  const outputRef = useRef<HTMLDivElement>(null);
  const [command, setCommand] = useState('');
  const [result, setResult] = useState<AdminConsoleResult | null>(null);
  const [error, setError] = useState('');
  const [history, setHistory] = useState<string[]>(() => loadHistory(selectedServerId));
  const [historyIndex, setHistoryIndex] = useState(-1);
  const [serviceCode, setServiceCode] = useState<string>('');
  const [portValue, setPortValue] = useState('8100');
  const [addCode, setAddCode] = useState<string>('');
  const [addPort, setAddPort] = useState('8110');
  const [busyAction, setBusyAction] = useState<string | null>(null);

  const server = servers.find((item) => item.id === selectedServerId) ?? null;
  const configured = useMemo(() => server?.services ?? [], [server]);
  const available = useMemo(
    () => ADMIN_SERVICES.filter((service) => !configured.some((item) => item.code === service.code)),
    [configured],
  );

  useEffect(() => {
    setHistory(loadHistory(selectedServerId));
    setHistoryIndex(-1);
    setResult(null);
    setError('');
  }, [selectedServerId]);

  useEffect(() => {
    if (!server) {
      setServiceCode('');
      return;
    }
    if (!server.services.some((item) => item.code === serviceCode)) {
      setServiceCode(server.services[0]?.code ?? '');
    }
    const currentPort = server.services.find((item) => item.code === serviceCode)?.port;
    if (currentPort) setPortValue(String(currentPort));
  }, [server, serviceCode]);

  useEffect(() => {
    if (!available.some((service) => service.code === addCode)) {
      setAddCode(available[0]?.code ?? '');
    }
  }, [available, addCode]);

  useEffect(() => {
    if (outputRef.current) outputRef.current.scrollTop = outputRef.current.scrollHeight;
  }, [result]);

  const historyQuery = useQuery({
    queryKey: ['admin', 'console-history', selectedServerId],
    queryFn: ({ signal }) => adminApi.consoleHistory(selectedServerId ?? '', 50, signal),
    enabled: active && Boolean(selectedServerId),
    retry: 1,
  });

  const commandMutation = useMutation({
    mutationFn: (value: string) => {
      if (!selectedServerId) throw new Error('Сервер не выбран');
      return adminApi.console(selectedServerId, { command: value });
    },
    onSuccess: (next, value) => {
      setResult(next);
      setError('');
      setCommand('');
      setHistory((current) => {
        const merged = [value, ...current.filter((item) => item !== value)].slice(0, HISTORY_LIMIT);
        if (selectedServerId) saveHistory(selectedServerId, merged);
        return merged;
      });
      setHistoryIndex(-1);
      void queryClient.invalidateQueries({ queryKey: ['admin', 'console-history', selectedServerId] });
      void queryClient.invalidateQueries({ queryKey: ['admin', 'audit'] });
    },
    onError: (mutationError) => {
      setResult(null);
      setError(adminErrorMessage(mutationError, 'Команда отклонена или сервер недоступен.'));
    },
  });

  const actionMutation = useMutation({
    mutationFn: (payload: { action: string; params?: Record<string, unknown> }) => {
      if (!selectedServerId) throw new Error('Сервер не выбран');
      return adminApi.console(selectedServerId, payload);
    },
    onSuccess: (next) => {
      setResult(next);
      setError('');
      setBusyAction(null);
      void queryClient.invalidateQueries({ queryKey: ['admin', 'console-history', selectedServerId] });
      void queryClient.invalidateQueries({ queryKey: ['admin', 'audit'] });
      void queryClient.invalidateQueries({ queryKey: ['admin', 'jobs'] });
      void queryClient.invalidateQueries({ queryKey: ['admin', 'servers'] });
      if (next.job_id) {
        toast.success(next.message ?? 'Задача control запущена');
      } else {
        toast.success(next.message ?? 'Действие выполнено');
      }
    },
    onError: (mutationError) => {
      setBusyAction(null);
      setResult(null);
      setError(adminErrorMessage(mutationError, 'Действие отклонено или сервер недоступен.'));
    },
  });

  const runCommand = (value: string) => {
    const trimmed = value.trim();
    if (!trimmed || commandMutation.isPending) return;
    setError('');
    commandMutation.mutate(trimmed);
  };

  const submitCommand = (event: FormEvent) => {
    event.preventDefault();
    runCommand(command);
  };

  const onCommandKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'ArrowUp') {
      event.preventDefault();
      if (history.length === 0) return;
      const next = Math.min(history.length - 1, historyIndex + 1);
      setHistoryIndex(next);
      setCommand(history[next]);
      return;
    }
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      const next = historyIndex - 1;
      setHistoryIndex(next);
      setCommand(next >= 0 ? history[next] ?? '' : '');
    }
  };

  const runAction = (action: string, params?: Record<string, unknown>) => {
    setBusyAction(action);
    actionMutation.mutate({ action, params });
  };

  const selectedService = configured.find((item) => item.code === serviceCode);
  const selectedPort = selectedService?.port;
  const canHealth = Boolean(selectedService && serviceHttp(selectedService.code) && selectedPort);

  const quickCommands = useMemo(() => {
    if (!server) return [];
    const items: Array<{ label: string; command: string; icon: 'shield' | 'list' | 'terminal' | 'server' }> = [];
    if (selectedService) {
      items.push({
        label: 'systemctl status',
        command: `systemctl status mangapoisk-${selectedService.code}`,
        icon: 'shield',
      });
      items.push({
        label: 'Журнал (100)',
        command: `journalctl -u mangapoisk-${selectedService.code} -n 100 --no-pager`,
        icon: 'list',
      });
    }
    if (canHealth && selectedPort) {
      items.push({
        label: 'Health',
        command: `curl -s 127.0.0.1:${selectedPort}/health`,
        icon: 'shield',
      });
    }
    items.push({ label: 'docker ps', command: 'docker ps', icon: 'terminal' });
    items.push({ label: 'ss -ltnp', command: 'ss -ltnp', icon: 'terminal' });
    items.push({ label: 'df -h', command: 'df -h', icon: 'server' });
    items.push({ label: 'free -h', command: 'free -h', icon: 'server' });
    items.push({ label: 'uptime', command: 'uptime', icon: 'server' });
    items.push({
      label: 'ls проекта',
      command: 'ls -la /opt/mangapoisk-reborn',
      icon: 'list',
    });
    return items;
  }, [server, selectedService, canHealth, selectedPort]);

  if (serversLoading) {
    return (
      <div className="admin-panel">
        <Skeleton height="180px" />
      </div>
    );
  }

  if (serversError) {
    return (
      <div className="admin-panel">
        <ErrorState
          title="Серверы недоступны"
          message="Не удалось загрузить inventory для консоли."
          onRetry={onRetryServers}
        />
      </div>
    );
  }

  if (servers.length === 0) {
    return (
      <div className="admin-panel">
        <EmptyState
          icon="terminal"
          title="Нет серверов для консоли"
          description="Сначала добавьте сервер в inventory на вкладке «Серверы»."
        />
      </div>
    );
  }

  return (
    <div className="admin-panel-stack">
      <section className="admin-panel" aria-labelledby="admin-terminal-title">
        <div className="admin-panel__head">
          <div>
            <h2 id="admin-terminal-title">Серверная консоль</h2>
            <p>
              Только allowlist read-only команд и структурированные действия.
              Это не произвольный shell: инъекции, sudo, секреты и чужие сервисы
              отклоняются до SSH-подключения.
            </p>
          </div>
          <span className="badge badge--accent">
            <Icon name="lock" size={13} />
            restricted
          </span>
        </div>

        <div className="console-server-list" role="list" aria-label="Серверы">
          {servers.map((item) => {
            const httpServices = item.services.filter((service) => service.code !== 'scheduler');
            const healthy = httpServices.filter((service) => service.healthy).length;
            return (
              <button
                key={item.id}
                type="button"
                role="listitem"
                className={`console-server${item.id === selectedServerId ? ' is-active' : ''}`}
                onClick={() => onSelectServer(item.id)}
              >
                <span className={`admin-health-dot ${healthy === httpServices.length ? 'is-ok' : 'is-bad'}`} />
                <span className="console-server__body">
                  <strong>{item.name}</strong>
                  <code>
                    {item.username}@{item.host}:{item.ssh_port}
                  </code>
                </span>
                <span className="console-server__meta">
                  {formatInt(healthy)} / {formatInt(httpServices.length)}
                </span>
              </button>
            );
          })}
        </div>
      </section>

      {!server ? (
        <section className="admin-panel">
          <EmptyState
            compact
            icon="terminal"
            title="Выберите сервер"
            description="Нажмите на карточку выше, чтобы открыть ограниченную консоль."
          />
        </section>
      ) : (
        <section className="admin-panel console-panel" aria-labelledby="admin-console-title">
          <div className="console-head">
            <div>
              <h2 id="admin-console-title">{server.name}</h2>
              <p>
                {server.username}@{server.host}:{server.ssh_port} ·{' '}
                {server.public_host || 'без public host'} · {configured.length} сервисов
              </p>
            </div>
            <button type="button" className="btn btn--ghost btn--sm" onClick={() => onSelectServer(null)}>
              <Icon name="close" size={14} />
              Сменить сервер
            </button>
          </div>

          <div className="console-toolbar">
            <label className="console-select">
              <span>Сервис</span>
              <select
                className="input"
                value={serviceCode}
                onChange={(event) => setServiceCode(event.target.value)}
              >
                {configured.length === 0 ? <option value="">нет сервисов</option> : null}
                {configured.map((item) => (
                  <option key={item.code} value={item.code}>
                    {serviceLabel(item.code)} · :{item.port}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              className="btn btn--outline btn--sm"
              disabled={!selectedService || busyAction !== null}
              onClick={() => {
                if (!selectedService) return;
                if (!window.confirm(`Перезапустить mangapoisk-${selectedService.code}?`)) return;
                runAction('service_restart', { service: selectedService.code });
              }}
            >
              {busyAction === 'service_restart' ? <DancingSpinner size={14} /> : <Icon name="refresh" size={14} />}
              Restart
            </button>
            <button
              type="button"
              className="btn btn--ghost btn--sm"
              disabled={!selectedService || busyAction !== null}
              onClick={() => {
                if (!selectedService) return;
                runAction('service_start', { service: selectedService.code });
              }}
            >
              Start
            </button>
            <button
              type="button"
              className="btn btn--ghost btn--sm"
              disabled={!selectedService || busyAction !== null}
              onClick={() => {
                if (!selectedService) return;
                if (!window.confirm(`Остановить mangapoisk-${selectedService.code}?`)) return;
                runAction('service_stop', { service: selectedService.code });
              }}
            >
              Stop
            </button>
            <button
              type="button"
              className="btn btn--primary btn--sm"
              disabled={busyAction !== null}
              onClick={() => runAction('deploy', { services: configured.map((item) => item.code), update: true })}
            >
              {busyAction === 'deploy' ? <DancingSpinner size={14} /> : <Icon name="download" size={14} />}
              Deploy
            </button>
            <button
              type="button"
              className="btn btn--danger-ghost btn--sm"
              disabled={busyAction !== null}
              onClick={() => {
                if (!window.confirm('Откатить сервер на предыдущий релиз (src.old)?')) return;
                runAction('rollback');
              }}
            >
              {busyAction === 'rollback' ? <DancingSpinner size={14} /> : <Icon name="refresh" size={14} />}
              Rollback
            </button>
          </div>

          <div className="console-quick" aria-label="Быстрые команды">
            {quickCommands.map((item) => (
              <button
                key={item.label}
                type="button"
                className="console-quick__button"
                onClick={() => runCommand(item.command)}
                disabled={commandMutation.isPending}
                title={item.command}
              >
                <Icon name={item.icon} size={14} />
                {item.label}
              </button>
            ))}
          </div>

          <div className={`console-window ${resultClass(result)}`}>
            <div className="console-window__bar">
              <span className="console-dots" aria-hidden="true">
                <i />
                <i />
                <i />
              </span>
              <span className="console-window__title">
                {result?.command ?? 'read-only console'}
              </span>
              {result ? (
                <span className="console-window__meta">
                  exit {result.exit_code ?? '—'} · {result.duration_ms} ms
                  {result.truncated ? ' · truncated' : ''}
                  {result.timed_out ? ' · timeout' : ''}
                </span>
              ) : null}
            </div>
            <div className="console-output" ref={outputRef} aria-live="polite" aria-label="Вывод консоли">
              {error ? (
                <p className="console-error">
                  <Icon name="alert" size={15} />
                  {error}
                </p>
              ) : result ? (
                <>
                  <pre>{result.output || '(пустой вывод)'}</pre>
                  {result.job_id ? (
                    <div className="console-job">
                      <span>control job {result.job_id.slice(0, 8)}</span>
                      <button type="button" className="btn btn--outline btn--sm" onClick={onOpenDeploy}>
                        Открыть задачу
                      </button>
                    </div>
                  ) : null}
                </>
              ) : (
                <p className="console-placeholder">
                  $ Выберите быструю команду или введите allowlist-команду ниже.
                </p>
              )}
            </div>
          </div>

          <form className="console-form" onSubmit={submitCommand}>
            <span className="console-prompt" aria-hidden="true">
              $
            </span>
            <input
              className="input console-input"
              value={command}
              onChange={(event) => setCommand(event.target.value)}
              onKeyDown={onCommandKeyDown}
              placeholder="systemctl status mangapoisk-gateway"
              aria-label="Команда серверной консоли"
              spellCheck={false}
              autoComplete="off"
            />
            <button
              type="submit"
              className="btn btn--primary"
              disabled={!command.trim() || commandMutation.isPending}
            >
              {commandMutation.isPending ? <DancingSpinner size={16} /> : <Icon name="play" size={16} />}
              Выполнить
            </button>
          </form>
          <p className="console-hint">
            Разрешены: systemctl status/is-active/is-failed mangapoisk-*, journalctl -u
            mangapoisk-* -n N, docker ps, ss -ltnp, df -h, free -h, uptime, curl
            localhost health, ls проекта. Ввод с ; | &amp; $ &gt; &lt; и sudo отклоняется.
          </p>

          <div className="console-actions-grid">
            <form
              className="console-action-card"
              onSubmit={(event) => {
                event.preventDefault();
                if (!selectedService) return;
                const port = Number(portValue);
                if (!Number.isInteger(port) || port < 1024 || port > 65535) {
                  setError('Порт должен быть целым числом от 1024 до 65535.');
                  return;
                }
                runAction('port_change', { service: selectedService.code, port });
              }}
            >
              <h3>Сменить порт</h3>
              <p>Только для сервиса из inventory. Порт 1024–65535.</p>
              <div className="console-action-row">
                <select
                  className="input"
                  value={serviceCode}
                  onChange={(event) => setServiceCode(event.target.value)}
                  aria-label="Сервис для смены порта"
                >
                  {configured.map((item) => (
                    <option key={item.code} value={item.code}>
                      {serviceLabel(item.code)}
                    </option>
                  ))}
                </select>
                <input
                  className="input"
                  type="number"
                  min={1024}
                  max={65535}
                  value={portValue}
                  onChange={(event) => setPortValue(event.target.value)}
                  aria-label="Новый порт"
                />
                <button type="submit" className="btn btn--outline btn--sm" disabled={!selectedService || busyAction !== null}>
                  Применить
                </button>
              </div>
            </form>

            <form
              className="console-action-card"
              onSubmit={(event) => {
                event.preventDefault();
                if (!addCode) return;
                const port = Number(addPort);
                if (!Number.isInteger(port) || port < 1024 || port > 65535) {
                  setError('Порт должен быть целым числом от 1024 до 65535.');
                  return;
                }
                runAction('add_service', { service: addCode, port });
              }}
            >
              <h3>Добавить сервис</h3>
              <p>Шаблон control: unit, env и health-check создаст deploy job.</p>
              <div className="console-action-row">
                <select
                  className="input"
                  value={addCode}
                  onChange={(event) => setAddCode(event.target.value)}
                  aria-label="Новый сервис"
                >
                  {available.length === 0 ? <option value="">все сервисы настроены</option> : null}
                  {available.map((service) => (
                    <option key={service.code} value={service.code}>
                      {service.label} · по умолчанию :{service.defaultPort}
                    </option>
                  ))}
                </select>
                <input
                  className="input"
                  type="number"
                  min={1024}
                  max={65535}
                  value={addPort}
                  onChange={(event) => setAddPort(event.target.value)}
                  aria-label="Порт нового сервиса"
                />
                <button type="submit" className="btn btn--outline btn--sm" disabled={!addCode || busyAction !== null}>
                  Добавить
                </button>
              </div>
            </form>
          </div>
        </section>
      )}

      {server ? (
        <section className="admin-panel" aria-labelledby="admin-console-history-title">
          <div className="admin-panel__head">
            <div>
              <h2 id="admin-console-history-title">История консоли</h2>
              <p>Аудит вызовов этого сервера: команда/действие, exit code и хеш вывода.</p>
            </div>
            <button
              type="button"
              className="btn btn--ghost btn--sm"
              onClick={() => void historyQuery.refetch()}
              disabled={historyQuery.isFetching}
            >
              {historyQuery.isFetching ? <DancingSpinner size={14} /> : <Icon name="refresh" size={14} />}
              Обновить
            </button>
          </div>
          {historyQuery.isLoading ? (
            <Skeleton height="120px" />
          ) : historyQuery.isError ? (
            <ErrorState
              title="История недоступна"
              message={adminErrorMessage(historyQuery.error, 'Не удалось получить аудит консоли.')}
              onRetry={() => void historyQuery.refetch()}
            />
          ) : (historyQuery.data ?? []).length === 0 ? (
            <p className="admin-overview-empty">Вызовов ещё не было.</p>
          ) : (
            <div className="console-history">
              {(historyQuery.data ?? []).map((entry) => {
                const details = entry.details ?? {};
                const label = String(details.command ?? details.action ?? entry.action);
                const exit = details.exit_code;
                return (
                  <div className="console-history__row" key={entry.id}>
                    <code>{label}</code>
                    <span>
                      {exit === undefined || exit === null ? 'job' : `exit ${String(exit)}`}
                      {details.rejected ? ` · rejected: ${String(details.rejected)}` : ''}
                    </span>
                    <span>{formatDateTime(entry.created_at)}</span>
                    <code className="console-history__hash">
                      {typeof details.output_hash === 'string'
                        ? details.output_hash.slice(0, 12)
                        : '—'}
                    </code>
                  </div>
                );
              })}
            </div>
          )}
        </section>
      ) : null}
    </div>
  );
}
