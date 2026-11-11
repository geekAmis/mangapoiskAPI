import type { CSSProperties } from 'react';

interface SkeletonProps {
  className?: string;
  width?: string;
  height?: string;
  style?: CSSProperties;
}

export function Skeleton({ className, width, height, style }: SkeletonProps) {
  return (
    <span
      className={`skeleton${className ? ` ${className}` : ''}`}
      style={{ width, height, ...style }}
      aria-hidden="true"
    />
  );
}

export function MangaCardSkeleton() {
  return (
    <div className="manga-card-skeleton" aria-hidden="true">
      <Skeleton className="manga-card-skeleton__poster" />
      <Skeleton className="manga-card-skeleton__title" />
      <Skeleton className="manga-card-skeleton__meta" />
    </div>
  );
}

export function MangaGridSkeleton({ count = 12 }: { count?: number }) {
  return (
    <div className="manga-grid" aria-hidden="true">
      {Array.from({ length: count }, (_, index) => (
        <MangaCardSkeleton key={index} />
      ))}
    </div>
  );
}

export function ReaderSkeleton() {
  return (
    <div className="reader-skeleton" aria-busy="true" aria-label="Загрузка главы">
      <div className="reader-skeleton__header">
        <Skeleton width="90px" height="20px" />
        <Skeleton width="220px" height="20px" />
        <Skeleton width="90px" height="20px" />
      </div>
      <div className="reader-skeleton__pages">
        {Array.from({ length: 3 }, (_, index) => (
          <Skeleton key={index} className="reader-skeleton__page" />
        ))}
      </div>
    </div>
  );
}
