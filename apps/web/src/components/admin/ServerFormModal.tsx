import { useEffect, useId, useState, type FormEvent } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import {
  ADMIN_SERVICES,
  adminApi,
  adminErrorMessage,
  type AdminServer,
  type AdminServerCreate,
  type AdminServerUpdate,
  type AdminServiceCode,
} from '../../api/admin';
import { Icon } from '../Icon';
import { DancingSpinner } from '../DancingLoader';
import { Modal } from '../Modal';
import { toast } from '../../stores/toast';

type ServiceRow = { selected: boolean; port: string };
type ServiceRows = Record<AdminServiceCode, ServiceRow>;

function defaultServiceRows(): ServiceRows {
  return Object.fromEntries(
    ADMIN_SERVICES.map((service) => [service.code, { selected: false, port: String(service.defaultPort) }]),
  ) as ServiceRows;
}

function rowsForServer(server: AdminServer | null): ServiceRows {
  const rows = defaultServiceRows();
  if (!server) return rows;
  for (const service of server.services) {
    if (service.code in rows) {
      rows[service.code as AdminServiceCode] = {
        selected: true,
        port: String(service.port),
      };
    }
  }
  return rows;
}

interface ServerFormModalProps {
  open: boolean;
  server: AdminServer | null;
  servers: AdminServer[];
  onClose: () => void;
}

