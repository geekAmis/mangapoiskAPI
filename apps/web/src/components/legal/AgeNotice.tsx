import { Link } from 'react-router-dom';
import { setAgeConfirmation, useAgeConfirmation } from '../../lib/age';
import { Icon } from '../Icon';

/**
 * A non-blocking reminder on adult title pages.  It does not hide chapters or
 * pretend to verify age; the reader can confirm locally and read the rules on
 * /age at any time.
 */
export function AgeNotice() {
  const confirmed = useAgeConfirmation();
  if (confirmed) return null;

  return (
    <aside className="age-notice" role="note" aria-label="Контент 18+">
      <Icon name="shield" size={18} />
      <div className="age-notice__body">
        <strong>Тайтл помечен 18+</strong>
        <span>
          В нём могут быть сцены для взрослых. Подтвердите возраст, если вам уже
          исполнилось 18 лет, или прочитайте{' '}
          <Link to="/age">правила взрослого контента</Link>.
        </span>
      </div>
      <button
        type="button"
        className="btn btn--outline btn--sm"
        onClick={() => setAgeConfirmation(true)}
      >
        Мне 18+
      </button>
    </aside>
  );
}
