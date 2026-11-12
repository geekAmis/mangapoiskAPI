import { useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ADMIN_SERVICES,
  adminApi,
  adminErrorMessage,
  type AdminJob,
  type AdminServer,
  type AdminServiceCode,
  type AdminServiceSpec,
  type AdminSupervisorReport,
} from '../../api/admin';
import { Icon } from '../Icon';
import { DancingSpinner } from '../DancingLoader';
import { Modal } from '../Modal';
import { formatDateTime } from '../../lib/format';
import { toast } from '../../stores/toast';

type DeployStep = 'configure' | 'confirm' | 'job';

const STATUS_LABELS: Record<string, string> = {
  queued: 'В очереди',
  running: 'Развёртывание',
  done: 'Готово',
  failed: 'Ошибка',
};

const SUPERVISOR_LABELS: Record<string, string> = {
  healthy: 'Проверено, всё работает',
  recovered: 'Восстановлено',
  failed: 'Не удалось исправить',
  skipped: 'Пропущено',
  timeout: 'Таймаут',
  error: 'Ошибка супервизора',
  dry_run: 'Dry-run',
};

const SUPERVISOR_TONE: Record<string, 'ok' | 'bad' | 'wait'> = {
  healthy: 'ok',
  recovered: 'ok',
  failed: 'bad',
  timeout: 'bad',
  error: 'bad',
  skipped: 'wait',
  dry_run: 'wait',
};

function readSupervisorReport(job: AdminJob | undefined): AdminSupervisorReport | null {
  const value = job?.requested?.supervisor;
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  return value as AdminSupervisorReport;
}

interface DeployModalProps {
  open: boolean;
  server: AdminServer | null;
  onClose: () => void;
}

