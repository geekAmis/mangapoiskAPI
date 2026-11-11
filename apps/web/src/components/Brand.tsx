import { Link } from 'react-router-dom';

export function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <Link to="/" className="brand" aria-label="MangaPoisk Reborn — на главную">
      <span className="brand__mark" aria-hidden="true">
        <svg width="30" height="30" viewBox="0 0 64 64" focusable="false">
          <rect width="64" height="64" rx="15" fill="currentColor" opacity=".08" />
          <path
            d="M13 19.5c5.6-2.1 11.6-1.3 17.4 2.6v25.2c-5.8-3.8-11.8-4.6-17.4-2.5V19.5Z"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.3"
            strokeLinejoin="round"
          />
          <path
            d="M51 19.5c-5.6-2.1-11.6-1.3-17.4 2.6v25.2c5.8-3.8 11.8-4.6 17.4-2.5V19.5Z"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.3"
            strokeLinejoin="round"
          />
          <path d="M32 22.1v25.2" stroke="currentColor" strokeWidth="2.1" strokeLinecap="round" />
          <circle cx="32" cy="16.5" r="2" fill="currentColor" />
        </svg>
      </span>
      <span className="brand__text">
        <span className="brand__name">MangaPoisk</span>
        {!compact && <span className="brand__sub">Reborn</span>}
      </span>
    </Link>
  );
}
