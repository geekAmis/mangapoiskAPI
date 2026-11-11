import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import { EmptyState } from '../components/EmptyState';
import { ErrorState } from '../components/ErrorState';
import { Icon } from '../components/Icon';
import { DancingSpinner } from '../components/DancingLoader';
import { Skeleton } from '../components/Skeleton';
import { humanizeError } from '../lib/errors';
import { useDocumentTitle } from '../lib/hooks';
import { pluralRu } from '../lib/format';

const CAPABILITY_LABELS: Array<{ key: string; label: string }> = [
  { key: 'search', label: 'Поиск' },
  { key: 'catalog', label: 'Каталог' },
  { key: 'manga', label: 'Страницы тайтла' },
  { key: 'chapters', label: 'Список глав' },
  { key: 'pages', label: 'Страницы чтения' },
  { key: 'latest', label: 'Обновления' },
];

function languageLabel(code: string): string {
  if (code === 'ru') return 'Русский';
  if (code === 'en') return 'Английский';
  if (code === 'ja') return 'Японский';
  if (code === 'ko') return 'Корейский';
  if (code === 'zh') return 'Китайский';
  return code.toUpperCase();
}

export default function SourcesPage() {
  useDocumentTitle('Источники — MangaPoisk Reborn');
  const sourcesQuery = useQuery({
    queryKey: ['sources'],
    queryFn: ({ signal }) => api.sources(signal),
    staleTime: 60_000,
  });

  const sources = sourcesQuery.data ?? [];
  const enabledCount = sources.filter((source) => source.enabled).length;

  return (
    <div className="page container">
      <div className="page-head">
        <div className="page-head__main">
          <span className="eyebrow">Открытый веб</span>
          <h1 className="page-title">Источники</h1>
          <p className="page-subtitle">
            MangaPoisk Reborn собирает метаданные с публичных страниц и не хранит чужие
            библиотеки изображений. У каждого источника — свой набор возможностей.
          </p>
        </div>
        <div className="page-head__actions">
          <button
            type="button"
            className="btn btn--outline"
            onClick={() => void sourcesQuery.refetch()}
            disabled={sourcesQuery.isFetching}
          >
            {sourcesQuery.isFetching ? (
              <DancingSpinner size={17} />
            ) : (
              <Icon name="refresh" size={17} />
            )}
            Обновить
          </button>
        </div>
      </div>

      {sources.length > 0 ? (
        <p className="sources-intro">
          Сейчас доступно <strong>{enabledCount}</strong> из {sources.length}{' '}
          {pluralRu(sources.length, 'источник', 'источника', 'источников')}. Отключённые адаптеры показаны для
          прозрачности: они не используются парсером, пока оператор не включит их.
        </p>
      ) : null}

      {sourcesQuery.isLoading ? (
        <div className="sources-grid" aria-hidden="true">
          {Array.from({ length: 4 }, (_, index) => (
            <Skeleton key={index} height="260px" />
          ))}
        </div>
      ) : sourcesQuery.isError ? (
        <ErrorState
          title="Источники недоступны"
          message={humanizeError(sourcesQuery.error)}
          onRetry={() => void sourcesQuery.refetch()}
        />
      ) : sources.length === 0 ? (
        <EmptyState
          icon="compass"
          title="Источники не настроены"
          description="Сервер не вернул ни одного адаптера. Проверьте конфигурацию parser и повторите запрос."
          action={
            <button type="button" className="btn btn--primary" onClick={() => void sourcesQuery.refetch()}>
              <Icon name="refresh" size={16} />
              Повторить
            </button>
          }
        />
      ) : (
        <div className="sources-grid">
          {sources.map((source) => (
            <article
              className={`source-card${source.enabled ? '' : ' is-disabled'}`}
              key={source.code}
              aria-labelledby={`source-${source.code}`}
            >
              <div className="source-card__head">
                <span className="source-card__mark" aria-hidden="true">
                  {source.name.slice(0, 1).toUpperCase()}
                </span>
                <div>
                  <h2 className="source-card__name" id={`source-${source.code}`}>
                    {source.name}
                  </h2>
                  <span className="source-card__code">{source.code}</span>
                </div>
                <span
                  className={`badge ${source.enabled ? 'badge--success' : 'badge--danger'} source-card__status`}
                >
                  {source.enabled ? 'Работает' : 'Отключён'}
                </span>
              </div>

              <div className="source-card__head" style={{ gap: 8 }}>
                <span className="capability">
                  <Icon name="link" size={13} />
                  {languageLabel(source.language)}
                </span>
                <a
                  className="source-card__url"
                  href={source.base_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  title={source.base_url}
                >
                  <Icon name="external" size={13} />
                  <span>{source.base_url}</span>
                </a>
              </div>

              <div className="source-card__caps">
                {CAPABILITY_LABELS.map((capability) => {
                  const enabled = Boolean(source.capabilities[capability.key]);
                  return (
                    <span
                      key={capability.key}
                      className={`capability ${enabled ? 'is-yes' : 'is-no'}`}
                      title={enabled ? 'Поддерживается' : 'Не поддерживается'}
                    >
                      <Icon name={enabled ? 'check' : 'close'} size={13} />
                      {capability.label}
                    </span>
                  );
                })}
              </div>

              {source.requires_cookies ? (
                <p className="source-card__cookies">
                  <Icon name="info" size={14} />
                  Для части контента нужны необязательные cookies, которые задаются только в
                  окружении оператора.
                </p>
              ) : null}
            </article>
          ))}
        </div>
      )}

      <section className="legal-note" aria-labelledby="legal-title">
        <span className="legal-note__icon" aria-hidden="true">
          <Icon name="shield" size={20} />
        </span>
        <div>
          <h2 className="legal-note__title" id="legal-title">Как это работает</h2>
          <p>
            Каталог хранит метаданные и ссылки на страницы источников. Изображения загружаются
            через кэширующий прокси по запросу читателя и не распространяются как собственный
            контент. Сервис не обходит CAPTCHA, DRM, платный доступ и другие технические
            ограничения. Права на произведения принадлежат авторам и правообладателям: если
            источник или правообладатель требуют удалить материал, он удаляется из индекса.
          </p>
        </div>
      </section>
    </div>
  );
}
