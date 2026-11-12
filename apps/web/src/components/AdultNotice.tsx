import { Icon } from './Icon';

interface AdultNoticeProps {
  source?: string | null;
  compact?: boolean;
}

/**
 * Visible 18+ warning shown on adult title and reader surfaces.
 *
 * It is intentionally informational: access control happens on the server.
 */
export function AdultNotice({ source, compact = false }: AdultNoticeProps) {
  return (
    <aside
      className={`adult-notice${compact ? ' adult-notice--compact' : ''}`}
      role="note"
      aria-label="Предупреждение о контенте 18+"
    >
      <span className="adult-notice__badge">18+</span>
      <div>
        <strong>Контент для взрослых</strong>
        <p>
          Тайтл содержит материалы 18+. Просмотр разрешён только пользователям с
          подтверждённым возрастом.
          {source === 'hentailib' ? ' Источник: HentaiLib.' : ''}
        </p>
      </div>
      <Icon name="shield" size={20} />
    </aside>
  );
}
