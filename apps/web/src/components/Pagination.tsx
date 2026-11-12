import { Icon } from './Icon';

interface PaginationProps {
  page: number;
  hasNext: boolean;
  total?: number;
  limit?: number;
  onChange: (page: number) => void;
  disabled?: boolean;
}

export function Pagination({ page, hasNext, total, limit, onChange, disabled = false }: PaginationProps) {
  const totalPages =
    total !== undefined && limit && limit > 0 ? Math.max(1, Math.ceil(total / limit)) : undefined;
  const canGoBack = page > 1;
  const canGoForward = totalPages ? page < totalPages : hasNext;

  if (!canGoBack && !canGoForward) return null;

  return (
    <nav className="pagination" aria-label="Постраничная навигация">
      <button
        type="button"
        className="btn btn--outline pagination__button"
        onClick={() => onChange(page - 1)}
        disabled={!canGoBack || disabled}
        aria-label="Предыдущая страница"
      >
        <Icon name="chevron-left" size={17} />
        <span>Назад</span>
      </button>
      <span className="pagination__status">
        Страница <strong>{page}</strong>
        {totalPages ? <> из {totalPages}</> : null}
      </span>
      <button
        type="button"
        className="btn btn--outline pagination__button"
        onClick={() => onChange(page + 1)}
        disabled={!canGoForward || disabled}
        aria-label="Следующая страница"
      >
        <span>Вперёд</span>
        <Icon name="chevron-right" size={17} />
      </button>
    </nav>
  );
}
