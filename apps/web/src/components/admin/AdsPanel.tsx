import { useEffect, useId, useState, type FormEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  adminApi,
  adminErrorMessage,
  type AdminAdProvider,
  type AdminAdProviderInput,
  type AdAudience,
  type AdPlacement,
  type AdProviderType,
} from '../../api/admin';
import { EmptyState } from '../EmptyState';
import { ErrorState } from '../ErrorState';
import { Icon } from '../Icon';
import { DancingSpinner } from '../DancingLoader';
import { Modal } from '../Modal';
import { Skeleton } from '../Skeleton';
import { formatDateTime, formatInt } from '../../lib/format';
import { toast } from '../../stores/toast';

const YANDEX_BLOCK_ID_RE = /^R-A-\d+-\d+$/;

function configBlockId(config: Record<string, unknown> | undefined): string {
  const value = config?.block_id;
  return typeof value === 'string' ? value : '';
}

const TYPE_LABELS: Record<AdProviderType, string> = {
  yandex: 'Яндекс РСЯ',
  adfox: 'AdFox',
  google: 'Google AdSense',
  custom_html: 'Custom HTML',
  custom_script: 'Custom script',
};

const PLACEMENT_LABELS: Record<AdPlacement, string> = {
  header: 'Header',
  sidebar: 'Sidebar',
  'in-feed': 'In-feed',
  'post-chapter': 'После главы',
  'mobile-sticky': 'Mobile sticky',
};

const AUDIENCE_LABELS: Record<AdAudience, string> = {
  guest: 'Гости',
  authenticated: 'Авторизованные',
  both: 'Все',
};

const DAY_LABELS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];
const PLACEMENT_SIZES: Record<AdPlacement, { format: string; width: string; height: string }> = {
  header: { format: '970x90', width: '970', height: '90' },
  sidebar: { format: '300x250', width: '300', height: '250' },
  'in-feed': { format: '728x90', width: '728', height: '90' },
  'post-chapter': { format: '728x90', width: '728', height: '90' },
  'mobile-sticky': { format: '320x50', width: '320', height: '50' },
};

interface AdDraft {
  name: string;
  type: AdProviderType;
  enabled: boolean;
  priority: string;
  placement: AdPlacement;
  audience: AdAudience;
  frequency_cap: string;
  format: string;
  width: string;
  height: string;
  schedule_days: number[];
  schedule_start: string;
  schedule_end: string;
  timezone: string;
  blockId: string;
  configText: string;
  custom_html: string;
  custom_script: string;
  exclude_adult: boolean;
  hide_for_donors: boolean;
  require_consent: boolean;
}

function defaultDraft(): AdDraft {
  return {
    name: '',
    type: 'custom_html',
    enabled: true,
    priority: '100',
    placement: 'header',
    audience: 'both',
    frequency_cap: '0',
    format: '970x90',
    width: '970',
    height: '90',
    schedule_days: [],
    schedule_start: '00:00',
    schedule_end: '23:59',
    timezone: 'Europe/Moscow',
    blockId: '',
    configText: '{}',
    custom_html: '',
    custom_script: '',
    exclude_adult: true,
    hide_for_donors: false,
    require_consent: false,
  };
}

function draftFrom(provider: AdminAdProvider): AdDraft {
  return {
    name: provider.name,
    type: provider.type,
    enabled: provider.enabled,
    priority: String(provider.priority),
    placement: provider.placement,
    audience: provider.audience,
    frequency_cap: String(provider.frequency_cap),
    format: provider.format,
    width: provider.width ? String(provider.width) : '',
    height: provider.height ? String(provider.height) : '',
    schedule_days: [...provider.schedule_days],
    schedule_start: provider.schedule_start,
    schedule_end: provider.schedule_end,
    timezone: provider.timezone,
    blockId: configBlockId(provider.config),
    configText: JSON.stringify(provider.config ?? {}, null, 2),
    custom_html: provider.custom_html,
    custom_script: provider.custom_script,
    exclude_adult: provider.exclude_adult,
    hide_for_donors: provider.hide_for_donors,
    require_consent: provider.require_consent,
  };
}

