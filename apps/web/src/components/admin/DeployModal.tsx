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
