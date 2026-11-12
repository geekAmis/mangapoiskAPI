import { useMemo, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { ApiError, api } from '../api/client';
import type { PublicProfileOut } from '../api/types';
import { EmptyState } from '../components/EmptyState';
import { ErrorState, InlineError } from '../components/ErrorState';
import { Icon } from '../components/Icon';
import { Modal } from '../components/Modal';
import { AchievementCard, EventRow, StatCard } from '../components/profile/ProfileBits';
import { Skeleton } from '../components/Skeleton';
import { formatDate, formatInt, initials } from '../lib/format';
import { profileCanonical, profileRobots, xpProgressPercent } from '../lib/profileUi';
import { absoluteUrl, metaDescription, useSeo } from '../lib/seo';
import { useAuthStore } from '../stores/auth';
import { toast } from '../stores/toast';

function buildProfileJsonLd(profile: PublicProfileOut): Record<string, unknown> {
  const url = absoluteUrl(profileCanonical(profile.username));
  return {
    '@context': 'https://schema.org',
    '@type': 'ProfilePage',
    inLanguage: 'ru',
    dateCreated: profile.joined_at,
    mainEntity: {
      '@type': 'Person',
      name: profile.display_name,
      alternateName: `@${profile.username}`,
      description: profile.bio || undefined,
      url,
    },
  };
}

export default function PublicProfilePage() {
  const { handle = '' } = useParams<{ handle: string }>();
  const navigate = useNavigate();
  const user = useAuthStore((state) => state.user);
  const accessToken = useAuthStore((state) => state.accessToken);
  const [reportOpen, setReportOpen] = useState(false);
  const [reason, setReason] = useState('');
  const timezone = useMemo(() => {
    try {
      return Intl.DateTimeFormat().resolvedOptions().timeZone;
    } catch {
      return undefined;
    }
  }, []);

  const profileQuery = useQuery({
    // The token is part of the key: Zustand rehydrates localStorage after the
    // first render, and without this the owner would briefly fetch and cache
    // the guest version of their own card.
    queryKey: ['profile', handle, accessToken ?? 'guest'],
    queryFn: async ({ signal }) => {
      try {
        return await api.getProfile(handle, timezone, signal);
      } catch (error) {
        // A stale reader token must not hide a public card from its owner or
        // from a signed-in visitor; retry as an anonymous request.
        if (error instanceof ApiError && error.status === 401) {
          return api.getProfile(handle, timezone, signal, false);
        }
        throw error;
      }
    },
    enabled: Boolean(handle),
    staleTime: 60_000,
    retry: (failureCount, error) =>
      !(error instanceof ApiError && [401, 404].includes(error.status)) && failureCount < 1,
  });
  const profile = profileQuery.data;

  const reportMutation = useMutation({
    mutationFn: () => api.reportProfile(profile?.username ?? handle, reason),
    onSuccess: (result) => {
      setReportOpen(false);
      setReason('');
      toast.success(result.message || 'Жалоба отправлена на проверку');
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : 'Не удалось отправить жалобу'),
  });
  const blockMutation = useMutation({
    mutationFn: () => api.blockProfile(profile?.username ?? handle),
    onSuccess: () => {
      toast.success('Пользователь заблокирован');
      navigate('/');
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : 'Не удалось заблокировать пользователя'),
  });

  const indexable = Boolean(profile?.indexable);
  useSeo({
    title: profile
      ? `${profile.display_name} (@${profile.username}) — профиль — MangaPoisk Reborn`
      : 'Профиль — MangaPoisk Reborn',
    description: profile
      ? metaDescription(
          profile.bio ||
            `Профиль ${profile.display_name}: уровень ${profile.level}, звание «${profile.rank.label}», статистика чтения и достижения.`,
        )
      : 'Публичный профиль читателя MangaPoisk Reborn.',
    canonical: profile ? profileCanonical(profile.username) : null,
    // Owner responses contain exact timestamps, so their document is noindex
    // too; search crawlers only ever see the guest version.
    robots: profileRobots(indexable && !profile?.is_owner),
    image: null,
    type: 'website',
    jsonLd: profile && indexable ? buildProfileJsonLd(profile) : null,
  });

  if (profileQuery.isLoading) {
    return (
      <div className="page container public-profile">
        <Skeleton height="210px" style={{ borderRadius: 18 }} />
        <div className="public-profile__grid" style={{ marginTop: 18 }}>
          <Skeleton height="320px" style={{ borderRadius: 16 }} />
          <Skeleton height="240px" style={{ borderRadius: 16 }} />
        </div>
      </div>
    );
  }

  if (profileQuery.isError) {
    const notFound = profileQuery.error instanceof ApiError && profileQuery.error.status === 404;
    if (notFound) {
      return (
        <div className="page container">
          <EmptyState
            icon="lock"
            title="Профиль недоступен"
            description="Профиль не найден, скрыт настройками приватности или заблокирован."
            action={
              <Link className="btn btn--outline" to="/">
                <Icon name="home" size={17} />
                На главную
              </Link>
            }
          />
        </div>
      );
    }
    return (
      <div className="page container">
        <ErrorState
          title="Профиль не загрузился"
          message={profileQuery.error instanceof Error ? profileQuery.error.message : undefined}
          onRetry={() => void profileQuery.refetch()}
        />
      </div>
    );
  }

  if (!profile) return null;

  const progressPercent = xpProgressPercent(profile);
  const owner = profile.is_owner;
  const canModerate = Boolean(user) && !owner;

  return (
    <div className="page container public-profile">
      <header className="public-profile__hero">
        <div className="public-profile__identity">
          <span className="avatar avatar--xl" aria-hidden="true">
            {profile.avatar_initials || initials(profile.display_name)}
          </span>
          <div className="public-profile__titles">
            <span className="eyebrow">Публичный профиль</span>
            <h1 className="page-title">{profile.display_name}</h1>
            <p className="public-profile__handle">@{profile.username}</p>
            <div className="public-profile__badges">
              <span className="badge badge--accent">
                <Icon name="star" size={13} />
                {profile.rank.label}
              </span>
              <span className="badge">Уровень {profile.level}</span>
              <span className="public-profile__joined">
                С нами с {formatDate(profile.joined_at)}
              </span>
            </div>
          </div>
        </div>
        <div className="public-profile__actions">
          {owner ? (
            <Link className="btn btn--outline btn--sm" to="/profile">
              <Icon name="settings" size={16} />
              Настроить профиль
            </Link>
          ) : null}
          {canModerate ? (
            <>
              <button
                type="button"
                className="btn btn--ghost btn--sm"
                onClick={() => setReportOpen(true)}
              >
                <Icon name="alert" size={16} />
                Пожаловаться
              </button>
              <button
                type="button"
                className="btn btn--ghost btn--sm is-danger"
                disabled={blockMutation.isPending}
                onClick={() => {
                  if (window.confirm('Заблокировать пользователя? Его профиль исчезнет для вас.')) {
                    blockMutation.mutate();
                  }
                }}
              >
                <Icon name="shield" size={16} />
                Заблокировать
              </button>
            </>
          ) : null}
        </div>
      </header>

      {owner && !profile.indexable ? (
        <div className="public-profile__notice">
          <Icon name="eye-off" size={16} />
          <span>
            Профиль не виден гостям или не индексируется. Проверьте раздел «Приватность» в
            настройках.
          </span>
        </div>
      ) : null}

      <div className="public-profile__grid">
        <main className="public-profile__main">
          <section className="public-profile__panel" aria-labelledby="profile-about">
            <div className="public-profile__panel-head">
              <h2 id="profile-about">О читателе</h2>
            </div>
            {profile.bio ? (
              <p className="public-profile__bio">{profile.bio}</p>
            ) : (
              <p className="public-profile__muted">Пока без описания.</p>
            )}
          </section>

          {profile.stats ? (
            <section className="public-profile__panel" aria-labelledby="profile-stats">
              <div className="public-profile__panel-head">
                <h2 id="profile-stats">Статистика чтения</h2>
                <span className="public-profile__hint">Агрегаты, без истории и времени</span>
              </div>
              <div className="profile-stats-grid">
                <StatCard label="Глав прочитано" value={profile.stats.chapters_read} />
                <StatCard label="Тайтлов" value={profile.stats.titles_read} />
                <StatCard label="Завершено" value={profile.stats.finished_titles} />
                <StatCard label="Дней чтения" value={profile.stats.reading_days} />
                <StatCard label="Серия сейчас" value={profile.stats.current_streak} />
                <StatCard label="Лучшая серия" value={profile.stats.longest_streak} />
              </div>
            </section>
          ) : null}

          {profile.achievements.length > 0 || owner ? (
            <section className="public-profile__panel" aria-labelledby="profile-achievements">
              <div className="public-profile__panel-head">
                <h2 id="profile-achievements">Достижения</h2>
                <span className="public-profile__hint">
                  {profile.achievements_unlocked} из {profile.achievements_total}
                </span>
              </div>
              <div className="achievement-grid">
                {profile.achievements.map((item) => (
                  <AchievementCard key={item.code} item={item} owner={owner} />
                ))}
              </div>
            </section>
          ) : null}

          {profile.events.length > 0 ? (
            <section className="public-profile__panel" aria-labelledby="profile-events">
              <div className="public-profile__panel-head">
                <h2 id="profile-events">Последние события</h2>
                <span className="public-profile__hint">Даты без точного времени</span>
              </div>
              <ol className="profile-events">
                {profile.events.map((item) => (
                  <EventRow key={item.id} item={item} />
                ))}
              </ol>
            </section>
          ) : owner ? (
            <section className="public-profile__panel" aria-labelledby="profile-events">
              <div className="public-profile__panel-head">
                <h2 id="profile-events">Последние события</h2>
              </div>
              <p className="public-profile__muted">
                Событий пока нет. Они появятся после чтения глав.
              </p>
            </section>
          ) : null}
        </main>

        <aside className="public-profile__aside">
          <section className="public-profile__panel level-card" aria-labelledby="profile-level">
            <div className="level-card__head">
              <div>
                <span className="level-card__eyebrow">Уровень</span>
                <strong className="level-card__value">{profile.level}</strong>
              </div>
              <span className="badge badge--accent">{profile.rank.label}</span>
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
            <div className="level-card__meta">
              {profile.xp_for_next_level > 0
                ? `${formatInt(profile.xp_into_level)} / ${formatInt(profile.xp_for_next_level)} XP`
                : 'Максимальный уровень'}
            </div>
            {profile.next_rank ? (
              <div className="level-card__next">
                Следующее звание: <strong>{profile.next_rank.label}</strong> с {profile.next_rank.min_level} уровня
              </div>
            ) : (
              <div className="level-card__next">Максимальное звание достигнуто</div>
            )}
          </section>

          {profile.favorite_genres.length > 0 ? (
            <section className="public-profile__panel" aria-labelledby="profile-genres">
              <div className="public-profile__panel-head">
                <h2 id="profile-genres">Любимые жанры</h2>
              </div>
              <div className="profile-genres">
                {profile.favorite_genres.map((item) => (
                  <span className="chip" key={item.genre}>
                    {item.genre}
                    <span className="chip__count">{item.count}</span>
                  </span>
                ))}
              </div>
            </section>
          ) : null}

          <section className="public-profile__panel public-profile__privacy" aria-labelledby="profile-privacy">
            <div className="public-profile__panel-head">
              <h2 id="profile-privacy">Приватность</h2>
            </div>
            <p>
              {profile.indexable
                ? 'Публичная карточка индексируется поиском. Точные даты и время чтения скрыты.'
                : 'Карточка не индексируется поиском.'}
            </p>
            <p>В публичном профиле нет email, IP и точных меток времени.</p>
          </section>
        </aside>
      </div>

      <Modal
        open={reportOpen}
        onClose={() => setReportOpen(false)}
        title="Пожаловаться на профиль"
        description="Опишите, что нарушает правила. Жалоба попадёт модераторам."
        size="sm"
        footer={
          <>
            <button type="button" className="btn btn--ghost" onClick={() => setReportOpen(false)}>
              Отмена
            </button>
            <button
              type="button"
              className="btn btn--primary"
              disabled={reportMutation.isPending || reason.trim().length < 3}
              onClick={() => reportMutation.mutate()}
            >
              {reportMutation.isPending ? 'Отправка…' : 'Отправить жалобу'}
            </button>
          </>
        }
      >
        <label className="field">
          <span className="field__label">Причина</span>
          <textarea
            className="textarea"
            value={reason}
            maxLength={500}
            data-autofocus
            onChange={(event) => setReason(event.target.value)}
            placeholder="Например: оскорбительное био или имя"
          />
          <span className="field__hint">{reason.length} / 500</span>
        </label>
        {reportMutation.isError ? (
          <div style={{ marginTop: 10 }}>
            <InlineError
              message={
                reportMutation.error instanceof Error
                  ? reportMutation.error.message
                  : 'Не удалось отправить жалобу'
              }
            />
          </div>
        ) : null}
      </Modal>
    </div>
  );
}
