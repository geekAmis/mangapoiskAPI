import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { api } from '../../api/client';
import type { ProfileUpdate } from '../../api/types';
import { InlineError } from '../ErrorState';
import { Icon } from '../Icon';
import { AchievementCard, EventRow } from './ProfileBits';
import { formatInt } from '../../lib/format';
import { privacySummary, xpProgressPercent } from '../../lib/profileUi';
import { useAuthStore } from '../../stores/auth';
import { toast } from '../../stores/toast';

interface ProfileForm {
  display_name: string;
  username: string;
  bio: string;
}

interface PrivacyForm {
  is_private: boolean;
  show_stats: boolean;
  show_events: boolean;
  show_achievements: boolean;
  indexable: boolean;
}

const EMPTY_FORM: ProfileForm = { display_name: '', username: '', bio: '' };
const EMPTY_PRIVACY: PrivacyForm = {
  is_private: false,
  show_stats: true,
  show_events: true,
  show_achievements: true,
  indexable: true,
};

function ToggleRow({
  label,
  description,
  checked,
  onChange,
  danger = false,
}: {
  label: string;
  description: string;
  checked: boolean;
  onChange: (value: boolean) => void;
  danger?: boolean;
}) {
  return (
    <div className="setting-row">
      <div className="setting-row__main">
        <span className="setting-row__label">{label}</span>
        <span className="setting-row__desc">{description}</span>
      </div>
      <div className="setting-row__control">
        <label className={`switch${danger ? ' is-danger' : ''}`}>
          <input
            className="switch__input"
            type="checkbox"
            checked={checked}
            aria-label={label}
            onChange={(event) => onChange(event.target.checked)}
          />
          <span className="switch__track">
            <span className="switch__thumb" />
          </span>
        </label>
      </div>
    </div>
  );
}

