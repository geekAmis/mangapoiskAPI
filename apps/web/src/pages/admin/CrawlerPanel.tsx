import type { AdminCatalogueHealth } from '../../api/admin';
import { CrawlerStatusPanel } from '../../components/admin/CrawlerStatusPanel';
import { InlineError } from '../../components/ErrorState';
import { Icon } from '../../components/Icon';
import { DancingSpinner } from '../../components/DancingLoader';
import { Skeleton } from '../../components/Skeleton';
import { formatDateTime, formatInt } from '../../lib/format';

interface CrawlerPanelProps {
  catalogue: AdminCatalogueHealth | undefined;
  catalogueLoading: boolean;
  catalogueError: unknown;
  catalogueFetching: boolean;
  active: boolean;
  onRetry: () => void;
}

export function CrawlerPanel({
  catalogue,
  catalogueLoading,
  catalogueError,
  catalogueFetching,
  active,
  onRetry,
}: CrawlerPanelProps) {
  return (
    <div className="admin-panel-stack">
      <CrawlerStatusPanel active={active} />

      <section className="admin-panel" aria-labelledby="admin-catalogue-title">
        <div className="admin-panel__head">
          <div>
            <h2 id="admin-catalogue-title">Каталог и обогащение</h2>
            <p>
              Backlog деталей, состояние источников и последний успешный обход.
              Обновляется каждую минуту, пока вкладка открыта.
            </p>
          </div>
          <button
            type="button"
            className="btn btn--ghost btn--icon"
            onClick={onRetry}
            disabled={catalogueFetching}
            aria-label="Обновить состояние каталога"
            title="Обновить состояние каталога"
          >
            {catalogueFetching ? <DancingSpinner size={18} /> : <Icon name="refresh" size={18} />}
          </button>
        </div>

        {catalogueLoading ? (
          <Skeleton height="120px" style={{ borderRadius: 14 }} />
        ) : catalogueError ? (
          <InlineError
            message="Не удалось получить состояние каталога."
            onRetry={onRetry}
          />
        ) : catalogue ? (
          <>
            <div className="admin-stats">
              <div className="admin-stat">
                <span>Тайтлы</span>
                <strong>{formatInt(catalogue.stats.manga)}</strong>
                <small>{formatInt(catalogue.stats.chapters)} глав</small>
              </div>
              <div className="admin-stat">
                <span>Ждут деталей</span>
                <strong>{formatInt(catalogue.enrichment.pending)}</strong>
                <small>{formatInt(catalogue.enrichment.retrying)} на retry</small>
              </div>
              <div className="admin-stat">
                <span>Ошибки</span>
                <strong>{formatInt(catalogue.enrichment.failed)}</strong>
                <small>после 5 попыток</small>
              </div>
              <div className="admin-stat">
                <span>Оценка очереди</span>
                <strong>
                  {catalogue.enrichment.estimated_seconds > 0
                    ? `${Math.ceil(catalogue.enrichment.estimated_seconds / 3600)} ч`
                    : '—'}
                </strong>
                <small>при 36 запросах/мин</small>
              </div>
            </div>

            <div className="admin-catalogue-health">
              {catalogue.enrichment.sources.map((source) => {
                const states =
                  catalogue.crawl_states.filter((state) => state.source === source.source) ?? [];
                const full = states.find((state) => state.mode === 'full');
                const incremental = states.find((state) => state.mode === 'incremental');
                const health = states.find((state) => state.mode === 'health');
                const lastSuccess = health?.last_success_at ?? source.last_success_at;
                return (
                  <div className="admin-catalogue-health__row" key={source.source}>
                    <strong>{source.source}</strong>
                    <span>
                      pending {formatInt(source.pending)} · retry {formatInt(source.retrying)}
                    </span>
                    <span>
                      full: {full?.status ?? '—'}
                      {full?.failure_count ? ` (${full.failure_count})` : ''} · inc:{' '}
                      {incremental?.status ?? '—'}
                    </span>
                    <span>last success: {lastSuccess ? formatDateTime(lastSuccess) : '—'}</span>
                  </div>
                );
              })}
            </div>
            {catalogue.crawl_states.some((state) => state.status === 'blocked') ? (
              <p className="admin-catalogue-health__warning">
                Источник остановлен circuit breaker. Следующая попытка — после указанного
                next_run_at; проверьте cookie/robots/доступность.
              </p>
            ) : null}
          </>
        ) : null}
      </section>
    </div>
  );
}