function scheduleLabel(provider: AdminAdProvider): string {
  const days =
    provider.schedule_days.length === 0
      ? 'каждый день'
      : provider.schedule_days.map((day) => DAY_LABELS[day] ?? '?').join(', ');
  if (provider.schedule_start === '00:00' && provider.schedule_end === '23:59') {
    return `${days}, круглосуточно`;
  }
  return `${days}, ${provider.schedule_start}–${provider.schedule_end} (${provider.timezone})`;
}

function AdFormModal({
  open,
  provider,
  onClose,
}: {
  open: boolean;
  provider: AdminAdProvider | null;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const formId = useId();
  const [draft, setDraft] = useState<AdDraft>(defaultDraft);
  const [error, setError] = useState('');
  const [secretName, setSecretName] = useState('api_key');
  const [secretValue, setSecretValue] = useState('');

  useEffect(() => {
    if (!open) return;
    setDraft(provider ? draftFrom(provider) : defaultDraft());
    setError('');
    setSecretName('api_key');
    setSecretValue('');
  }, [open, provider?.id]);

  const saveMutation = useMutation({
    mutationFn: (payload: AdminAdProviderInput) =>
      provider ? adminApi.updateAd(provider.id, payload) : adminApi.createAd(payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['admin', 'ads'] });
      void queryClient.invalidateQueries({ queryKey: ['admin', 'audit'] });
      toast.success(provider ? 'Рекламная интеграция обновлена' : 'Рекламная интеграция добавлена');
      onClose();
    },
    onError: (mutationError) =>
      setError(adminErrorMessage(mutationError, 'Не удалось сохранить рекламную интеграцию.')),
  });

  const secretMutation = useMutation({
    mutationFn: (input: { name: string; value: string }) =>
      adminApi.setAdSecret(provider!.id, input.name, input.value),
    onSuccess: (secret) => {
      setSecretValue('');
      void queryClient.invalidateQueries({ queryKey: ['admin', 'ads'] });
      void queryClient.invalidateQueries({ queryKey: ['admin', 'audit'] });
      toast.success(`Ключ «${secret.name}» сохранён (${secret.hint})`);
    },
    onError: (mutationError) =>
      toast.error(adminErrorMessage(mutationError, 'Не удалось сохранить ключ.')),
  });

  const deleteSecretMutation = useMutation({
    mutationFn: (name: string) => adminApi.deleteAdSecret(provider!.id, name),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['admin', 'ads'] });
      void queryClient.invalidateQueries({ queryKey: ['admin', 'audit'] });
      toast.success('Ключ удалён');
    },
    onError: (mutationError) =>
      toast.error(adminErrorMessage(mutationError, 'Не удалось удалить ключ.')),
  });

  const patch = (values: Partial<AdDraft>) =>
    setDraft((current) => ({ ...current, ...values }));

  const changePlacement = (placement: AdPlacement) => {
    const size = PLACEMENT_SIZES[placement];
    patch({
      placement,
      format: size.format,
      width: size.width,
      height: size.height,
    });
  };

  const toggleDay = (day: number) => {
    setDraft((current) => ({
      ...current,
      schedule_days: current.schedule_days.includes(day)
        ? current.schedule_days.filter((item) => item !== day)
        : [...current.schedule_days, day].sort(),
    }));
  };

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError('');

    const priority = Number(draft.priority);
    const frequencyCap = Number(draft.frequency_cap);
    const width = draft.width ? Number(draft.width) : null;
    const height = draft.height ? Number(draft.height) : null;

    if (!draft.name.trim()) return setError('Укажите название.');
    if (!Number.isInteger(priority) || priority < 0 || priority > 10000) {
      return setError('Приоритет должен быть целым числом от 0 до 10000.');
    }
    if (!Number.isInteger(frequencyCap) || frequencyCap < 0 || frequencyCap > 1000) {
      return setError('Частотный лимит должен быть целым числом от 0 до 1000.');
    }
    if (width !== null && (!Number.isInteger(width) || width < 0 || width > 4096)) {
      return setError('Ширина должна быть целым числом от 0 до 4096.');
    }
    if (height !== null && (!Number.isInteger(height) || height < 0 || height > 4096)) {
      return setError('Высота должна быть целым числом от 0 до 4096.');
    }
    if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(draft.schedule_start)) {
      return setError('Начало показа должно быть в формате ЧЧ:ММ.');
    }
    if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(draft.schedule_end)) {
      return setError('Конец показа должен быть в формате ЧЧ:ММ.');
    }

    let config: Record<string, unknown>;
    try {
      const parsed: unknown = draft.configText.trim() ? JSON.parse(draft.configText) : {};
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        return setError('Публичный config должен быть JSON-объектом.');
      }
      config = parsed as Record<string, unknown>;
    } catch {
      return setError('Публичный config содержит некорректный JSON.');
    }

    if (draft.type === 'yandex') {
      const blockId = draft.blockId.trim() || configBlockId(config);
      if (!blockId) {
        return setError('Укажите Block ID блока Яндекс РСЯ, например R-A-20411736-1.');
      }
      if (!YANDEX_BLOCK_ID_RE.test(blockId)) {
        return setError('Block ID должен иметь формат R-A-<число>-<число>.');
      }
      config.block_id = blockId;
    }

    saveMutation.mutate({
      name: draft.name.trim(),
      type: draft.type,
      enabled: draft.enabled,
      priority,
      placement: draft.placement,
      audience: draft.audience,
      frequency_cap: frequencyCap,
      format: draft.format.trim(),
      width,
      height,
      schedule_days: draft.schedule_days,
      schedule_start: draft.schedule_start,
      schedule_end: draft.schedule_end,
      timezone: draft.timezone.trim() || 'Europe/Moscow',
      config,
      custom_html: draft.type === 'custom_html' ? draft.custom_html : '',
      custom_script: draft.type === 'custom_script' ? draft.custom_script : '',
      exclude_adult: draft.exclude_adult,
      hide_for_donors: draft.hide_for_donors,
      require_consent: draft.require_consent,
    });
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={provider ? 'Изменить рекламную интеграцию' : 'Добавить рекламную интеграцию'}
      description={
        provider
          ? `${provider.name} · ${TYPE_LABELS[provider.type]} · ${PLACEMENT_LABELS[provider.placement]}`
          : 'Провайдер, слот, аудитория и расписание показа.'
      }
      size="lg"
      variant="sheet"
      footer={
        <>
          <button type="button" className="btn btn--ghost" onClick={onClose} disabled={saveMutation.isPending}>
            Отмена
          </button>
          <button type="submit" form={formId} className="btn btn--primary" disabled={saveMutation.isPending}>
            {saveMutation.isPending ? (
              <>
                <DancingSpinner size={16} />
                Сохраняем…
              </>
            ) : (
              <>
                <Icon name={provider ? 'check' : 'plus'} size={16} />
                {provider ? 'Сохранить' : 'Добавить'}
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
          <div className="admin-form__grid">
            <div className="field">
              <label className="field__label" htmlFor="ad-name">
                Название
              </label>
              <input
                id="ad-name"
                className="input"
                value={draft.name}
                onChange={(event) => patch({ name: event.target.value })}
                placeholder="Например, Header — Яндекс РСЯ"
                maxLength={128}
                required
              />
            </div>
            <div className="field">
              <label className="field__label" htmlFor="ad-type">
                Провайдер
              </label>
              <select
                id="ad-type"
                className="select"
                value={draft.type}
                onChange={(event) => patch({ type: event.target.value as AdProviderType })}
              >
                {Object.entries(TYPE_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
              <span className="field__hint">
                Ключи не вставляйте в поля контента: они уходят в HTML.
              </span>
            </div>
            <div className="field">
              <label className="field__label" htmlFor="ad-placement">
                Слот
              </label>
              <select
                id="ad-placement"
                className="select"
                value={draft.placement}
                onChange={(event) => changePlacement(event.target.value as AdPlacement)}
              >
                {Object.entries(PLACEMENT_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label className="field__label" htmlFor="ad-audience">
                Аудитория
              </label>
              <select
                id="ad-audience"
                className="select"
                value={draft.audience}
                onChange={(event) => patch({ audience: event.target.value as AdAudience })}
              >
                {Object.entries(AUDIENCE_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label className="field__label" htmlFor="ad-priority">
                Приоритет
              </label>
              <input
                id="ad-priority"
                className="input"
                type="number"
                min={0}
                max={10000}
                value={draft.priority}
                onChange={(event) => patch({ priority: event.target.value })}
              />
              <span className="field__hint">Меньшее число показывается первым.</span>
            </div>
            <div className="field">
              <label className="field__label" htmlFor="ad-frequency">
                Частотный лимит
              </label>
              <input
                id="ad-frequency"
                className="input"
                type="number"
                min={0}
                max={1000}
                value={draft.frequency_cap}
                onChange={(event) => patch({ frequency_cap: event.target.value })}
              />
              <span className="field__hint">Показов на браузер за 24 часа; 0 — без лимита.</span>
            </div>
          </div>
          <div className="admin-form__checks">
            <label className="switch">
              <input
                className="switch__input"
                type="checkbox"
                checked={draft.enabled}
                onChange={(event) => patch({ enabled: event.target.checked })}
              />
              <span className="switch__track">
                <span className="switch__thumb" />
              </span>
              <span className="switch__label">Провайдер включён</span>
            </label>
          </div>
        </section>

        <section className="admin-form__section">
          <div className="admin-form__section-head">
            <h3>Формат и расписание</h3>
            <span className="field__hint">Размер резервируется до загрузки баннера.</span>
          </div>
          <div className="admin-form__grid">
            <div className="field">
              <label className="field__label" htmlFor="ad-format">
                Формат
              </label>
              <input
                id="ad-format"
                className="input"
                value={draft.format}
                onChange={(event) => patch({ format: event.target.value })}
                placeholder="728x90"
                maxLength={32}
              />
            </div>
            <div className="field">
              <label className="field__label" htmlFor="ad-width">
                Ширина, px
              </label>
              <input
                id="ad-width"
                className="input"
                type="number"
                min={0}
                max={4096}
                value={draft.width}
                onChange={(event) => patch({ width: event.target.value })}
              />
            </div>
            <div className="field">
              <label className="field__label" htmlFor="ad-height">
                Высота, px
              </label>
              <input
                id="ad-height"
                className="input"
                type="number"
                min={0}
                max={4096}
                value={draft.height}
                onChange={(event) => patch({ height: event.target.value })}
              />
            </div>
            <div className="field">
              <label className="field__label" htmlFor="ad-timezone">
                Часовой пояс
              </label>
              <input
                id="ad-timezone"
                className="input"
                value={draft.timezone}
                onChange={(event) => patch({ timezone: event.target.value })}
                placeholder="Europe/Moscow"
              />
            </div>
            <div className="field">
              <label className="field__label" htmlFor="ad-start">
                Начало
              </label>
              <input
                id="ad-start"
                className="input"
                type="time"
                value={draft.schedule_start}
                onChange={(event) => patch({ schedule_start: event.target.value })}
              />
            </div>
            <div className="field">
              <label className="field__label" htmlFor="ad-end">
                Конец
              </label>
              <input
                id="ad-end"
                className="input"
                type="time"
                value={draft.schedule_end}
                onChange={(event) => patch({ schedule_end: event.target.value })}
              />
            </div>
          </div>
          <div className="ad-days" role="group" aria-label="Дни показа">
            <span className="field__label">Дни показа</span>
            <div className="ad-days__list">
              {DAY_LABELS.map((label, day) => (
                <button
                  key={label}
                  type="button"
                  className={`ad-day${draft.schedule_days.includes(day) ? ' is-active' : ''}`}
                  aria-pressed={draft.schedule_days.includes(day)}
                  onClick={() => toggleDay(day)}
                >
                  {label}
                </button>
              ))}
            </div>
            <span className="field__hint">Ничего не выбрано — каждый день.</span>
          </div>
        </section>

        <section className="admin-form__section">
          <div className="admin-form__section-head">
            <h3>Контент</h3>
            <span className="field__hint">Публичные параметры видны всем клиентам.</span>
          </div>
          {draft.type === 'yandex' ? (
            <div className="field">
              <label className="field__label" htmlFor="ad-block-id">
                Block ID
              </label>
              <input
                id="ad-block-id"
                className="input"
                value={draft.blockId}
                onChange={(event) => patch({ blockId: event.target.value })}
                placeholder="R-A-20411736-1"
                maxLength={64}
                spellCheck={false}
              />
              <span className="field__hint">
                Публичный идентификатор блока Яндекс РСЯ. Сохраняется в config.block_id,
                секретов здесь нет.
              </span>
            </div>
          ) : null}
          <div className="field">
            <label className="field__label" htmlFor="ad-config">
              Публичный config (JSON)
            </label>
            <textarea
              id="ad-config"
              className="textarea"
              rows={4}
              value={draft.configText}
              onChange={(event) => patch({ configText: event.target.value })}
              spellCheck={false}
            />
            <span className="field__hint">
              Например, {"{"}"block_id": "R-A-000000-1"{"}"}. Не добавляйте сюда секретные ключи.
            </span>
          </div>
          {draft.type === 'custom_html' ? (
            <div className="field">
              <label className="field__label" htmlFor="ad-html">
                HTML баннера
              </label>
              <textarea
                id="ad-html"
                className="textarea"
                rows={6}
                value={draft.custom_html}
                onChange={(event) => patch({ custom_html: event.target.value })}
                placeholder='<div class="banner">...</div>'
                spellCheck={false}
              />
              <span className="field__hint">
                Сервер удаляет script, iframe, обработчики on* и опасные URL. Баннер рендерится
                только при наличии разметки.
              </span>
            </div>
          ) : null}
          {draft.type === 'custom_script' ? (
            <div className="field">
              <label className="field__label" htmlFor="ad-script">
                Скрипт баннера
              </label>
              <textarea
                id="ad-script"
                className="textarea"
                rows={6}
                value={draft.custom_script}
                onChange={(event) => patch({ custom_script: event.target.value })}
                spellCheck={false}
              />
              <span className="field__hint">
                Выполняется в sandbox-iframe без доступа к сайту. Не вставляйте секретные ключи:
                исходник скрипта отдаётся браузеру.
              </span>
            </div>
          ) : null}
        </section>

        <section className="admin-form__section">
          <div className="admin-form__section-head">
            <h3>Политики показа</h3>
          </div>
          <div className="admin-form__checks ad-checks">
            <label className="switch">
              <input
                className="switch__input"
                type="checkbox"
                checked={draft.exclude_adult}
                onChange={(event) => patch({ exclude_adult: event.target.checked })}
              />
              <span className="switch__track">
                <span className="switch__thumb" />
              </span>
              <span className="switch__label">Скрывать на 18+ тайтлах</span>
            </label>
            <label className="switch">
              <input
                className="switch__input"
                type="checkbox"
                checked={draft.hide_for_donors}
                onChange={(event) => patch({ hide_for_donors: event.target.checked })}
              />
              <span className="switch__track">
                <span className="switch__thumb" />
              </span>
              <span className="switch__label">Скрывать для Pro/донатеров</span>
            </label>
            <label className="switch">
              <input
                className="switch__input"
                type="checkbox"
                checked={draft.require_consent}
                onChange={(event) => patch({ require_consent: event.target.checked })}
              />
              <span className="switch__track">
                <span className="switch__thumb" />
              </span>
              <span className="switch__label">Показывать только после согласия (CMP)</span>
            </label>
          </div>
        </section>

        {provider ? (
          <section className="admin-form__section">
            <div className="admin-form__section-head">
              <h3>Секретные ключи</h3>
              <span className="field__hint">Шифруются at rest и никогда не возвращаются в GET.</span>
            </div>
            {provider.secrets.length === 0 ? (
              <p className="ad-secrets-empty">Ключи не добавлены.</p>
            ) : (
              <div className="ad-secrets">
                {provider.secrets.map((secret) => (
                  <div className="ad-secret-row" key={secret.name}>
                    <div>
                      <strong>{secret.name}</strong>
                      <code>{secret.hint}</code>
                      {secret.updated_at ? <span>{formatDateTime(secret.updated_at)}</span> : null}
                    </div>
                    <button
                      type="button"
                      className="btn btn--ghost btn--sm"
                      disabled={deleteSecretMutation.isPending}
                      onClick={() => {
                        if (!window.confirm(`Удалить ключ «${secret.name}»?`)) return;
                        deleteSecretMutation.mutate(secret.name);
                      }}
                    >
                      <Icon name="trash" size={14} />
                      Удалить
                    </button>
                  </div>
                ))}
              </div>
            )}
            <div className="ad-secret-form">
              <input
                className="input"
                value={secretName}
                onChange={(event) => setSecretName(event.target.value)}
                placeholder="api_key"
                aria-label="Имя ключа"
                maxLength={64}
                spellCheck={false}
              />
              <input
                className="input"
                type="password"
                value={secretValue}
                onChange={(event) => setSecretValue(event.target.value)}
                placeholder="Новое значение ключа"
                aria-label="Значение ключа"
                autoComplete="new-password"
                spellCheck={false}
              />
              <button
                type="button"
                className="btn btn--primary btn--sm"
                disabled={!secretValue.trim() || !secretName.trim() || secretMutation.isPending}
                onClick={() => secretMutation.mutate({ name: secretName.trim(), value: secretValue })}
              >
                {secretMutation.isPending ? <DancingSpinner size={14} /> : <Icon name="lock" size={14} />}
                Сохранить ключ
              </button>
            </div>
            <p className="field__hint">
              Повторное сохранение с тем же именем заменяет ключ. После смены CONTROL_SECRET_KEY
              старые ключи нужно ввести заново.
            </p>
          </section>
        ) : null}
      </form>
    </Modal>
  );
}

export function AdsPanel() {
  const queryClient = useQueryClient();
  const [formOpen, setFormOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<AdminAdProvider | null>(null);

  const adsQuery = useQuery({
    queryKey: ['admin', 'ads'],
    queryFn: ({ signal }) => adminApi.listAds(signal),
  });

  const providers = adsQuery.data ?? [];
  const editing = editingId ? providers.find((item) => item.id === editingId) ?? null : null;

  const toggleMutation = useMutation({
    mutationFn: (provider: AdminAdProvider) =>
      adminApi.updateAd(provider.id, { enabled: !provider.enabled }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['admin', 'ads'] });
      void queryClient.invalidateQueries({ queryKey: ['admin', 'audit'] });
      toast.success('Статус провайдера обновлён');
    },
    onError: (error) => toast.error(adminErrorMessage(error, 'Не удалось переключить провайдера.')),
  });

  const deleteMutation = useMutation({
    mutationFn: (provider: AdminAdProvider) => adminApi.deleteAd(provider.id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['admin', 'ads'] });
      void queryClient.invalidateQueries({ queryKey: ['admin', 'audit'] });
      toast.success('Рекламная интеграция удалена');
      setDeleteTarget(null);
    },
    onError: (error) => toast.error(adminErrorMessage(error, 'Не удалось удалить интеграцию.')),
  });

  return (
    <section className="admin-panel" aria-labelledby="admin-ads-title">
      <div className="admin-panel__head">
        <div>
          <h2 id="admin-ads-title">Реклама</h2>
          <p>
            Провайдеры, слоты, аудитории и зашифрованные ключи. Изменения применяются без
            перезапуска сервисов.
          </p>
        </div>
        <button
          type="button"
          className="btn btn--primary btn--sm"
          onClick={() => {
            setEditingId(null);
            setFormOpen(true);
          }}
        >
          <Icon name="plus" size={15} />
          Добавить интеграцию
        </button>
      </div>

      {adsQuery.isLoading ? (
        <div className="admin-server-grid" aria-hidden="true">
          {Array.from({ length: 2 }, (_, index) => (
            <Skeleton key={index} height="240px" style={{ borderRadius: 14 }} />
          ))}
        </div>
      ) : adsQuery.isError ? (
        <ErrorState
          title="Реклама недоступна"
          message={adminErrorMessage(adsQuery.error, 'Не удалось загрузить рекламные интеграции.')}
          onRetry={() => void adsQuery.refetch()}
        />
      ) : providers.length === 0 ? (
        <EmptyState
          compact
          icon="sparkles"
          title="Рекламных интеграций пока нет"
          description="Добавьте провайдера и слот. Пока ничего не настроено, реклама не показывается."
          action={
            <button
              type="button"
              className="btn btn--primary btn--sm"
              onClick={() => {
                setEditingId(null);
                setFormOpen(true);
              }}
            >
              <Icon name="plus" size={15} />
              Добавить интеграцию
            </button>
          }
        />
      ) : (
        <div className="admin-server-grid">
          {providers.map((provider) => (
            <article
              className={`admin-server-card${provider.enabled ? '' : ' is-disabled'}`}
              key={provider.id}
            >
              <div className="admin-server-card__head">
                <div>
                  <h3>{provider.name}</h3>
                  <div className="admin-server-card__host">
                    <Icon name="sparkles" size={13} />
                    <code>{TYPE_LABELS[provider.type]}</code>
                  </div>
                </div>
                <div className="admin-badges">
                  <span className={`badge ${provider.enabled ? 'badge--success' : 'badge--danger'}`}>
                    {provider.enabled ? 'Активен' : 'Выключен'}
                  </span>
                  <span className="badge">{PLACEMENT_LABELS[provider.placement]}</span>
                  <span className="badge">{AUDIENCE_LABELS[provider.audience]}</span>
                </div>
              </div>

              <div className="admin-server-card__meta">
                <div>
                  <span>Приоритет</span>
                  <strong>{formatInt(provider.priority)}</strong>
                </div>
                <div>
                  <span>Формат</span>
                  <strong>{provider.format || `${provider.width ?? '—'}×${provider.height ?? '—'}`}</strong>
                </div>
                {provider.type === 'yandex' ? (
                  <div>
                    <span>Block ID</span>
                    <strong>
                      <code>{configBlockId(provider.config) || 'не задан'}</code>
                    </strong>
                  </div>
                ) : null}
                <div>
                  <span>Частотный лимит</span>
                  <strong>{provider.frequency_cap || 'без лимита'}</strong>
                </div>
                <div>
                  <span>Ключи</span>
                  <strong>
                    {provider.secrets.length > 0
                      ? provider.secrets.map((secret) => `${secret.name} ${secret.hint}`).join(', ')
                      : 'не заданы'}
                  </strong>
                </div>
              </div>

              <p className="admin-server-card__notes">
                {scheduleLabel(provider)}
                {provider.exclude_adult ? ' · 18+ скрыта' : ''}
                {provider.hide_for_donors ? ' · Pro/донатеры скрыты' : ''}
                {provider.require_consent ? ' · нужно согласие' : ''}
              </p>

              <div className="admin-server-card__actions">
                <button
                  type="button"
                  className="btn btn--outline btn--sm"
                  disabled={toggleMutation.isPending}
                  onClick={() => toggleMutation.mutate(provider)}
                >
                  <Icon name="power" size={14} />
                  {provider.enabled ? 'Выключить' : 'Включить'}
                </button>
                <button
                  type="button"
                  className="btn btn--ghost btn--sm"
                  onClick={() => {
                    setEditingId(provider.id);
                    setFormOpen(true);
                  }}
                >
                  <Icon name="edit" size={14} />
                  Изменить
                </button>
                <button
                  type="button"
                  className="btn btn--ghost btn--sm admin-server-card__delete"
                  onClick={() => setDeleteTarget(provider)}
                >
                  <Icon name="trash" size={14} />
                  Удалить
                </button>
              </div>
            </article>
          ))}
        </div>
      )}

      <AdFormModal
        open={formOpen}
        provider={editing}
        onClose={() => {
          setFormOpen(false);
          setEditingId(null);
        }}
      />

      <Modal
        open={Boolean(deleteTarget)}
        onClose={() => setDeleteTarget(null)}
        title="Удалить рекламную интеграцию?"
        description={
          deleteTarget
            ? `«${deleteTarget.name}» и все его ключи будут удалены. Это действие нельзя отменить.`
            : undefined
        }
        size="sm"
        footer={
          <>
            <button type="button" className="btn btn--ghost" onClick={() => setDeleteTarget(null)}>
              Отмена
            </button>
            <button
              type="button"
              className="btn btn--danger"
              disabled={deleteMutation.isPending}
              onClick={() => deleteTarget && deleteMutation.mutate(deleteTarget)}
            >
              {deleteMutation.isPending ? <DancingSpinner size={16} /> : <Icon name="trash" size={16} />}
              Удалить
            </button>
          </>
        }
      >
        <p>Публичный конфиг сразу перестанет отдавать этот слот. Аудит сохранит действие.</p>
      </Modal>
    </section>
  );
}
