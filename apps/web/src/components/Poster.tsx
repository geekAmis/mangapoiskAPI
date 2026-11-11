import { useEffect, useState } from 'react';
import { resolveApiUrl } from '../api/client';
import { Icon } from './Icon';

function normalizePoster(src: string | null | undefined): string | null {
  if (!src) return null;
  const trimmed = src.trim();
  if (!trimmed) return null;
  return resolveApiUrl(trimmed);
}

interface PosterProps {
  src: string | null | undefined;
  alt: string;
  className?: string;
  blurred?: boolean;
  eager?: boolean;
}

export function Poster({ src, alt, className, blurred = false, eager = false }: PosterProps) {
  const normalized = normalizePoster(src);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    setFailed(false);
  }, [normalized]);

  const classes = ['poster', className].filter(Boolean).join(' ');

  return (
    <div className={classes}>
      {normalized && !failed ? (
        <img
          className={`poster__img${blurred ? ' is-blurred' : ''}`}
          src={normalized}
          alt={alt}
          loading={eager ? 'eager' : 'lazy'}
          decoding="async"
          draggable={false}
          onError={() => setFailed(true)}
        />
      ) : (
        <div className="poster__fallback" role="img" aria-label={alt}>
          <Icon name="book" size={30} />
          <span>Нет обложки</span>
        </div>
      )}
    </div>
  );
}
