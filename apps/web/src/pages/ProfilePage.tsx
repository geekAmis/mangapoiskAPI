import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ApiError } from '../api/client';
import { api } from '../api/client';
import { Icon } from '../components/Icon';
import { InlineError } from '../components/ErrorState';
import { NotificationSettingsPanel } from '../components/NotificationSettings';
import { ThemePicker } from '../components/ThemeSwitcher';
import { humanizeError } from '../lib/errors';
import { formatDate, initials } from '../lib/format';
import { useReducedMotion } from '../lib/hooks';
import { useSeo } from '../lib/seo';
import { useLogout } from '../lib/useLogout';
import { useAuthStore } from '../stores/auth';
import {
  DEFAULT_READER_PREFERENCES,
  clampSpeed,
  useReaderStore,
  type PageFit,
  type ReaderGap,
  type ReaderMode,
} from '../stores/reader';
import { toast } from '../stores/toast';

const MODES: Array<{ value: ReaderMode; title: string; description: string; icon: 'scroll' | 'columns' }> = [
  {
    value: 'vertical',
    title: 'Непрерывный',
    description: 'Вебтун и длинные страницы — обычная прокрутка',
    icon: 'scroll',
  },
  {
    value: 'horizontal',
    title: 'Постраничный',
    description: 'Одна страница за раз, свайпы и клавиши',
    icon: 'columns',
  },
];

const FITS: Array<{ value: PageFit; title: string; description: string }> = [
  { value: 'width', title: 'По ширине', description: 'Страница занимает всю ширину' },
  { value: 'height', title: 'По высоте', description: 'Страница вписывается в экран' },
  { value: 'original', title: 'Оригинал', description: 'Натуральный размер без растяжения' },
];

function roleLabel(role: string | undefined): string {
  if (!role) return 'Читатель';
  if (role === 'admin') return 'Администратор';
  if (role === 'moderator') return 'Модератор';
  return 'Читатель';
}

