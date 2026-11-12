import { useEffect, useState, type FormEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  adminApi,
  adminErrorMessage,
  type AdminYandexIntegration,
  type AdminYandexIntegrationUpdate,
  type AdminYandexTest,
} from '../../api/admin';
import { DancingSpinner } from '../DancingLoader';
import { ErrorState } from '../ErrorState';
import { Icon } from '../Icon';
import { Modal } from '../Modal';
import { Skeleton } from '../Skeleton';
import { formatDateTime } from '../../lib/format';
import { toast } from '../../stores/toast';

const CALLBACK_PATH = '/api/v1/auth/yandex/callback';

function SecretLine({
  label,
  secret,
}: {
  label: string;
  secret: AdminYandexIntegration['client_id'];
}) {
  return (
    <span className={`yandex-integration__secret${secret.configured ? '' : ' is-empty'}`}>
      {label}: {secret.configured ? secret.hint || '••••' : 'не задан'}
    </span>
  );
}

/**
 * Self-contained "Интеграции → Яндекс ID" admin section.
 *
 * The component deliberately does not know about AdminPage tabs: another task
 * will group integrations into tabs later, and this panel can be moved as-is.
 */
export function YandexIntegrationPanel() {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ['admin', 'integrations', 'yandex'],
    queryFn: ({ signal }) => adminApi.getYandexIntegration(signal),
  });

  const [enabled, setEnabled] = useState(true);
  const [clientId, setClientId] = useState('');
  const [clientSecret, setClientSecret] = useState('');
  const [redirectUri, setRedirectUri] = useState('');
  const [formError, setFormError] = useState('');
  const [testResult, setTestResult] = useState<AdminYandexTest | null>(null);
  const [deleteOpen, setDeleteOpen] = useState(false);

  useEffect(() => {
    if (!query.data) return;
    setEnabled(query.data.enabled);
    setRedirectUri(query.data.redirect_uri ?? '');
  }, [query.data]);

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['admin', 'integrations', 'yandex'] });
    void queryClient.invalidateQueries({ queryKey: ['admin', 'audit'] });
    void queryClient.invalidateQueries({ queryKey: ['auth', 'providers'] });
  };

  const saveMutation = useMutation({
    mutationFn: (payload: AdminYandexIntegrationUpdate) =>
      adminApi.updateYandexIntegration(payload),
    onSuccess: () => {
      setClientId('');
      setClientSecret('');
      setFormError('');
      setTestResult(null);
      invalidate();
      toast.success('Настройки Яндекс ID сохранены');
    },
    onError: (error) => {
      const message = adminErrorMessage(error, 'Не удалось сохранить настройки Яндекс ID.');
      setFormError(message);
      toast.error(message);
    },
  });

  const testMutation = useMutation({
    mutationFn: () => adminApi.testYandexIntegration(),
    onSuccess: (result) => {
      setTestResult(result);
      if (result.ok) toast.success('Конфигурация заполнена корректно');
      else toast.error('Проверьте отмеченные поля конфигурации');
    },
    onError: (error) =>
      toast.error(adminErrorMessage(error, 'Не удалось проверить конфигурацию.')),
  });

  const deleteMutation = useMutation({
    mutationFn: () => adminApi.deleteYandexIntegration(),
    onSuccess: () => {
      setDeleteOpen(false);
      setClientId('');
      setClientSecret('');
      setRedirectUri('');
      setTestResult(null);
      invalidate();
      toast.success('Интеграция Яндекс ID удалена');
    },
    onError: (error) =>
      toast.error(adminErrorMessage(error, 'Не удалось удалить интеграцию.')),
  });

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setFormError('');
    const payload: AdminYandexIntegrationUpdate = {
      enabled,
      redirect_uri: redirectUri.trim(),
    };
    if (clientId.trim()) payload.client_id = clientId.trim();
    if (clientSecret.trim()) payload.client_secret = clientSecret.trim();
    saveMutation.mutate(payload);
  };

  return (
    <section className="admin-panel" aria-labelledby="admin-yandex-title">
      <div className="admin-panel__head">
        <div>
          <h2 id="admin-yandex-title">Интеграции → Яндекс ID</h2>
          <p>
            OAuth 2.0 для входа и регистрации. Client secret хранится только в базе
            control-сервиса в зашифрованном виде и никогда не возвращается в браузер.
          </p>
        </div>
      </div>

      {query.isLoading ? (
        <Skeleton height="220px" />
      ) : query.isError ? (
        <ErrorState
          title="Яндекс ID недоступен"
          message={adminErrorMessage(query.error, 'Не удалось загрузить настройки интеграции.')}
          onRetry={() => void query.refetch()}
        />
      ) : (
        <form className="admin-form" onSubmit={onSubmit}>
          <div className="yandex-integration__status">
            <span className={`badge ${query.data?.configured ? 'badge--success' : 'badge--danger'}`}>
              {query.data?.configured ? 'Настроено' : 'Не настроено'}
            </span>
            <span className={`badge ${query.data?.enabled ? 'badge--accent' : ''}`}>
              {query.data?.enabled ? 'Включено' : 'Выключено'}
            </span>
            <SecretLine label="Client ID" secret={query.data!.client_id} />
            <SecretLine label="Client secret" secret={query.data!.client_secret} />
            {query.data?.updated_at ? (
              <span className="yandex-integration__updated">
                Обновлено {formatDateTime(query.data.updated_at)}
              </span>
            ) : null}
          </div>

          {formError ? (
            <div className="form-alert" role="alert">
              <Icon name="alert" size={17} />
              <span>{formError}</span>
            </div>
          ) : null}

          <section className="admin-form__section">
            <div className="admin-form__checks">
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={enabled}
                  onChange={(event) => setEnabled(event.target.checked)}
                />
                <span>Включить вход через Яндекс ID</span>
              </label>
            </div>

            <div className="admin-form__grid">
              <div className="field">
                <label className="field__label" htmlFor="yandex-client-id">
                  Client ID
                </label>
                <input
                  id="yandex-client-id"
                  className="input"
                  value={clientId}
                  onChange={(event) => setClientId(event.target.value)}
                  placeholder={query.data?.client_id.configured ? query.data.client_id.hint : 'Из Яндекс.Консоли'}
                  autoComplete="off"
                  spellCheck={false}
                  maxLength={128}
                />
              </div>

              <div className="field">
                <label className="field__label" htmlFor="yandex-client-secret">
                  Client secret
                </label>
                <input
                  id="yandex-client-secret"
                  className="input"
                  type="password"
                  value={clientSecret}
                  onChange={(event) => setClientSecret(event.target.value)}
                  placeholder={
                    query.data?.client_secret.configured
                      ? query.data.client_secret.hint
                      : 'Новое значение'
                  }
                  autoComplete="new-password"
                  spellCheck={false}
                  maxLength={256}
                />
              </div>

              <div className="field field--wide">
                <label className="field__label" htmlFor="yandex-redirect-uri">
                  Redirect URI
                </label>
                <input
                  id="yandex-redirect-uri"
                  className="input"
                  value={redirectUri}
                  onChange={(event) => setRedirectUri(event.target.value)}
                  placeholder={`https://85.192.37.58.nip.io:8443${CALLBACK_PATH}`}
                  spellCheck={false}
                  maxLength={512}
                />
                <span className="field__hint">
                  В Яндекс.Консоли у приложения должен быть указан ровно этот адрес, без
                  завершающего слэша: production —
                  <code> https://85.192.37.58.nip.io:8443{CALLBACK_PATH}</code>.
                </span>
              </div>
            </div>

            <div className="yandex-integration__actions">
              <button
                type="submit"
                className="btn btn--primary btn--sm"
                disabled={saveMutation.isPending}
              >
                {saveMutation.isPending ? (
                  <DancingSpinner size={14} />
                ) : (
                  <Icon name="check" size={14} />
                )}
                Сохранить
              </button>
              <button
                type="button"
                className="btn btn--outline btn--sm"
                onClick={() => testMutation.mutate()}
                disabled={testMutation.isPending}
              >
                {testMutation.isPending ? (
                  <DancingSpinner size={14} />
                ) : (
                  <Icon name="shield" size={14} />
                )}
                Проверить конфигурацию
              </button>
              <button
                type="button"
                className="btn btn--danger-ghost btn--sm"
                onClick={() => setDeleteOpen(true)}
                disabled={!query.data?.configured && !query.data?.enabled}
              >
                <Icon name="trash" size={14} />
                Удалить
              </button>
            </div>

            {testResult ? (
              <div className="yandex-integration__checks" role="status">
                <strong>{testResult.message}</strong>
                {testResult.checks.map((check) => (
                  <span
                    key={check.name}
                    className={`yandex-integration__check ${
                      check.ok ? 'yandex-integration__check--ok' : 'yandex-integration__check--fail'
                    }`}
                  >
                    <Icon name={check.ok ? 'check' : 'alert'} size={14} />
                    {check.message}
                  </span>
                ))}
              </div>
            ) : null}
          </section>
        </form>
      )}

      <Modal
        open={deleteOpen}
        onClose={() => setDeleteOpen(false)}
        title="Удалить интеграцию Яндекс ID?"
        description="Ключи будут удалены из базы. Вход через Яндекс перестанет работать до повторной настройки."
        size="sm"
        footer={
          <>
            <button
              type="button"
              className="btn btn--ghost"
              onClick={() => setDeleteOpen(false)}
              disabled={deleteMutation.isPending}
            >
              Отмена
            </button>
            <button
              type="button"
              className="btn btn--danger"
              onClick={() => deleteMutation.mutate()}
              disabled={deleteMutation.isPending}
            >
              {deleteMutation.isPending ? <DancingSpinner size={14} /> : <Icon name="trash" size={14} />}
              Удалить
            </button>
          </>
        }
      >
        <p>
          Текущие client ID, client secret и redirect URI будут удалены. Публичная кнопка
          «Войти через Яндекс» скроется сразу после обновления статуса провайдера.
        </p>
      </Modal>
    </section>
  );
}