export function ServerFormModal({ open, server, servers, onClose }: ServerFormModalProps) {
  const queryClient = useQueryClient();
  const formId = useId();
  const [name, setName] = useState('');
  const [host, setHost] = useState('');
  const [publicHost, setPublicHost] = useState('');
  const [sshPort, setSshPort] = useState('22');
  const [username, setUsername] = useState('root');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [jumpServerId, setJumpServerId] = useState('');
  const [bindHost, setBindHost] = useState('0.0.0.0');
  const [isFallback, setIsFallback] = useState(false);
  const [isJump, setIsJump] = useState(false);
  const [notes, setNotes] = useState('');
  const [serviceRows, setServiceRows] = useState<ServiceRows>(defaultServiceRows);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!open) return;
    setName(server?.name ?? '');
    setHost(server?.host ?? '');
    setPublicHost(server?.public_host ?? '');
    setSshPort(String(server?.ssh_port ?? 22));
    setUsername(server?.username ?? 'root');
    setPassword('');
    setShowPassword(false);
    setJumpServerId(server?.jump_server_id ?? '');
    setBindHost(server?.bind_host ?? '0.0.0.0');
    setIsFallback(server?.is_fallback ?? false);
    setIsJump(server?.is_jump ?? false);
    setNotes(server?.notes ?? '');
    setServiceRows(rowsForServer(server));
    setError('');
    // Список серверов не должен сбрасывать уже заполненную форму при обновлении инвентаря.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, server?.id]);

  const mutation = useMutation({
    mutationFn: (variables: { serverId: string | null; payload: AdminServerCreate | AdminServerUpdate }) =>
      variables.serverId
        ? adminApi.updateServer(variables.serverId, variables.payload as AdminServerUpdate)
        : adminApi.createServer(variables.payload as AdminServerCreate),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['admin', 'servers'] });
      void queryClient.invalidateQueries({ queryKey: ['admin', 'registry'] });
      void queryClient.invalidateQueries({ queryKey: ['admin', 'audit'] });
      toast.success(
        server
          ? 'Сервер обновлён'
          : Object.values(serviceRows).some((row) => row.selected)
            ? 'Сервер добавлен. Теперь нажмите «Развернуть» на его карточке.'
            : 'Сервер добавлен',
      );
      onClose();
    },
    onError: (mutationError: unknown) => {
      setError(adminErrorMessage(mutationError, 'Не удалось сохранить сервер.'));
    },
  });

  const jumpCandidates = servers.filter(
    (item) => item.is_jump && item.id !== server?.id,
  );
  const currentJump = server?.jump_server_id
    ? servers.find((item) => item.id === server.jump_server_id)
    : null;
  const jumpOptions =
    currentJump && !jumpCandidates.some((item) => item.id === currentJump.id)
      ? [...jumpCandidates, currentJump]
      : jumpCandidates;
  const selectedCount = ADMIN_SERVICES.filter((service) => serviceRows[service.code].selected).length;

  const setService = (code: AdminServiceCode, patch: Partial<ServiceRow>) => {
    setServiceRows((current) => ({
      ...current,
      [code]: { ...current[code], ...patch },
    }));
  };

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError('');

    const trimmedName = name.trim();
    const trimmedHost = host.trim();
    const trimmedUser = username.trim();
    const trimmedBind = bindHost.trim();
    const port = Number(sshPort);

    if (!trimmedName) return setError('Укажите имя сервера.');
    if (!trimmedHost) return setError('Укажите хост или IP-адрес.');
    if (!Number.isInteger(port) || port < 1 || port > 65535) return setError('SSH-порт должен быть от 1 до 65535.');
    if (!trimmedUser) return setError('Укажите SSH-пользователя.');
    if (!trimmedBind) return setError('Укажите bind host.');
    if (!server && !password) return setError('Для нового сервера нужен SSH-пароль.');

    const services = ADMIN_SERVICES.filter((service) => serviceRows[service.code].selected).map((service) => {
      const rawPort = serviceRows[service.code].port;
      const servicePort = Number(rawPort);
      return { code: service.code, port: servicePort };
    });

    if (
      services.some(
        (service) =>
          !Number.isInteger(service.port) || service.port < 1024 || service.port > 65535,
      )
    ) {
      return setError('Порты сервисов должны быть целыми числами от 1024 до 65535.');
    }

    const payload: AdminServerUpdate = {
      name: trimmedName,
      host: trimmedHost,
      public_host: publicHost.trim() || null,
      ssh_port: port,
      username: trimmedUser,
      jump_server_id: jumpServerId || null,
      bind_host: trimmedBind,
      is_fallback: isFallback,
      is_jump: isJump,
      notes: notes.trim() || null,
      services,
    };
    if (password) payload.password = password;

    if (server) {
      mutation.mutate({ serverId: server.id, payload });
    } else {
      mutation.mutate({
        serverId: null,
        payload: { ...payload, password } as AdminServerCreate,
      });
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={server ? 'Изменить сервер' : 'Добавить сервер'}
      description={
        server
          ? `${server.name} · ${server.host}:${server.ssh_port}`
          : 'Inventory, SSH-доступ и набор сервисов на узле.'
      }
      size="lg"
      variant="sheet"
      footer={
        <>
          <button type="button" className="btn btn--ghost" onClick={onClose} disabled={mutation.isPending}>
            Отмена
          </button>
          <button type="submit" form={formId} className="btn btn--primary" disabled={mutation.isPending}>
            {mutation.isPending ? (
              <>
                <DancingSpinner size={16} />
                Сохраняем…
              </>
            ) : (
              <>
                <Icon name={server ? 'check' : 'plus'} size={16} />
                {server ? 'Сохранить' : 'Добавить сервер'}
              </>
            )}
          </button>
        </>
      }
    >
      <form id={formId} className="admin-form" onSubmit={onSubmit}>
        {error ? (
          <div className="form-alert" role="alert">
            <Icon name="alert" size={17} />
            <span>{error}</span>
          </div>
        ) : null}

        <section className="admin-form__section">
          <h3>Узел</h3>
          <div className="admin-form__grid">
            <div className="field">
              <label className="field__label" htmlFor="admin-server-name">
                Имя
              </label>
              <input
                id="admin-server-name"
                className="input"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="edge-01"
                required
              />
            </div>
            <div className="field">
              <label className="field__label" htmlFor="admin-server-host">
                Хост / IP
              </label>
              <input
                id="admin-server-host"
                className="input"
                value={host}
                onChange={(event) => setHost(event.target.value)}
                placeholder="203.0.113.10"
                required
              />
            </div>
            <div className="field">
              <label className="field__label" htmlFor="admin-server-public">
                Public host <span className="field__hint">необязательно</span>
              </label>
              <input
                id="admin-server-public"
                className="input"
                value={publicHost}
                onChange={(event) => setPublicHost(event.target.value)}
                placeholder="manga.example.com"
              />
            </div>
            <div className="field">
              <label className="field__label" htmlFor="admin-server-ssh-port">
                SSH-порт
              </label>
              <input
                id="admin-server-ssh-port"
                className="input"
                type="number"
                min={1}
                max={65535}
                value={sshPort}
                onChange={(event) => setSshPort(event.target.value)}
              />
            </div>
            <div className="field">
              <label className="field__label" htmlFor="admin-server-user">
                SSH-пользователь
              </label>
              <input
                id="admin-server-user"
                className="input"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                autoComplete="off"
                required
              />
            </div>
            <div className="field">
              <label className="field__label" htmlFor="admin-server-password">
                SSH-пароль
              </label>
              <div className="password-field">
                <input
                  id="admin-server-password"
                  className="input"
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder={server ? 'Оставьте пустым, чтобы не менять' : 'Пароль для SSH'}
                  autoComplete="new-password"
                  required={!server}
                />
                <button
                  type="button"
                  className="password-field__toggle"
                  onClick={() => setShowPassword((value) => !value)}
                  aria-label={showPassword ? 'Скрыть пароль' : 'Показать пароль'}
                  aria-pressed={showPassword}
                >
                  <Icon name={showPassword ? 'eye-off' : 'eye'} size={17} />
                </button>
              </div>
            </div>
          </div>
        </section>

        <section className="admin-form__section">
          <h3>Сеть и роль</h3>
          <div className="admin-form__grid">
            <div className="field">
              <label className="field__label" htmlFor="admin-server-bind">
                Bind host сервисов
              </label>
              <input
                id="admin-server-bind"
                className="input"
                value={bindHost}
                onChange={(event) => setBindHost(event.target.value)}
              />
              <span className="field__hint">
                <strong>0.0.0.0</strong> — сервисы доступны другим серверам (нужно для отдельного
                узла). <strong>127.0.0.1</strong> — только через nginx на этом же сервере.
              </span>
            </div>
            <div className="field">
              <label className="field__label" htmlFor="admin-server-jump">
                Jump-сервер
              </label>
              <select
                id="admin-server-jump"
                className="select"
                value={jumpServerId}
                onChange={(event) => setJumpServerId(event.target.value)}
              >
                <option value="">Без jump-сервера</option>
                {jumpOptions.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name} · {item.host}
                  </option>
                ))}
              </select>
              {jumpOptions.length === 0 ? (
                <span className="field__hint">Нет узлов, помеченных как jump. Сначала добавьте jump-сервер.</span>
              ) : null}
            </div>
          </div>
          <div className="admin-form__checks">
            <label className="switch">
              <input
                className="switch__input"
                type="checkbox"
                checked={isFallback}
                onChange={(event) => setIsFallback(event.target.checked)}
              />
              <span className="switch__track">
                <span className="switch__thumb" />
              </span>
              <span className="switch__label">Резервный узел (fallback)</span>
            </label>
            <label className="switch">
              <input
                className="switch__input"
                type="checkbox"
                checked={isJump}
                onChange={(event) => setIsJump(event.target.checked)}
              />
              <span className="switch__track">
                <span className="switch__thumb" />
              </span>
              <span className="switch__label">Jump-сервер для других узлов</span>
            </label>
          </div>
          <div className="field">
            <label className="field__label" htmlFor="admin-server-notes">
              Заметки
            </label>
            <textarea
              id="admin-server-notes"
              className="textarea"
              value={notes}
              maxLength={2000}
              onChange={(event) => setNotes(event.target.value)}
              placeholder="Провайдер, регион, особенности доступа…"
            />
          </div>
        </section>

        <section className="admin-form__section">
          <div className="admin-form__section-head">
            <h3>Сервисы на сервере</h3>
            <span className="field__hint">Выбрано: {selectedCount}</span>
          </div>
          <div className="admin-service-form">
            {ADMIN_SERVICES.map((service) => {
              const row = serviceRows[service.code];
              return (
                <div className={`admin-service-row${row.selected ? ' is-selected' : ''}`} key={service.code}>
                  <label className="admin-service-row__check">
                    <input
                      type="checkbox"
                      checked={row.selected}
                      onChange={(event) => setService(service.code, { selected: event.target.checked })}
                    />
                    <span className="admin-service-row__name">{service.label}</span>
                    <span className="admin-service-row__code">{service.code}</span>
                  </label>
                  <label className="admin-service-row__port">
                    <span className="sr-only">Порт {service.label}</span>
                    <input
                      className="input"
                      type="number"
                      min={1024}
                      max={65535}
                      value={row.port}
                      onChange={(event) => setService(service.code, { port: event.target.value })}
                      aria-label={`Порт ${service.label}`}
                    />
                  </label>
                  {!service.http ? <span className="admin-service-row__hint">без health-check</span> : null}
                </div>
              );
            })}
          </div>
          <p className="field__hint">
            Scheduler принимает порт для единообразия inventory, но health-check для него не выполняется.
            После сохранения нажмите «Развернуть» на карточке сервера — установка идёт отдельной задачей.
          </p>
        </section>
      </form>
    </Modal>
  );
}