export default function ProfilePage() {
  useSeo({
    title: 'Профиль и настройки — MangaPoisk Reborn',
    description:
      'Настройки профиля MangaPoisk Reborn: тема оформления, режим читалки, размер страниц и параметры аккаунта.',
    canonical: null,
    robots: 'noindex,nofollow',
  });
  const user = useAuthStore((state) => state.user);
  const setUser = useAuthStore((state) => state.setUser);
  const logout = useLogout();
  const reducedMotion = useReducedMotion();

  const mode = useReaderStore((state) => state.mode);
  const pageFit = useReaderStore((state) => state.pageFit);
  const gap = useReaderStore((state) => state.gap);
  const autoScroll = useReaderStore((state) => state.autoScroll);
  const autoScrollSpeed = useReaderStore((state) => state.autoScrollSpeed);
  const showPageNumbers = useReaderStore((state) => state.showPageNumbers);
  const blurAdultPosters = useReaderStore((state) => state.blurAdultPosters);
  const update = useReaderStore((state) => state.update);
  const reset = useReaderStore((state) => state.reset);

  const meQuery = useQuery({
    queryKey: ['auth', 'me'],
    queryFn: ({ signal }) => api.me(signal),
    retry: (failureCount, error) => !(error instanceof ApiError && error.status === 401) && failureCount < 1,
  });

  useEffect(() => {
    if (meQuery.data) setUser(meQuery.data);
  }, [meQuery.data, setUser]);

  return (
    <div className="page container">
      <div className="page-head">
        <div className="page-head__main">
          <span className="eyebrow">Личные настройки</span>
          <h1 className="page-title">Профиль</h1>
          <p className="page-subtitle">
            Внешний вид, поведение читалки и данные аккаунта. Изменения сохраняются автоматически.
          </p>
        </div>
      </div>

      {meQuery.isError ? (
        <div style={{ marginBottom: 16 }}>
          <InlineError
            message={humanizeError(meQuery.error, 'Не удалось проверить профиль. Показаны сохранённые данные.')}
            onRetry={() => void meQuery.refetch()}
          />
        </div>
      ) : null}

      <div className="profile-layout">
        <aside className="profile-sidebar">
          <div className="profile-card">
            <span className="avatar avatar--lg" aria-hidden="true">
              {initials(user?.display_name)}
            </span>
            <div>
              <div className="profile-card__name">{user?.display_name ?? 'Читатель'}</div>
              <div className="profile-card__email">{user?.email ?? '—'}</div>
              <span className="badge badge--accent profile-card__role">{roleLabel(user?.role)}</span>
            </div>
            <div className="profile-card__joined">
              С нами с {formatDate(user?.created_at)}
            </div>
          </div>

          <nav className="profile-side-nav" aria-label="Разделы настроек">
            <a href="#appearance">
              <Icon name="palette" size={17} />
              Внешний вид
            </a>
            <a href="#reader-defaults">
              <Icon name="book" size={17} />
              Читалка по умолчанию
            </a>
            <a href="#notifications">
              <Icon name="bell" size={17} />
              Уведомления
            </a>
            <a href="#account">
              <Icon name="user" size={17} />
              Аккаунт
            </a>
            <button type="button" className="is-danger" onClick={() => void logout()}>
              <Icon name="logout" size={17} />
              Выйти из аккаунта
            </button>
          </nav>
        </aside>

        <div className="profile-content">
          <section className="panel" id="appearance" aria-labelledby="appearance-title">
            <div className="panel__head">
              <div>
                <h2 className="panel__title" id="appearance-title">
                  <Icon name="palette" size={19} />
                  Тема оформления
                </h2>
                <p className="panel__sub">
                  Шесть атмосферных палитр. Изображение используется только на главной, страницах входа и 404.
                </p>
              </div>
            </div>
            <ThemePicker />
            <div className="sync-note" style={{ marginTop: 14 }}>
              <Icon name="refresh" size={15} />
              <span>
                Тема сохраняется в этом браузере и синхронизируется с аккаунтом после входа.
              </span>
            </div>
          </section>

          <section className="panel" id="reader-defaults" aria-labelledby="reader-defaults-title">
            <div className="panel__head">
              <div>
                <h2 className="panel__title" id="reader-defaults-title">
                  <Icon name="book" size={19} />
                  Читалка по умолчанию
                </h2>
                <p className="panel__sub">
                  Настройки применятся к новой главе. В самой читалке их можно менять на лету.
                </p>
              </div>
              <div className="panel__actions">
                <button
                  type="button"
                  className="btn btn--ghost btn--sm"
                  onClick={() => {
                    reset();
                    toast.info('Настройки читалки сброшены');
                  }}
                >
                  <Icon name="refresh" size={15} />
                  Сбросить
                </button>
              </div>
            </div>

            <div className="reader-defaults">
              <div>
                <span className="field__label" style={{ display: 'block', marginBottom: 7 }}>
                  Режим чтения
                </span>
                <div className="reader-defaults__grid" role="radiogroup" aria-label="Режим чтения">
                  {MODES.map((item) => (
                    <button
                      key={item.value}
                      type="button"
                      className={`option-card${mode === item.value ? ' is-active' : ''}`}
                      role="radio"
                      aria-checked={mode === item.value}
                      onClick={() => update({ mode: item.value })}
                    >
                      <span className="option-card__title">
                        <Icon name={item.icon} size={16} />
                        {item.title}
                      </span>
                      <span className="option-card__desc">{item.description}</span>
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <span className="field__label" style={{ display: 'block', marginBottom: 7 }}>
                  Вписывание страницы
                </span>
                <div className="reader-defaults__grid" role="radiogroup" aria-label="Вписывание страницы">
                  {FITS.map((item) => (
                    <button
                      key={item.value}
                      type="button"
                      className={`option-card${pageFit === item.value ? ' is-active' : ''}`}
                      role="radio"
                      aria-checked={pageFit === item.value}
                      onClick={() => update({ pageFit: item.value })}
                    >
                      <span className="option-card__title">{item.title}</span>
                      <span className="option-card__desc">{item.description}</span>
                    </button>
                  ))}
                </div>
              </div>

              <div className="setting-row">
                <div className="setting-row__main">
                  <span className="setting-row__label">Отступ между страницами</span>
                  <span className="setting-row__desc">Промежуток в непрерывном режиме</span>
                </div>
                <div className="setting-row__control">
                  <select
                    className="select"
                    style={{ minHeight: 38, width: 108 }}
                    value={gap}
                    onChange={(event) => update({ gap: Number(event.target.value) as ReaderGap })}
                    aria-label="Отступ между страницами"
                  >
                    <option value={0}>0 px</option>
                    <option value={8}>8 px</option>
                    <option value={16}>16 px</option>
                    <option value={24}>24 px</option>
                    <option value={32}>32 px</option>
                  </select>
                </div>
              </div>

              <div className="setting-row">
                <div className="setting-row__main">
                  <span className="setting-row__label">Показывать номера страниц</span>
                  <span className="setting-row__desc">Подписи между страницами в непрерывном режиме</span>
                </div>
                <div className="setting-row__control">
                  <label className="switch">
                    <input
                      className="switch__input"
                      type="checkbox"
                      checked={showPageNumbers}
                      onChange={(event) => update({ showPageNumbers: event.target.checked })}
                    />
                    <span className="switch__track">
                      <span className="switch__thumb" />
                    </span>
                  </label>
                </div>
              </div>

              <div className="setting-row">
                <div className="setting-row__main">
                  <span className="setting-row__label">Размывать обложки 18+</span>
                  <span className="setting-row__desc">Скрывает постеры взрослых тайтлов в каталоге</span>
                </div>
                <div className="setting-row__control">
                  <label className="switch">
                    <input
                      className="switch__input"
                      type="checkbox"
                      checked={blurAdultPosters}
                      onChange={(event) => update({ blurAdultPosters: event.target.checked })}
                    />
                    <span className="switch__track">
                      <span className="switch__thumb" />
                    </span>
                  </label>
                </div>
              </div>

              <div className="setting-row">
                <div className="setting-row__main">
                  <span className="setting-row__label">Автопрокрутка</span>
                  <span className="setting-row__desc">
                    {reducedMotion
                      ? 'Отключена: в системе включено уменьшение движения'
                      : 'Прокручивает непрерывную главу с выбранной скоростью'}
                  </span>
                </div>
                <div className="setting-row__control">
                  <label className={`switch${reducedMotion ? ' switch--disabled' : ''}`}>
                    <input
                      className="switch__input"
                      type="checkbox"
                      checked={autoScroll}
                      disabled={reducedMotion}
                      onChange={(event) => update({ autoScroll: event.target.checked })}
                    />
                    <span className="switch__track">
                      <span className="switch__thumb" />
                    </span>
                  </label>
                </div>
              </div>

              {autoScroll && !reducedMotion ? (
                <div className="reader-settings__slider">
                  <div className="reader-settings__slider-head">
                    <span>Скорость автопрокрутки</span>
                    <output>{autoScrollSpeed} px/с</output>
                  </div>
                  <input
                    className="range"
                    type="range"
                    min={5}
                    max={200}
                    step={5}
                    value={autoScrollSpeed}
                    onChange={(event) => update({ autoScrollSpeed: clampSpeed(Number(event.target.value)) })}
                    aria-label="Скорость автопрокрутки"
                  />
                </div>
              ) : null}

              <div className="sync-note">
                <Icon name="settings" size={15} />
                <span>
                  Значения по умолчанию: непрерывный режим, скорость автопрокрутки{' '}
                  {DEFAULT_READER_PREFERENCES.autoScrollSpeed} px/с. Настройки синхронизируются с
                  профилем, когда сервер доступен.
                </span>
              </div>
            </div>
          </section>

          <NotificationSettingsPanel />

          <section className="panel" id="account" aria-labelledby="account-title">
            <div className="panel__head">
              <div>
                <h2 className="panel__title" id="account-title">
                  <Icon name="user" size={19} />
                  Аккаунт
                </h2>
                <p className="panel__sub">Данные профиля и состояние сессии.</p>
              </div>
            </div>
            <div className="account-list">
              <div className="account-list__row">
                <span className="account-list__label">Имя</span>
                <span className="account-list__value">{user?.display_name ?? '—'}</span>
              </div>
              <div className="account-list__row">
                <span className="account-list__label">Email</span>
                <span className="account-list__value">{user?.email ?? '—'}</span>
              </div>
              <div className="account-list__row">
                <span className="account-list__label">Роль</span>
                <span className="account-list__value">{roleLabel(user?.role)}</span>
              </div>
              <div className="account-list__row">
                <span className="account-list__label">Дата регистрации</span>
                <span className="account-list__value">{formatDate(user?.created_at)}</span>
              </div>
            </div>
            <div className="sync-note" style={{ marginTop: 14 }}>
              <Icon name="shield" size={15} />
              <span>
                Access-токен живёт 30 минут, refresh-токен — 30 дней и ротируется при обновлении.
                Токены хранятся в localStorage этого браузера; пароль на клиенте не сохраняется.
              </span>
            </div>
          </section>

          <section className="panel danger-zone" aria-labelledby="logout-title">
            <div className="panel__head">
              <div>
                <h2 className="panel__title" id="logout-title">
                  <Icon name="logout" size={19} />
                  Сессия
                </h2>
                <p className="panel__sub">Завершить сессию на этом устройстве.</p>
              </div>
            </div>
            <p className="danger-zone__text">
              Выход отзовёт refresh-токен на сервере и удалит токены из браузера. Закладки,
              история и настройки останутся в аккаунте.
            </p>
            <div className="danger-zone__actions">
              <button type="button" className="btn btn--danger-ghost" onClick={() => void logout()}>
                <Icon name="logout" size={17} />
                Выйти из аккаунта
              </button>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
