import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { adminApi, adminErrorMessage } from '../../api/admin';
import { formatDateTime } from '../../lib/format';
import { toast } from '../../stores/toast';
import { InlineError } from '../ErrorState';
import { Icon } from '../Icon';
import { Skeleton } from '../Skeleton';

export function ProfileReportsPanel() {
  const queryClient = useQueryClient();
  const reportsQuery = useQuery({
    queryKey: ['admin', 'profile-reports', 'open'],
    queryFn: ({ signal }) => adminApi.getProfileReports('open', signal),
  });
  const resolveMutation = useMutation({
    mutationFn: ({ id, status }: { id: string; status: 'resolved' | 'dismissed' }) =>
      adminApi.resolveProfileReport(id, status),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['admin', 'profile-reports'] });
    },
    onError: (error) =>
      toast.error(adminErrorMessage(error, 'Не удалось обработать жалобу на профиль')),
  });

  const reports = reportsQuery.data ?? [];

  return (
    <section className="admin-panel" aria-labelledby="admin-profile-reports-title">
      <div className="admin-panel__head">
        <div>
          <h2 id="admin-profile-reports-title">Модерация профилей</h2>
          <p>
            Жалобы на имена, био и публичные карточки. Аватары не загружаются: используются
            инициалы. После решения жалоба уходит из очереди.
          </p>
        </div>
      </div>

      {reportsQuery.isLoading ? (
        <Skeleton height="120px" />
      ) : reportsQuery.isError ? (
        <InlineError
          message={adminErrorMessage(reportsQuery.error, 'Не удалось загрузить жалобы на профили.')}
          onRetry={() => void reportsQuery.refetch()}
        />
      ) : reports.length === 0 ? (
        <p className="admin-moderation-empty">Открытых жалоб на профили нет.</p>
      ) : (
        <div className="admin-moderation-list">
          {reports.map((report) => (
            <article className="admin-moderation-item" key={report.id}>
              <div className="admin-moderation-item__head">
                <strong>{report.target_display_name}</strong>
                <span>{formatDateTime(report.created_at)}</span>
              </div>
              <p className="admin-moderation-item__reason">
                Профиль:{' '}
                <Link className="admin-moderation-item__manga" to={`/u/${report.target_username}`}>
                  @{report.target_username}
                </Link>
                {' · '}от {report.reporter_username}
              </p>
              <p className="admin-moderation-item__body">{report.reason}</p>
              <div className="admin-moderation-item__actions">
                {report.target_visible ? (
                  <Link className="btn btn--ghost btn--sm" to={`/u/${report.target_username}`}>
                    <Icon name="external" size={14} />
                    Открыть профиль
                  </Link>
                ) : (
                  <span className="badge">Профиль скрыт от гостей</span>
                )}
                <button
                  type="button"
                  className="btn btn--outline btn--sm"
                  disabled={resolveMutation.isPending}
                  onClick={() => resolveMutation.mutate({ id: report.id, status: 'resolved' })}
                >
                  Решено
                </button>
                <button
                  type="button"
                  className="btn btn--ghost btn--sm"
                  disabled={resolveMutation.isPending}
                  onClick={() => resolveMutation.mutate({ id: report.id, status: 'dismissed' })}
                >
                  Отклонить
                </button>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
