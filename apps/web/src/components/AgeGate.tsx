import { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { api } from '../api/client';
import { Icon } from './Icon';
import { useAuthStore } from '../stores/auth';
import { toast } from '../stores/toast';

interface AgeGateProps {
  /** Whether the visitor is signed in but has not confirmed 18+. */
  signedIn: boolean;
  onConfirmed?: () => void;
}

/**
 * Age confirmation gate for adult-only titles and reader routes.
 *
 * The server is the source of truth and returns 403 without content.  This
 * component only explains the restriction and offers the self-confirmation
 * action; it never receives or renders any adult title data.
 */
export function AgeGate({ signedIn, onConfirmed }: AgeGateProps) {
  const location = useLocation();
  const setAgeConfirmedAt = useAuthStore((state) => state.setAgeConfirmedAt);
  const [checked, setChecked] = useState(false);
  const [busy, setBusy] = useState(false);

  const confirm = async () => {
    if (!checked || busy) return;
    setBusy(true);
    try {
      const status = await api.confirmAge();
      setAgeConfirmedAt(status.age_confirmed_at);
      toast.success('Возраст 18+ подтверждён');
      onConfirmed?.();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось подтвердить возраст');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="page container">
      <section className="panel age-gate" aria-labelledby="age-gate-title">
        <span className="age-gate__badge" aria-hidden="true">
          18+
        </span>
        <h1 className="panel__title" id="age-gate-title">
          <Icon name="shield" size={22} />
          Контент для взрослых
        </h1>
        <p className="age-gate__text">
          Этот тайтл доступен только пользователям, подтвердившим, что им исполнилось 18 лет.
          Мы не собираем документы: подтверждение добровольное и его можно отозвать в любой
          момент в настройках профиля.
        </p>
        {signedIn ? (
          <>
            <label className="age-gate__check">
              <input
                type="checkbox"
                checked={checked}
                onChange={(event) => setChecked(event.target.checked)}
              />
              <span>Мне исполнилось 18 лет, и я хочу видеть контент для взрослых.</span>
            </label>
            <button
              type="button"
              className="btn btn--primary"
              disabled={!checked || busy}
              onClick={() => void confirm()}
            >
              <Icon name="shield" size={17} />
              {busy ? 'Подтверждаем…' : 'Подтвердить 18+'}
            </button>
          </>
        ) : (
          <>
            <p className="age-gate__text">
              Войдите в аккаунт и подтвердите возраст, чтобы открыть этот тайтл.
            </p>
            <Link
              className="btn btn--primary"
              to={`/login?next=${encodeURIComponent(location.pathname + location.search)}`}
            >
              <Icon name="user" size={17} />
              Войти в аккаунт
            </Link>
          </>
        )}
        <p className="age-gate__legal">
          Продолжая, вы подтверждаете, что достигли совершеннолетия и просмотр такого контента
          законен в вашей юрисдикции.
        </p>
      </section>
    </div>
  );
}
