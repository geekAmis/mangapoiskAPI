import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import type { MangaOut } from '../api/types';
import { chaptersLabel, formatRelative, sourceLabel } from '../lib/format';
import { mangaPath } from '../lib/mangaRoute';
import { useReaderStore } from '../stores/reader';
import { Icon } from './Icon';
import { Poster } from './Poster';
import { Rating } from './Rating';

interface MangaCardProps {
  manga: MangaOut;
  action?: ReactNode;
  eager?: boolean;
  compact?: boolean;
}

export function MangaCard({ manga, action, eager = false, compact = false }: MangaCardProps) {
  const blurAdultPosters = useReaderStore((state) => state.blurAdultPosters);
  const shouldBlur = manga.adult && blurAdultPosters;
  const meta = [manga.year ? String(manga.year) : null, chaptersLabel(manga.chapters_count)].filter(Boolean);

  return (
    <article className={`manga-card${compact ? ' manga-card--compact' : ''}`}>
      <div className="manga-card__cover-wrap">
        <Link
          to={mangaPath(manga)}
          className="manga-card__cover"
          aria-label={`${manga.title}${manga.adult ? ', 18+' : ''}`}
        >
          <Poster
            src={manga.poster_url}
            alt={`Обложка «${manga.title}»`}
            blurred={shouldBlur}
            eager={eager}
          />
          <span className="manga-card__shade" aria-hidden="true" />
          <span className="manga-card__rating">
            <Rating value={manga.rating} compact />
          </span>
          {manga.adult ? (
            <span className="manga-card__adult" title={shouldBlur ? 'Обложка скрыта настройкой 18+' : 'Контент 18+'}>
              18+
            </span>
          ) : null}
          {manga.last_chapter_at ? (
            <span className="manga-card__update">{formatRelative(manga.last_chapter_at)}</span>
          ) : null}
        </Link>
        {action ? <div className="manga-card__action">{action}</div> : null}
      </div>
      <div className="manga-card__body">
        <Link to={mangaPath(manga)} className="manga-card__title">
          {manga.title}
        </Link>
        <div className="manga-card__meta">
          <span className="manga-card__source">
            <Icon name="compass" size={12} />
            {sourceLabel(manga.source)}
          </span>
          <span aria-hidden="true">·</span>
          <span>{meta.join(' · ')}</span>
        </div>
      </div>
    </article>
  );
}
