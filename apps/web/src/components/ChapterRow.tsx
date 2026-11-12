import { Link } from 'react-router-dom';
import type { ChapterOut } from '../api/types';
import {
  chapterHeading,
  chapterSecondaryTitle,
  formatRelative,
  formatShortDate,
  pagesLabel,
} from '../lib/format';
import type { DownloadJobStatus } from '../lib/offlineTypes';
import { DancingSpinner } from './DancingLoader';
import { Icon } from './Icon';

interface ChapterRowProps {
  chapter: ChapterOut;
  current?: boolean;
  /** Глава уже сохранена в офлайн-библиотеке устройства. */
  downloaded?: boolean;
  /** Текущий статус офлайн-загрузки главы, если задание существует. */
  downloadStatus?: DownloadJobStatus;
  offlineHref?: string;
  onDownload?: (chapter: ChapterOut) => void;
}

export function ChapterRow({
  chapter,
  current = false,
  downloaded = false,
  downloadStatus,
  offlineHref,
  onDownload,
}: ChapterRowProps) {
  const heading = chapterHeading(chapter);
  const secondary = chapterSecondaryTitle(chapter);
  const date = chapter.published_at ? formatRelative(chapter.published_at) : '';
  const external = chapter.is_external && chapter.url;
  const mainClassName = `chapter-row__main${current ? ' is-current' : ''}`;
  const downloading = downloadStatus === 'queued' || downloadStatus === 'running';
  const failed = downloadStatus === 'error';

  const inner = (
    <>
      <span className="chapter-row__index" aria-hidden="true">
        {current ? <Icon name="book" size={18} /> : <span>{chapter.number || '•'}</span>}
      </span>
      <span className="chapter-row__info">
        <span className="chapter-row__heading">
          {heading}
          {current ? <span className="chapter-row__badge">Вы здесь</span> : null}
        </span>
        {secondary ? <span className="chapter-row__subtitle">{secondary}</span> : null}
        <span className="chapter-row__meta">
          {date ? <span title={formatShortDate(chapter.published_at)}>{date}</span> : null}
          {date && chapter.page_count ? <span aria-hidden="true">·</span> : null}
          {chapter.page_count ? <span>{pagesLabel(chapter.page_count)}</span> : null}
          {chapter.translator ? (
            <>
              <span aria-hidden="true">·</span>
              <span className="chapter-row__translator" title={`Перевод: ${chapter.translator}`}>
                {chapter.translator}
              </span>
            </>
          ) : null}
          {downloaded ? (
            <>
              <span aria-hidden="true">·</span>
              <span className="chapter-row__offline">На устройстве</span>
            </>
          ) : null}
          {external ? (
            <>
              <span aria-hidden="true">·</span>
              <span>На сайте источника</span>
            </>
          ) : null}
        </span>
      </span>
      <span className="chapter-row__tail" aria-hidden="true">
        {external ? <Icon name="external" size={17} /> : <Icon name="chevron-right" size={18} />}
      </span>
    </>
  );

  return (
    <div className={`chapter-row${current ? ' is-current' : ''}`}>
      {external && chapter.url ? (
        <a
          className={mainClassName}
          href={chapter.url}
          target="_blank"
          rel="noopener noreferrer"
          aria-label={`${heading} — открыть на сайте источника`}
        >
          {inner}
        </a>
      ) : (
        <Link className={mainClassName} to={`/reader/${chapter.id}`} aria-current={current ? 'page' : undefined}>
          {inner}
        </Link>
      )}
      {downloaded && offlineHref ? (
        <Link
          className="btn btn--icon btn--ghost chapter-row__download is-done"
          to={offlineHref}
          aria-label={`${heading} — на устройстве, читать офлайн`}
          title="На устройстве — читать офлайн"
        >
          <Icon name="check" size={17} />
        </Link>
      ) : onDownload && !external ? (
        <button
          type="button"
          className="btn btn--icon btn--ghost chapter-row__download"
          onClick={() => onDownload(chapter)}
          disabled={downloading}
          aria-busy={downloading}
          aria-label={
            downloading
              ? `${heading} — скачивается на устройство`
              : `${heading} — скачать на устройство`
          }
          title={
            downloading
              ? 'Скачиваем на устройство…'
              : failed
                ? 'Повторить скачивание на устройство'
                : 'Скачать на устройство'
          }
        >
          {downloading ? (
            <DancingSpinner size={16} />
          ) : (
            <Icon name={failed ? 'refresh' : 'download'} size={17} />
          )}
        </button>
      ) : null}
    </div>
  );
}
