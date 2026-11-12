import { useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  adminApi,
  adminErrorMessage,
  type AdminCrawlState,
  type AdminCrawlerSource,
} from '../../api/admin';
import { ErrorState } from '../ErrorState';
import { Icon } from '../Icon';
import { Skeleton } from '../Skeleton';
import {
  chaptersLabel,
  formatBytes,
  formatDateTime,
  formatDuration,
  formatInt,
  formatRelative,
  pluralRu,
  sourceLabel,
} from '../../lib/format';

const STATUS_LABELS: Record<string, string> = {
  completed: 'Завершён',
  running: 'Идёт',
  failed: 'Ошибка',
  pending: 'Ожидает',
};

const STATUS_CLASSES: Record<string, string> = {
  completed: 'is-ok',
  running: 'is-running',
  failed: 'is-bad',
  pending: 'is-pending',
};

function statusLabel(status: string | undefined): string {
  if (!status) return 'Нет данных';
  return STATUS_LABELS[status] ?? status;
}

function stateClass(status: string | undefined): string {
  if (!status) return 'is-pending';
  return STATUS_CLASSES[status] ?? 'is-pending';
}

function StateBadge({ state }: { state: AdminCrawlState | null }) {
  if (!state) {
    return <span className="badge">не запускался</span>;
  }
  return (
    <span className={`admin-crawler-state ${stateClass(state.status)}`}>
      <span className="admin-crawler-state__dot" aria-hidden="true" />
      {statusLabel(state.status)}
    </span>
  );
}

function SourceCard({
  source,
  measuredEta,
}: {
  source: AdminCrawlerSource;
  measuredEta: number | null;
}) {
  const full = source.full;
  const incremental = source.incremental;
  const page = full?.page ?? 0;
  const total = full?.total_pages ?? null;
  const progress = source.progress_percent ?? (total ? Math.min(100, Math.round((page / total) * 1000) / 10) : 0);
  const eta = source.eta_seconds ?? measuredEta;
  const lastError = full?.last_error ?? incremental?.last_error ?? null;

  return (
    <article className="admin-crawler-source">
      <header className="admin-crawler-source__head">
        <div>
          <h3>{sourceLabel(source.source)}</h3>
          <span>{source.source}</span>
        </div>
        <StateBadge state={full} />
      </header>

      <div className="admin-crawler-source__metrics">
        <div>
          <span>Тайтлы</span>
          <strong>{formatInt(source.manga)}</strong>
          <small>{chaptersLabel(source.chapters)}</small>
        </div>
        <div>
          <span>Страница</span>
          <strong>{formatInt(page)}</strong>
          <small>
            {full?.status === 'completed'
              ? 'источник исчерпан'
              : total
                ? `из ${formatInt(total)}`
                : 'всего неизвестно'}
          </small>
        </div>
        <div>
          <span>ETA</span>
          <strong>{full?.status === 'running' ? formatDuration(eta) : '—'}</strong>
          <small>{full?.status === 'running' ? 'до конца обхода' : 'обход не идёт'}</small>
        </div>
        <div>
          <span>Импортировано</span>
          <strong>{formatInt(full?.items_imported ?? 0)}</strong>
          <small>из {formatInt(full?.items_seen ?? 0)} найденных</small>
        </div>
      </div>

      <div className="admin-crawler-progress" aria-label={`Прогресс обхода ${sourceLabel(source.source)}`}>
        <div className="admin-crawler-progress__track">
          <span style={{ width: `${Math.max(0, Math.min(100, progress))}%` }} />
        </div>
        <span>{progress ? `${progress.toFixed(1).replace('.', ',')}%` : '—'}</span>
      </div>

      <div className="admin-crawler-source__meta">
        <div>
          <span>Очередь обогащения</span>
          <strong>{formatInt(source.pending)}</strong>
        </div>
        <div>
          <span>Инкрементальный обход</span>
          <strong>{statusLabel(incremental?.status)}</strong>
        </div>
        <div>
          <span>Последний запуск</span>
          <strong>{full?.last_run_at ? formatRelative(full.last_run_at) : '—'}</strong>
        </div>
        <div>
          <span>Следующий запуск</span>
          <strong>{full?.next_run_at ? formatDateTime(full.next_run_at) : '—'}</strong>
        </div>
      </div>

      {lastError ? (
        <p className="admin-crawler-source__error" title={lastError}>
          <Icon name="alert" size={14} />
          <span>{lastError}</span>
        </p>
      ) : (
        <p className="admin-crawler-source__ok">
          <Icon name="check" size={14} />
          <span>Последний обход без ошибок</span>
        </p>
      )}
    </article>
  );
}