export function DeployModal({ open, server, onClose }: DeployModalProps) {
  const queryClient = useQueryClient();
  const logRef = useRef<HTMLPreElement>(null);
  const notifiedRef = useRef<string | null>(null);
  const [step, setStep] = useState<DeployStep>('configure');
  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const [update, setUpdate] = useState(true);
  const [jobId, setJobId] = useState<string | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!open) return;
    const next: Record<string, boolean> = {};
    for (const service of server?.services ?? []) next[service.code] = true;
    setSelected(next);
    setUpdate(true);
    setJobId(null);
    setStep('configure');
    setError('');
    notifiedRef.current = null;
  }, [open, server?.id]);

  const deployMutation = useMutation({
    mutationFn: (services: AdminServiceSpec[]) => {
      if (!server) return Promise.reject(new Error('Сервер не выбран'));
      return adminApi.deployServer(server.id, { services, update });
    },
    onSuccess: (result) => {
      setJobId(result.job_id);
      setStep('job');
      setError('');
    },
    onError: (mutationError: unknown) => {
      setError(adminErrorMessage(mutationError, 'Не удалось запустить развёртывание.'));
    },
  });

  const jobQuery = useQuery({
    queryKey: ['admin', 'job', jobId ?? 'none'],
    queryFn: ({ signal }) => adminApi.getJob(jobId ?? '', signal),
    enabled: Boolean(jobId),
    retry: 1,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === 'queued' || status === 'running' ? 2000 : false;
    },
  });

  const job: AdminJob | undefined = jobQuery.data;
  const supervisorReport = readSupervisorReport(job);
  const supervisorTone = supervisorReport
    ? (SUPERVISOR_TONE[supervisorReport.status] ?? 'wait')
    : 'wait';

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [job?.log]);

  useEffect(() => {
    if (!job || !jobId) return;
    if (job.status !== 'done' && job.status !== 'failed') return;
    if (notifiedRef.current === job.id) return;
    notifiedRef.current = job.id;
    void queryClient.invalidateQueries({ queryKey: ['admin', 'servers'] });
    void queryClient.invalidateQueries({ queryKey: ['admin', 'registry'] });
    void queryClient.invalidateQueries({ queryKey: ['admin', 'audit'] });
    if (job.status === 'done') toast.success(`Развёртывание «${server?.name ?? 'сервер'}» завершено`);
    else toast.error(`Развёртывание «${server?.name ?? 'сервер'}» завершилось ошибкой`);
  }, [job, jobId, queryClient, server?.name]);

  const selectedServices = ADMIN_SERVICES.filter((service) => selected[service.code]).map((service) => {
    const port =
      server?.services.find((item) => item.code === service.code)?.port ?? service.defaultPort;
    return { code: service.code, port };
  });

  const toggle = (code: AdminServiceCode) => {
    setSelected((current) => ({ ...current, [code]: !current[code] }));
  };

  const modalTitle = step === 'job' ? 'Развёртывание' : 'Развернуть сервисы';
  const jobStatus = job?.status ?? 'queued';

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={modalTitle}
      description={server ? `${server.name} · ${server.host}` : undefined}
      size="lg"
      variant="sheet"
      footer={
        step === 'job' ? (
          <>
            {job?.status === 'failed' ? (
              <button
                type="button"
                className="btn btn--outline"
                onClick={() => {
                  setJobId(null);
                  setStep('configure');
                  notifiedRef.current = null;
                }}
              >
                <Icon name="refresh" size={16} />
                Повторить
              </button>
            ) : null}
            <button type="button" className="btn btn--primary" onClick={onClose}>
              Закрыть
            </button>
          </>
        ) : step === 'confirm' ? (
          <>
            <button type="button" className="btn btn--ghost" onClick={() => setStep('configure')}>
              Назад
            </button>
            <button
              type="button"
              className="btn btn--primary"
              onClick={() => deployMutation.mutate(selectedServices)}
              disabled={deployMutation.isPending}
            >
              {deployMutation.isPending ? (
                <>
                  <DancingSpinner size={16} />
                  Запускаем…
                </>
              ) : (
                <>
                  <Icon name="play" size={16} />
                  Подтвердить и запустить
                </>
              )}
            </button>
          </>
        ) : (
          <>
            <button type="button" className="btn btn--ghost" onClick={onClose}>
              Отмена
            </button>
            <button
              type="button"
              className="btn btn--primary"
              onClick={() => setStep('confirm')}
              disabled={selectedServices.length === 0}
            >
              <Icon name="download" size={16} />
              Развернуть
            </button>
          </>
        )
      }
    >
      {step === 'job' ? (
        <div className="admin-deploy">
          <div className="admin-deploy__status">
            <span className={`admin-status admin-status--${jobStatus}`}>
              <span className={`admin-health-dot ${jobStatus === 'failed' ? 'is-bad' : jobStatus === 'done' ? 'is-ok' : 'is-wait'}`} />
              {STATUS_LABELS[jobStatus] ?? jobStatus}
            </span>
            {job ? (
              <span className="field__hint">
                {job.updated_at ? `обновлено ${formatDateTime(job.updated_at)}` : 'ожидание ответа control-сервиса'}
              </span>
            ) : null}
          </div>

          {job?.error ? (
            <div className="form-alert" role="alert">
              <Icon name="alert" size={17} />
              <span>{job.error}</span>
            </div>
          ) : null}
          {jobQuery.isError ? (
            <div className="form-alert" role="alert">
              <Icon name="alert" size={17} />
              <span>{adminErrorMessage(jobQuery.error, 'Не удалось получить статус задачи.')}</span>
            </div>
          ) : null}

          {supervisorReport ? (
            <section
              className={`admin-supervisor admin-supervisor--${supervisorTone}`}
              aria-label="Отчёт AI-супервизора"
            >
              <div className="admin-supervisor__head">
                <span className={`admin-supervisor__badge admin-supervisor__badge--${supervisorTone}`}>
                  <span
                    className={`admin-health-dot ${
                      supervisorTone === 'ok' ? 'is-ok' : supervisorTone === 'bad' ? 'is-bad' : 'is-wait'
                    }`}
                  />
                  AI-супервизор · {SUPERVISOR_LABELS[supervisorReport.status] ?? supervisorReport.status}
                </span>
                {supervisorReport.model ? (
                  <span className="field__hint">{supervisorReport.model}</span>
                ) : null}
              </div>
              {supervisorReport.summary ? (
                <p className="admin-supervisor__summary">{supervisorReport.summary}</p>
              ) : null}
              <div className="admin-supervisor__meta">
                {typeof supervisorReport.rounds === 'number' ? (
                  <span>
                    раундов: {supervisorReport.rounds}/{supervisorReport.max_iterations ?? '—'}
                  </span>
                ) : null}
                {supervisorReport.timeout_seconds ? (
                  <span>лимит: {Math.round(supervisorReport.timeout_seconds / 60)} мин</span>
                ) : null}
                {supervisorReport.max_steps ? <span>шагов: {supervisorReport.max_steps}</span> : null}
                {supervisorReport.rollback?.attempted ? (
                  <span>
                    откат:{' '}
                    {supervisorReport.rollback.skipped
                      ? 'пропущен'
                      : supervisorReport.rollback.ok
                        ? 'выполнен'
                        : 'не выполнен'}
                  </span>
                ) : null}
                {supervisorReport.finished_at ? (
                  <span>завершено {formatDateTime(supervisorReport.finished_at)}</span>
                ) : null}
              </div>
              {Array.isArray(supervisorReport.actions) && supervisorReport.actions.length ? (
                <ul className="admin-supervisor__actions">
                  {supervisorReport.actions.map((action, index) => (
                    <li key={`${index}-${action}`}>{action}</li>
                  ))}
                </ul>
              ) : null}
              {Array.isArray(supervisorReport.guard_violations) &&
              supervisorReport.guard_violations.length ? (
                <div className="admin-supervisor__danger" role="alert">
                  <strong>Запрещённые команды:</strong>
                  <ul>
                    {supervisorReport.guard_violations.map((violation, index) => (
                      <li key={`${index}-${violation.command}`}>
                        <code>{violation.command}</code>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {Array.isArray(supervisorReport.changed_files) &&
              supervisorReport.changed_files.length ? (
                <details className="admin-supervisor__details">
                  <summary>Изменённые файлы ({supervisorReport.changed_files.length})</summary>
                  <ul>
                    {supervisorReport.changed_files.map((file) => (
                      <li key={file}>
                        <code>{file}</code>
                      </li>
                    ))}
                  </ul>
                </details>
              ) : null}
              {Array.isArray(supervisorReport.shell_commands) &&
              supervisorReport.shell_commands.length ? (
                <details className="admin-supervisor__details">
                  <summary>Команды агента ({supervisorReport.shell_commands.length})</summary>
                  <ul>
                    {supervisorReport.shell_commands.map((command, index) => (
                      <li key={`${index}-${command}`}>
                        <code>{command}</code>
                      </li>
                    ))}
                  </ul>
                </details>
              ) : null}
              {supervisorReport.raw_tail ? (
                <details className="admin-supervisor__details">
                  <summary>Хвост отчёта</summary>
                  <pre>{supervisorReport.raw_tail}</pre>
                </details>
              ) : null}
            </section>
          ) : null}

          <div className="admin-terminal" aria-label="Лог развёртывания" aria-live="polite">
            <pre ref={logRef}>{job?.log || 'Ожидание вывода задачи…'}</pre>
          </div>
          {job?.status === 'queued' || job?.status === 'running' ? (
            <p className="field__hint">Статус обновляется каждые 2 секунды.</p>
          ) : null}
        </div>
      ) : step === 'confirm' ? (
        <div className="admin-confirm">
          <span className="admin-confirm__icon" aria-hidden="true">
            <Icon name="alert" size={26} />
          </span>
          <h2>Развернуть сервисы на «{server?.name}»?</h2>
          <p>
            Будут перезапущены выбранные сервисы: {selectedServices.map((item) => item.code).join(', ') || '—'}.
            {update ? ' Репозиторий и образы будут обновлены.' : ''}
          </p>
          <ul>
            {selectedServices.map((service) => (
              <li key={service.code}>
                <span>{service.code}</span>
                <code>:{service.port}</code>
              </li>
            ))}
          </ul>
          {error ? (
            <div className="form-alert" role="alert">
              <Icon name="alert" size={17} />
              <span>{error}</span>
            </div>
          ) : null}
        </div>
      ) : (
        <div className="admin-deploy">
          {error ? (
            <div className="form-alert" role="alert">
              <Icon name="alert" size={17} />
              <span>{error}</span>
            </div>
          ) : null}
          <p className="field__hint">
            Выберите сервисы, которые нужно развернуть на узле. Порты берутся из inventory этого сервера.
          </p>
          <div className="admin-deploy__services">
            {ADMIN_SERVICES.map((service) => {
              const configured = server?.services.some((item) => item.code === service.code);
              return (
                <label
                  key={service.code}
                  className={`admin-deploy__service${selected[service.code] ? ' is-selected' : ''}${configured ? '' : ' is-missing'}`}
                >
                  <input
                    type="checkbox"
                    checked={Boolean(selected[service.code])}
                    onChange={() => toggle(service.code)}
                  />
                  <span className="admin-deploy__service-body">
                    <strong>{service.label}</strong>
                    <span>
                      {configured
                        ? `порт ${server?.services.find((item) => item.code === service.code)?.port}`
                        : `порт по умолчанию ${service.defaultPort} · не настроен`}
                    </span>
                  </span>
                  {configured ? (
                    <span
                      className={`admin-health-dot ${
                        server?.services.find((item) => item.code === service.code)?.healthy ? 'is-ok' : 'is-bad'
                      }`}
                    />
                  ) : null}
                </label>
              );
            })}
          </div>
          <label className="switch">
            <input
              className="switch__input"
              type="checkbox"
              checked={update}
              onChange={(event) => setUpdate(event.target.checked)}
            />
            <span className="switch__track">
              <span className="switch__thumb" />
            </span>
            <span className="switch__label">Обновить образы и репозиторий перед развёртыванием</span>
          </label>
        </div>
      )}
    </Modal>
  );
}
