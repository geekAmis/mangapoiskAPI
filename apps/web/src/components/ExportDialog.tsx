import { useEffect, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import type { ChapterOut, ExportFormat, ExportJobOut } from '../api/types';
import { humanizeError } from '../lib/errors';
import { chapterHeading, formatInt } from '../lib/format';
import { queryKeys } from '../lib/queryClient';
import { Icon } from './Icon';
import { Modal } from './Modal';

const FORMATS: Array<{ value: ExportFormat; name: string; description: string }> = [
  { value: 'cbz', name: 'CBZ', description: 'Архив для читалок и планшетов' },
  { value: 'pdf', name: 'PDF', description: 'Универсальный документ' },
  { value: 'html', name: 'HTML', description: 'Офлайн-страница в браузере' },
];

const STATUS_LABELS: Record<string, string> = {
  queued: 'В очереди',
  running: 'Собираем архив',
  done: 'Готово',
  failed: 'Ошибка',
};

interface ExportDialogProps {
  open: boolean;
  onClose: () => void;
  chapter: ChapterOut | null;
}

export function ExportDialog({ open, onClose, chapter }: ExportDialogProps) {
  const [format, setFormat] = useState<ExportFormat>('cbz');
  const [jobId, setJobId] = useState<string | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!open) return;
    setFormat('cbz');
    setJobId(null);
    setError('');
  }, [open, chapter?.id]);

  const createMutation = useMutation({
    mutationFn: () => {
      if (!chapter) throw new Error('Не выбрана глава');
      return api.createExport(chapter.id, format);
    },
    onSuccess: (job: ExportJobOut) => {
      setError('');
      setJobId(job.id);
    },
    onError: (mutationError: unknown) => {
      setError(humanizeError(mutationError, 'Не удалось запустить экспорт. Попробуйте другую главу.'));
    },
  });

  const jobQuery = useQuery({
    queryKey: queryKeys.exportJob(jobId ?? 'none'),
    queryFn: ({ signal }) => api.getExport(jobId ?? '', signal),
    enabled: open && Boolean(jobId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === 'done' || status === 'failed' ? false : 1500;
    },
  });

  const job = jobQuery.data;
  const status = job?.status;
  const progressPercent =
    job && job.total > 0 ? Math.min(100, Math.round((job.progress / job.total) * 100)) : job?.status === 'done' ? 100 : 12;

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Экспорт главы"
      description="Соберите главу в один файл для чтения без интернета. Готовый архив можно скачать."
      size="md"
    >
      {chapter ? (
        <div className="export-chapter">
          <Icon name="book" size={18} />
          <span>{chapterHeading(chapter)}</span>
          <span className="muted">· {chapter.page_count ? formatInt(chapter.page_count) + ' стр.' : 'страницы уточняются'}</span>
        </div>
      ) : null}

      {error ? (
        <div className="form-alert" role="alert" style={{ marginBottom: 14 }}>
          <Icon name="alert" size={17} />
          <span>{error}</span>
        </div>
      ) : null}

      {!jobId ? (
        <>
          <div className="export-formats" role="radiogroup" aria-label="Формат экспорта">
            {FORMATS.map((option) => (
              <button
                key={option.value}
                type="button"
                className={`export-format${format === option.value ? ' is-active' : ''}`}
                role="radio"
                aria-checked={format === option.value}
                onClick={() => setFormat(option.value)}
              >
                <span className="export-format__name">{option.name}</span>
                <span className="export-format__desc">{option.description}</span>
              </button>
            ))}
          </div>
          <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 18 }}>
            <button
              type="button"
              className="btn btn--primary"
              onClick={() => createMutation.mutate()}
              disabled={!chapter || createMutation.isPending}
              data-autofocus
            >
              {createMutation.isPending ? (
                <>
                  <Icon name="loader" size={16} className="spin" />
                  Запускаем…
                </>
              ) : (
                <>
                  <Icon name="download" size={16} />
                  Собрать {format.toUpperCase()}
                </>
              )}
            </button>
          </div>
        </>
      ) : (
        <div className="export-status">
          <div className="export-status__line">
            <span>Статус</span>
            <strong>{STATUS_LABELS[status ?? 'queued'] ?? 'Обработка'}</strong>
          </div>
          <div className="progress progress--lg">
            <div className="progress__bar" style={{ width: `${progressPercent}%` }} />
          </div>
          <div className="export-status__line">
            <span>
              {job ? `${formatInt(job.progress)} из ${formatInt(job.total)} страниц` : 'Подготавливаем страницы…'}
            </span>
            <span>{progressPercent}%</span>
          </div>
          {status === 'done' && job ? (
            <div className="export-done">
              <Icon name="check" size={18} />
              <span>Файл готов</span>
              <a
                className="btn btn--primary btn--sm"
                href={api.exportDownloadUrl(job)}
                style={{ marginLeft: 'auto' }}
                download
              >
                <Icon name="download" size={15} />
                Скачать
              </a>
            </div>
          ) : status === 'failed' ? (
            <div className="form-alert" role="alert" style={{ marginTop: 4 }}>
              <Icon name="alert" size={17} />
              <span>{job?.error || 'Экспорт не удался. Попробуйте ещё раз.'}</span>
            </div>
          ) : (
            <p className="field__hint" style={{ marginTop: 2 }}>
              Сборка выполняется на сервере. Дождитесь завершения, чтобы скачать готовый файл.
            </p>
          )}
          {status === 'failed' || jobQuery.isError ? (
            <button
              type="button"
              className="btn btn--outline btn--sm"
              style={{ justifySelf: 'start' }}
              onClick={() => {
                setJobId(null);
                setError('');
              }}
            >
              <Icon name="refresh" size={15} />
              Попробовать снова
            </button>
          ) : null}
        </div>
      )}
    </Modal>
  );
}
