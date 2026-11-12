import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { notificationsApi, type NotificationSettings } from '../api/notifications';
import { humanizeError } from '../lib/errors';
import {
  PushUnavailableError,
  getPushState,
  notificationPermission,
  pushSupport,
  subscribeToPush,
  unsubscribeFromPush,
} from '../lib/push';
import { toast } from '../stores/toast';
import { Icon } from './Icon';

type SettingsForm = Omit<NotificationSettings, 'updated_at'>;

const DEFAULT_FORM: SettingsForm = {
  in_app_enabled: true,
  web_push_enabled: true,
  max_pushes_per_hour: 5,
  quiet_hours_start: null,
  quiet_hours_end: null,
};

const HOURS = Array.from({ length: 24 }, (_, hour) => hour);
const RATE_OPTIONS = [1, 2, 3, 5, 10, 20];

function hourLabel(hour: number): string {
  return `${String(hour).padStart(2, '0')}:00`;
}

export function NotificationSettingsPanel() {
  const queryClient = useQueryClient();
  const support = useMemo(() => pushSupport(), []);
  const [form, setForm] = useState<SettingsForm>(DEFAULT_FORM);
  const [pushBusy, setPushBusy] = useState(false);
  const [permission, setPermission] = useState(notificationPermission());

  const settingsQuery = useQuery({
    queryKey: ['notification-settings'],
    queryFn: () => notificationsApi.settings(),
    staleTime: 30_000,
  });
  const pushConfigQuery = useQuery({
    queryKey: ['push-config'],
    queryFn: () => notificationsApi.pushConfig(),
    staleTime: 5 * 60_000,
  });
  const pushStatusQuery = useQuery({
    queryKey: ['push-status'],
    queryFn: () => notificationsApi.pushStatus(),
    enabled: support.supported,
    staleTime: 30_000,
  });

  useEffect(() => {
    if (!settingsQuery.data) return;
    setForm({
      in_app_enabled: settingsQuery.data.in_app_enabled,
      web_push_enabled: settingsQuery.data.web_push_enabled,
      max_pushes_per_hour: settingsQuery.data.max_pushes_per_hour,
      quiet_hours_start: settingsQuery.data.quiet_hours_start,
      quiet_hours_end: settingsQuery.data.quiet_hours_end,
    });
  }, [settingsQuery.data]);

  useEffect(() => {
    void getPushState()
      .then((state) => setPermission(state.permission))
      .catch(() => undefined);
  }, [pushStatusQuery.dataUpdatedAt]);

  const saveMutation = useMutation({
    mutationFn: (payload: SettingsForm) => notificationsApi.saveSettings(payload),
    onSuccess: (data) => {
      queryClient.setQueryData(['notification-settings'], data);
      void queryClient.invalidateQueries({ queryKey: ['notifications'] });
      toast.success('Настройки уведомлений сохранены');
    },
    onError: (error: unknown) =>
      toast.error(humanizeError(error, 'Не удалось сохранить настройки уведомлений')),
  });

  const persist = async (next: SettingsForm) => {
    setForm(next);
    await saveMutation.mutateAsync(next);
  };

  const enablePush = async () => {
    setPushBusy(true);
    try {
      await subscribeToPush();
      setPermission(notificationPermission());
      await persist({ ...form, web_push_enabled: true });
      await queryClient.invalidateQueries({ queryKey: ['push-status'] });
      toast.success('Web Push включён на этом устройстве');
    } catch (error: unknown) {
      const message =
        error instanceof PushUnavailableError
          ? error.message
          : humanizeError(error, 'Не удалось включить Web Push');
      toast.error(message);
      setPermission(notificationPermission());
    } finally {
      setPushBusy(false);
    }
  };

  const disablePush = async () => {
    setPushBusy(true);
    try {
      await unsubscribeFromPush();
      await persist({ ...form, web_push_enabled: false });
      await queryClient.invalidateQueries({ queryKey: ['push-status'] });
      toast.info('Web Push отключён, in-app уведомления остались');
    } catch (error: unknown) {
      toast.error(humanizeError(error, 'Не удалось отключить Web Push'));
    } finally {
      setPushBusy(false);
    }
  };

  const toggleQuietHours = (enabled: boolean) => {
    setForm((current) => ({
      ...current,
      quiet_hours_start: enabled ? (current.quiet_hours_start ?? 22) : null,
      quiet_hours_end: enabled ? (current.quiet_hours_end ?? 8) : null,
    }));
  };

  const quietEnabled = form.quiet_hours_start !== null && form.quiet_hours_end !== null;
  const pushActive = Boolean(pushStatusQuery.data?.subscribed);
  const serverPushReady = Boolean(pushConfigQuery.data?.enabled);
  const permissionDenied = permission === 'denied';
  const pushToggleDisabled =
    pushBusy || !support.supported || !serverPushReady || permissionDenied;

  return (
    <section className="panel" id="notifications" aria-labelledby="notifications-title">
      <div className="panel__head">
        <div>
          <h2 className="panel__title" id="notifications-title">
            <Icon name="bell" size={19} />
            Уведомления о новых главах
          </h2>
          <p className="panel__sub">
            Следите за тайтлом на его странице. Уведомления приходят в колокольчик, а при
            разрешении браузера — ещё и системным Web Push.
          </p>
        </div>
        <div className="panel__actions">
          <button
            type="button"
            className="btn btn--primary btn--sm"
            onClick={() => void persist(form)}
            disabled={saveMutation.isPending}
          >
            <Icon name="check" size={15} />
            Сохранить
          </button>
        </div>
      </div>

      {settingsQuery.isError ? (
        <div className="notification-settings__error" role="status">
          {humanizeError(settingsQuery.error, 'Не удалось загрузить настройки уведомлений')}
        </div>
      ) : null}

      <div className="setting-row">
        <div className="setting-row__main">
          <span className="setting-row__label">In-app уведомления</span>
          <span className="setting-row__desc">
            Показывать новые главы в колокольчике и на странице уведомлений.
          </span>
        </div>
        <div className="setting-row__control">
          <label className="switch">
            <input
              className="switch__input"
              type="checkbox"
              checked={form.in_app_enabled}
              onChange={(event) =>
                setForm((current) => ({ ...current, in_app_enabled: event.target.checked }))
              }
            />
            <span className="switch__track">
              <span className="switch__thumb" />
            </span>
          </label>
        </div>
      </div>

      <div className="setting-row">
        <div className="setting-row__main">
          <span className="setting-row__label">Web Push на этом устройстве</span>
          <span className="setting-row__desc">
            {!support.supported
              ? support.message
              : !serverPushReady
                ? 'Сервер не настроен: отсутствуют VAPID-ключи.'
                : permissionDenied
                  ? 'Разрешение запрещено в браузере. Откройте настройки сайта и разрешите уведомления.'
                  : pushActive
                    ? 'Подписка активна. Можно отключить её на этом устройстве.'
                    : 'Браузер спросит разрешение только после нажатия переключателя.'}
          </span>
        </div>
        <div className="setting-row__control">
          <label className={`switch${pushToggleDisabled && !pushActive ? ' switch--disabled' : ''}`}>
            <input
              className="switch__input"
              type="checkbox"
              checked={pushActive && form.web_push_enabled}
              disabled={pushToggleDisabled}
              onChange={(event) => {
                if (event.target.checked) void enablePush();
                else void disablePush();
              }}
            />
            <span className="switch__track">
              <span className="switch__thumb" />
            </span>
          </label>
        </div>
      </div>

      {support.reason === 'native' ? (
        <div className="sync-note notification-settings__note">
          <Icon name="shield" size={15} />
          <span>
            В Android-сборке Capacitor WebView не поддерживает Web Push API. Это ограничение
            платформы, а не ошибка приложения: новые главы приходят в in-app колокольчик, пока
            приложение открыто или при следующем запуске.
          </span>
        </div>
      ) : null}

      <div className="setting-row">
        <div className="setting-row__main">
          <span className="setting-row__label">Лимит Web Push</span>
          <span className="setting-row__desc">
            Не больше выбранного числа уведомлений в час. Несколько глав одного тайтла
            объединяются в один push.
          </span>
        </div>
        <div className="setting-row__control">
          <select
            className="select"
            style={{ minHeight: 38, width: 112 }}
            value={form.max_pushes_per_hour}
            onChange={(event) =>
              setForm((current) => ({
                ...current,
                max_pushes_per_hour: Number(event.target.value),
              }))
            }
            aria-label="Максимум Web Push в час"
          >
            {RATE_OPTIONS.map((value) => (
              <option key={value} value={value}>
                {value} / час
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="setting-row">
        <div className="setting-row__main">
          <span className="setting-row__label">Тихие часы</span>
          <span className="setting-row__desc">
            В это время Web Push не отправляется, in-app уведомление всё равно появится.
            Время указано в UTC.
          </span>
        </div>
        <div className="setting-row__control">
          <label className="switch">
            <input
              className="switch__input"
              type="checkbox"
              checked={quietEnabled}
              onChange={(event) => toggleQuietHours(event.target.checked)}
            />
            <span className="switch__track">
              <span className="switch__thumb" />
            </span>
          </label>
        </div>
      </div>

      {quietEnabled ? (
        <div className="notification-settings__quiet">
          <label>
            <span className="field__label">С</span>
            <select
              className="select"
              value={form.quiet_hours_start ?? 22}
              onChange={(event) =>
                setForm((current) => ({
                  ...current,
                  quiet_hours_start: Number(event.target.value),
                }))
              }
            >
              {HOURS.map((hour) => (
                <option key={hour} value={hour}>
                  {hourLabel(hour)}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span className="field__label">До</span>
            <select
              className="select"
              value={form.quiet_hours_end ?? 8}
              onChange={(event) =>
                setForm((current) => ({
                  ...current,
                  quiet_hours_end: Number(event.target.value),
                }))
              }
            >
              {HOURS.map((hour) => (
                <option key={hour} value={hour}>
                  {hourLabel(hour)}
                </option>
              ))}
            </select>
          </label>
        </div>
      ) : null}

      <div className="sync-note notification-settings__note">
        <Icon name="clock" size={15} />
        <span>
          Настройки сохраняются в аккаунте и действуют на всех устройствах. Отписаться от
          конкретного тайтла можно на его странице или прямо из уведомления в колокольчике.
        </span>
      </div>
    </section>
  );
}
