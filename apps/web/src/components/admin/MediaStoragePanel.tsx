import { useQuery } from '@tanstack/react-query';
import { adminApi, adminErrorMessage, type AdminStorageLevel } from '../../api/admin';
import { ErrorState } from '../ErrorState';
import { Icon } from '../Icon';
import { Skeleton } from '../Skeleton';
import { formatDateTime, formatInt } from '../../lib/format';
import { formatBytes } from '../../lib/offlineTypes';

const LEVEL_LABELS: Record<AdminStorageLevel, string> = {
  ok: 'В норме',
  warning: '80%+',
  critical: '90%+',
  unbounded: 'Без лимита',
};

function usageWidth(percent: number): string {
  if (!Number.isFinite(percent) || percent <= 0) return '0%';
  return `${Math.min(100, percent)}%`;
}

function StorageCard({
  title,
  usedBytes,
  capBytes,
  usagePercent,
  level,
  details,
}: {
  title: string;
  usedBytes: number;
  capBytes: number;
  usagePercent: number;
  level: AdminStorageLevel;
  details: Array<[string, string]>;
}) {
  return (
    <div className={`admin-storage-card admin-storage-card--${level}`}>
      <header>
        <div>
          <h3>{title}</h3>
          <span>{capBytes > 0 ? `${formatBytes(usedBytes)} из ${formatBytes(capBytes)}` : formatBytes(usedBytes)}</span>
        </div>
        <span className={`badge admin-storage-level admin-storage-level--${level}`}>
          {LEVEL_LABELS[level]}
        </span>
      </header>
      <div
        className="admin-usage"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(usagePercent)}
        aria-label={`${title}: ${usagePercent.toFixed(1)}%`}
      >
        <span
          className={`admin-usage__fill admin-usage__fill--${level}`}
          style={{ width: usageWidth(usagePercent) }}
        />
      </div>
      <div className="admin-storage-card__meta">
        <strong>{capBytes > 0 ? `${usagePercent.toFixed(1)}%` : '—'}</strong>
        <span>занято</span>
      </div>
      <dl className="admin-storage-facts">
        {details.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

export function MediaStoragePanel({ active = true }: { active?: boolean }) {
  const query = useQuery({
    queryKey: ['admin', 'media-stats'],
    queryFn: ({ signal }) => adminApi.getMediaStats(signal),
    enabled: active,
    refetchInterval: active ? 60_000 : false,
    retry: 1,
  });
  const data = query.data;

  return (
    <section className="admin-panel" aria-labelledby="admin-storage-title">
      <div className="admin-panel__head">
        <div>
          <h2 id="admin-storage-title">Хранилище медиа</h2>
          <p>
            LRU-кэш изображений и архив глав. Удаляются только байты кэша — каталог,
            закладки и метаданные не затрагиваются.
          </p>
        </div>
        <button
          type="button"
          className="btn btn--outline btn--sm"
          onClick={() => void query.refetch()}
          disabled={query.isFetching}
        >
          <Icon name="refresh" size={15} />
          Обновить
        </button>
      </div>

      {query.isLoading ? (
        <div className="admin-storage-grid" aria-hidden="true">
          {Array.from({ length: 2 }, (_, index) => (
            <Skeleton key={index} height="220px" style={{ borderRadius: 12 }} />
          ))}
        </div>
      ) : query.isError ? (
        <ErrorState
          title="Статистика хранилища недоступна"
          message={adminErrorMessage(query.error, 'Медиа-сервис не ответил.')}
          onRetry={() => void query.refetch()}
        />
      ) : data ? (
        <>
          {data.warnings.length > 0 ? (
            <div className="admin-storage-warnings" role="status">
              {data.warnings.map((warning) => (
                <p key={warning}>
                  <Icon name="alert" size={15} />
                  {warning}
                </p>
              ))}
            </div>
          ) : null}

          <div className="admin-storage-grid">
            <StorageCard
              title="Кэш изображений"
              usedBytes={data.image_cache.used_bytes}
              capBytes={data.image_cache.cap_bytes}
              usagePercent={data.image_cache.usage_percent}
              level={data.image_cache.level}
              details={[
                ['Файлов', formatInt(data.image_cache.files)],
                ['Evictions', formatInt(data.image_cache.evictions)],
                ['Последняя очистка', formatDateTime(data.image_cache.last_pruned_at)],
              ]}
            />
            <StorageCard
              title="Архив глав"
              usedBytes={data.archives.done_bytes}
              capBytes={data.archives.cap_bytes}
              usagePercent={data.archives.usage_percent}
              level={data.archives.level}
              details={[
                ['Готово глав', formatInt(data.archives.done)],
                ['Ошибки / в работе', `${formatInt(data.archives.failed)} / ${formatInt(data.archives.pending)}`],
                ['SQLite', formatBytes(data.archives.db_bytes)],
                ['Evictions', formatInt(data.archives.evictions)],
                ['Последняя очистка', formatDateTime(data.archives.last_pruned_at)],
              ]}
            />
          </div>

          <p className="admin-storage-footnote">
            Снимок от {formatDateTime(data.generated_at)}. Лимиты задаются через
            MEDIA_CACHE_MAX_BYTES и ARCHIVE_MAX_BYTES; 0 отключает eviction для
            соответствующего хранилища.
          </p>
        </>
      ) : null}
    </section>
  );
}
