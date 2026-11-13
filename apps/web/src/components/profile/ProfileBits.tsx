import { Link } from 'react-router-dom';
import type { AchievementOut, ProfileEventOut } from '../../api/types';
import { formatDate, formatInt } from '../../lib/format';
import { eventKindLabel } from '../../lib/profileUi';
import { Icon, type IconName } from '../Icon';

const ACHIEVEMENT_ICONS: Record<string, IconName> = {
  book: 'book',
  star: 'star',
  sparkles: 'sparkles',
  compass: 'compass',
  grid: 'grid',
  list: 'list',
  check: 'check',
  clock: 'clock',
  heart: 'heart',
};

export function achievementIcon(item: AchievementOut): IconName {
  return ACHIEVEMENT_ICONS[item.icon] ?? 'star';
}

export function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="profile-stat">
      <span className="profile-stat__value">{formatInt(value)}</span>
      <span className="profile-stat__label">{label}</span>
    </div>
  );
}

export function AchievementCard({ item, owner }: { item: AchievementOut; owner: boolean }) {
  const progress = item.target > 0 ? Math.min(1, item.progress / item.target) : 0;
  return (
    <article className={`achievement-card${item.unlocked ? ' is-unlocked' : ' is-locked'}`}>
      <span className="achievement-card__icon" aria-hidden="true">
        <Icon name={achievementIcon(item)} size={19} />
      </span>
      <div className="achievement-card__body">
        <div className="achievement-card__title">
          <span>{item.title}</span>
          {item.unlocked ? (
            <span className="badge badge--success">Получено</span>
          ) : owner ? (
            <span className="badge">
              {item.progress} / {item.target}
            </span>
          ) : null}
        </div>
        <p className="achievement-card__desc">{item.description}</p>
        {owner && !item.unlocked ? (
          <div className="progress progress--slim" aria-hidden="true">
            <span style={{ width: `${Math.round(progress * 100)}%` }} />
          </div>
        ) : null}
      </div>
    </article>
  );
}

export function EventRow({ item }: { item: ProfileEventOut }) {
  const icon: IconName =
    item.kind === 'achievement' ? 'sparkles' : item.kind === 'title_finished' ? 'check' : 'book';
  return (
    <li className="profile-event">
      <span className="profile-event__dot" aria-hidden="true">
        <Icon name={icon} size={15} />
      </span>
      <div className="profile-event__body">
        <div className="profile-event__head">
          <span className="profile-event__kind">{eventKindLabel(item.kind)}</span>
          <time className="profile-event__date" dateTime={item.occurred_on}>
            {formatDate(item.occurred_on)}
          </time>
        </div>
        <div className="profile-event__title">{item.title}</div>
        {item.subtitle ? <div className="profile-event__subtitle">{item.subtitle}</div> : null}
      </div>
      {item.manga_id ? (
        <Link className="profile-event__link" to={`/manga/${item.manga_id}`} aria-label="Открыть тайтл">
          <Icon name="chevron-right" size={17} />
        </Link>
      ) : null}
    </li>
  );
}