export function ProfileOverview() {
  const queryClient = useQueryClient();
  const setUser = useAuthStore((state) => state.setUser);
  const authUser = useAuthStore((state) => state.user);
  const [form, setForm] = useState<ProfileForm>(EMPTY_FORM);
  const [privacy, setPrivacy] = useState<PrivacyForm>(EMPTY_PRIVACY);
  const timezone = useMemo(() => {
    try {
      return Intl.DateTimeFormat().resolvedOptions().timeZone;
    } catch {
      return undefined;
    }
  }, []);

  const profileQuery = useQuery({
    queryKey: ['profile', 'me'],
    queryFn: ({ signal }) => api.getMyProfile(timezone, signal),
    staleTime: 30_000,
  });
  const profile = profileQuery.data;

  useEffect(() => {
    if (!profile) return;
    setForm({
      display_name: profile.display_name,
      username: profile.username,
      bio: profile.bio,
    });
    setPrivacy({
      is_private: profile.privacy.is_private,
      show_stats: profile.privacy.show_stats,
      show_events: profile.privacy.show_events,
      show_achievements: profile.privacy.show_achievements,
      indexable: profile.privacy.indexable,
    });
  }, [profile]);

  const mutation = useMutation({
    mutationFn: (payload: ProfileUpdate) => api.updateMyProfile(payload),
    onSuccess: (data) => {
      queryClient.setQueryData(['profile', 'me'], data);
      void queryClient.invalidateQueries({ queryKey: ['profile'] });
      void queryClient.invalidateQueries({ queryKey: ['auth', 'me'] });
      if (authUser && authUser.display_name !== data.display_name) {
        setUser({ ...authUser, display_name: data.display_name });
      }
      toast.success('Профиль сохранён');
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : 'Не удалось сохранить профиль'),
  });

  const save = () => {
    mutation.mutate({
      ...form,
      ...privacy,
    });
  };

  const updatePrivacy = (key: keyof PrivacyForm, value: boolean) => {
    setPrivacy((current) => ({ ...current, [key]: value }));
  };

  if (profileQuery.isLoading) {
    return (
      <section className="panel" aria-labelledby="profile-public-title">
        <div className="panel__head">
          <div>
            <h2 className="panel__title" id="profile-public-title">
              <Icon name="user" size={19} />
              Публичный профиль
            </h2>
            <p className="panel__sub">Загружаем данные профиля…</p>
          </div>
        </div>
      </section>
    );
  }

  if (profileQuery.isError || !profile) {
    return (
      <section className="panel" aria-labelledby="profile-public-title">
        <div className="panel__head">
          <div>
            <h2 className="panel__title" id="profile-public-title">
              <Icon name="user" size={19} />
              Публичный профиль
            </h2>
          </div>
        </div>
        <InlineError
          message={
            profileQuery.error instanceof Error
              ? profileQuery.error.message
              : 'Не удалось загрузить профиль.'
          }
          onRetry={() => void profileQuery.refetch()}
        />
      </section>
    );
  }

  const progressPercent = xpProgressPercent(profile);

  return (
    <>
      <section className="panel" id="public-profile" aria-labelledby="profile-public-title">
        <div className="panel__head">
          <div>
            <h2 className="panel__title" id="profile-public-title">
              <Icon name="user" size={19} />
              Публичный профиль
            </h2>
            <p className="panel__sub">
              Карточка по адресу{' '}
              <Link className="profile-inline-link" to={`/u/${profile.username}`}>
                /u/{profile.username}
              </Link>
              . Аватар — инициалы, загрузка файлов пока не поддерживается.
            </p>
          </div>
          <div className="panel__actions">
            <Link className="btn btn--outline btn--sm" to={`/u/${profile.username}`}>
              <Icon name="external" size={15} />
              Открыть
            </Link>
          </div>
        </div>

        <div className="profile-level-strip">
          <div className="profile-level-strip__level">
            <span className="profile-level-strip__eyebrow">Уровень</span>
            <strong>{profile.level}</strong>
          </div>
          <div className="profile-level-strip__body">
            <div className="profile-level-strip__rank">
              <span className="badge badge--accent">{profile.rank.label}</span>
              {profile.next_rank ? (
                <span className="profile-level-strip__next">
                  до «{profile.next_rank.label}» — {profile.next_rank.min_level} ур.
                </span>
              ) : (
                <span className="profile-level-strip__next">максимальное звание</span>
              )}
            </div>
            <div
              className="progress"
              role="progressbar"
              aria-label="Прогресс уровня"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={progressPercent}
            >
              <span style={{ width: `${progressPercent}%` }} />
            </div>
            <div className="profile-level-strip__xp">
              {profile.xp_for_next_level > 0
                ? `${formatInt(profile.xp_into_level)} / ${formatInt(profile.xp_for_next_level)} XP`
                : 'Максимальный уровень'}
              <span> · всего {formatInt(profile.xp)} XP</span>
            </div>
          </div>
        </div>

        <div className="profile-form">
          <label className="field">
            <span className="field__label">Отображаемое имя</span>
            <input
              className="input"
              value={form.display_name}
              maxLength={48}
              onChange={(event) => setForm((current) => ({ ...current, display_name: event.target.value }))}
            />
            <span className="field__hint">Видно в комментариях и на публичной карточке.</span>
          </label>
          <label className="field">
            <span className="field__label">Ник в ссылке</span>
            <input
              className="input"
              value={form.username}
              maxLength={24}
              spellCheck={false}
              onChange={(event) => setForm((current) => ({ ...current, username: event.target.value }))}
            />
            <span className="field__hint">3–24 символа: латиница, цифры и «_». Меняет адрес /u/…</span>
          </label>
          <label className="field">
            <span className="field__label">Био</span>
            <textarea
              className="textarea"
              value={form.bio}
              maxLength={280}
              onChange={(event) => setForm((current) => ({ ...current, bio: event.target.value }))}
            />
            <span className="field__hint">{form.bio.length} / 280</span>
          </label>
          <div className="profile-form__actions">
            <button
              type="button"
              className="btn btn--primary"
              disabled={mutation.isPending}
              onClick={save}
            >
              {mutation.isPending ? 'Сохранение…' : 'Сохранить профиль'}
            </button>
            {mutation.isError ? (
              <span className="field__error">
                {mutation.error instanceof Error ? mutation.error.message : 'Ошибка сохранения'}
              </span>
            ) : null}
          </div>
        </div>
      </section>

      <section className="panel" id="privacy" aria-labelledby="profile-privacy-title">
        <div className="panel__head">
          <div>
            <h2 className="panel__title" id="profile-privacy-title">
              <Icon name="shield" size={19} />
              Приватность
            </h2>
            <p className="panel__sub">
              По умолчанию профиль открыт и индексируется. Скрытие любого раздела делает карточку
              недоступной гостям и убирает её из поиска.
            </p>
          </div>
        </div>
        <div className="profile-privacy-list">
          <ToggleRow
            label="Скрыть профиль"
            description="Профиль не открывается у гостей; владелец видит его в настройках."
            checked={privacy.is_private}
            onChange={(value) => updatePrivacy('is_private', value)}
            danger
          />
          <ToggleRow
            label="Показывать статистику"
            description="Агрегаты чтения: главы, тайтлы, дни и серии."
            checked={privacy.show_stats}
            onChange={(value) => updatePrivacy('show_stats', value)}
          />
          <ToggleRow
            label="Показывать события"
            description="Последние прочитанные главы и завершённые тайтлы. Даты — без точного времени."
            checked={privacy.show_events}
            onChange={(value) => updatePrivacy('show_events', value)}
          />
          <ToggleRow
            label="Показывать достижения"
            description="Полученные достижения и прогресс по ним."
            checked={privacy.show_achievements}
            onChange={(value) => updatePrivacy('show_achievements', value)}
          />
          <ToggleRow
            label="Индексировать в поиске"
            description="Разрешить поисковым системам индексировать публичную карточку."
            checked={privacy.indexable}
            onChange={(value) => updatePrivacy('indexable', value)}
          />
        </div>
        <div className="sync-note" style={{ marginTop: 14 }}>
          <Icon name="info" size={15} />
          <span>{privacySummary({ ...privacy })}. Изменения вступят в силу после сохранения.</span>
        </div>
        <div className="profile-form__actions" style={{ marginTop: 14 }}>
          <button
            type="button"
            className="btn btn--outline"
            disabled={mutation.isPending}
            onClick={save}
          >
            {mutation.isPending ? 'Сохранение…' : 'Сохранить настройки'}
          </button>
        </div>
      </section>

      <section className="panel" id="achievements" aria-labelledby="profile-achievements-title">
        <div className="panel__head">
          <div>
            <h2 className="panel__title" id="profile-achievements-title">
              <Icon name="sparkles" size={19} />
              Достижения
            </h2>
            <p className="panel__sub">
              Получено {profile.achievements_unlocked} из {profile.achievements_total}. Награды
              выдаются автоматически и только один раз.
            </p>
          </div>
        </div>
        <div className="achievement-grid">
          {profile.achievements.map((item) => (
            <AchievementCard key={item.code} item={item} owner />
          ))}
        </div>
      </section>

      <section className="panel" id="events" aria-labelledby="profile-events-title">
        <div className="panel__head">
          <div>
            <h2 className="panel__title" id="profile-events-title">
              <Icon name="clock" size={19} />
              Последние события
            </h2>
            <p className="panel__sub">
              Видны вам и — если включено — гостям. Точное время не публикуется.
            </p>
          </div>
        </div>
        {profile.events.length > 0 ? (
          <ol className="profile-events">
            {profile.events.map((item) => (
              <EventRow key={item.id} item={item} />
            ))}
          </ol>
        ) : (
          <p className="public-profile__muted">
            Событий пока нет. Они появятся после чтения глав.
          </p>
        )}
      </section>
    </>
  );
}