export function CrawlerStatusPanel() {
  const statusQuery = useQuery({
    queryKey: ['admin', 'crawl-status'],
    queryFn: ({ signal }) => adminApi.getCrawlerStatus(signal),
    refetchInterval: 15_000,
    staleTime: 5_000,
    retry: 1,
  });

  const previous = useRef<Map<string, { page: number; at: number }>>(new Map());
  const measured = useRef<Map<string, number>>(new Map());
  const data = statusQuery.data;

  useEffect(() => {
    if (!data) return;
    const now = Date.now();
    for (const source of data.sources) {
      const full = source.full;
      if (!full || full.status !== 'running') {
        measured.current.delete(source.source);
        previous.current.delete(source.source);
        continue;
      }
      const prior = previous.current.get(source.source);
      if (prior && full.page > prior.page) {
        const elapsed = (now - prior.at) / 1000;
        const rate = elapsed > 0 ? (full.page - prior.page) / elapsed : 0;
        if (rate > 0) measured.current.set(source.source, rate);
      }
      previous.current.set(source.source, { page: full.page, at: now });
    }
  }, [data]);

  const measuredEta = (source: AdminCrawlerSource): number | null => {
    const rate = measured.current.get(source.source);
    const full = source.full;
    const total = full?.total_pages ?? null;
    if (!rate || !total || !full) return null;
    return Math.max(0, Math.round((total - full.page) / rate));
  };

  const archive = data?.archive;
  const archivePercent = archive?.cap_bytes ? archive.usage_percent : 0;
  const warnings = data?.warnings ?? [];

  return (
    <section className="admin-panel admin-crawler-panel" aria-labelledby="admin-crawler-title">
      <div className="admin-panel__head">
        <div>
          <h2 id="admin-crawler-title">Состояние краулера</h2>
          <p>
            Живой обход источников, очередь обогащения, архив глав и кэш изображений.
            Обновляется автоматически каждые 15 секунд.
          </p>
        </div>
        <button
          type="button"
          className="btn btn--outline btn--sm"
          onClick={() => void statusQuery.refetch()}
          disabled={statusQuery.isFetching}
        >
          <Icon name="refresh" size={15} />
          {statusQuery.isFetching ? 'Обновляем…' : 'Обновить'}
        </button>
      </div>

      {statusQuery.isLoading ? (
        <div className="admin-crawler-grid" aria-hidden="true">
          <Skeleton height="230px" style={{ borderRadius: 12 }} />
          <Skeleton height="230px" style={{ borderRadius: 12 }} />
          <Skeleton height="230px" style={{ borderRadius: 12 }} />
        </div>
      ) : statusQuery.isError ? (
        <ErrorState
          title="Метрики краулера недоступны"
          message={adminErrorMessage(statusQuery.error, 'Не удалось загрузить состояние краулера.')}
          onRetry={() => void statusQuery.refetch()}
        />
      ) : !data ? (
        <p className="admin-crawler-empty">Нет данных о краулере.</p>
      ) : (
        <>
          <div className="admin-crawler-summary">
            <div className="admin-crawler-summary__item">
              <span>Тайтлы в каталоге</span>
              <strong>{formatInt(data.catalog_manga)}</strong>
              <small>{chaptersLabel(data.catalog_chapters)}</small>
            </div>
            <div className="admin-crawler-summary__item">
              <span>Очередь обогащения</span>
              <strong>{formatInt(data.enrichment_pending)}</strong>
              <small>без деталей и глав</small>
            </div>
            <div className="admin-crawler-summary__item">
              <span>Архив глав</span>
              <strong>{formatBytes(archive?.done_bytes)}</strong>
              <small>
                {archive?.cap_bytes ? `${formatBytes(archive.cap_bytes)} лимит · ${archivePercent.toFixed(1).replace('.', ',')}%` : 'лимит не задан'}
              </small>
            </div>
            <div className="admin-crawler-summary__item">
              <span>Кэш изображений</span>
              <strong>{formatBytes(data.image_cache_bytes)}</strong>
              <small>
                {formatInt(data.image_cache_files)}{' '}
                {pluralRu(data.image_cache_files, 'файл', 'файла', 'файлов')}
              </small>
            </div>
          </div>

          {archive ? (
            <div className="admin-crawler-archive">
              <div className="admin-crawler-archive__bar">
                <span style={{ width: `${Math.max(0, Math.min(100, archivePercent))}%` }} />
              </div>
              <div className="admin-crawler-archive__legend">
                <span>Готово: {formatInt(archive.done)}</span>
                <span>В очереди: {formatInt(archive.pending)}</span>
                <span>Ошибки: {formatInt(archive.failed)}</span>
                <span>БД архива: {formatBytes(archive.db_bytes)}</span>
              </div>
            </div>
          ) : null}

          {warnings.length > 0 ? (
            <div className="admin-crawler-alerts" role="status">
              <div className="admin-crawler-alerts__title">
                <Icon name="alert" size={16} />
                <strong>Требует внимания</strong>
              </div>
              <ul>
                {warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            </div>
          ) : (
            <div className="admin-crawler-clear" role="status">
              <Icon name="check" size={16} />
              <span>Критичных проблем не обнаружено.</span>
            </div>
          )}

          {data.sources.length === 0 ? (
            <p className="admin-crawler-empty">Источники ещё не вернули состояние обхода.</p>
          ) : (
            <div className="admin-crawler-grid">
              {data.sources.map((source) => (
                <SourceCard key={source.source} source={source} measuredEta={measuredEta(source)} />
              ))}
            </div>
          )}

          <p className="admin-crawler-updated">
            Снимок: {formatDateTime(data.generated_at)} · ETA рассчитывается по текущей скорости страниц.
          </p>
        </>
      )}
    </section>
  );
}
