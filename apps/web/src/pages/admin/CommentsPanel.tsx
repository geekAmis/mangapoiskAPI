import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  adminApi,
  adminErrorMessage,
  type AdminCommentReport,
} from '../../api/admin';
import { InlineError } from '../../components/ErrorState';
import { Skeleton } from '../../components/Skeleton';
import { formatDateTime } from '../../lib/format';
import { toast } from '../../stores/toast';

export function CommentsPanel() {
  const queryClient = useQueryClient();
  const reportsQuery = useQuery({
    queryKey: ['admin', 'comment-reports', 'open'],
    queryFn: ({ signal }) => adminApi.getCommentReports('open', signal),
  });
  const commentsQuery = useQuery({
    queryKey: ['admin', 'reported-comments'],
    queryFn: ({ signal }) => adminApi.getReportedComments(signal),
  });
  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['admin', 'comment-reports'] });
    void queryClient.invalidateQueries({ queryKey: ['admin', 'reported-comments'] });
  };
  const resolveMutation = useMutation({
    mutationFn: ({ id, status }: { id: string; status: 'resolved' | 'dismissed' }) =>
      adminApi.resolveCommentReport(id, status),
    onSuccess: invalidate,
    onError: (error) => toast.error(adminErrorMessage(error, 'Не удалось обработать жалобу')),
  });
  const moderateMutation = useMutation({
    mutationFn: ({ id, action }: { id: string; action: 'hide' | 'restore' }) =>
      adminApi.moderateComment(id, action),
    onSuccess: invalidate,
    onError: (error) => toast.error(adminErrorMessage(error, 'Не удалось изменить комментарий')),
  });

  const reports: AdminCommentReport[] = reportsQuery.data?.items ?? [];
  const comments = commentsQuery.data?.items ?? [];

  return (
    <section className="admin-panel" aria-labelledby="admin-moderation-title">
      <div className="admin-panel__head">
        <div>
          <h2 id="admin-moderation-title">Модерация комментариев</h2>
          <p>
            Жалобы читателей и комментарии, на которые пожаловались. Скрытие убирает
            текст из публичных обсуждений.
          </p>
        </div>
      </div>

      <div className="admin-moderation-grid">
        <div className="admin-moderation-column">
          <h3>Открытые жалобы</h3>
          {reportsQuery.isLoading ? (
            <Skeleton height="120px" />
          ) : reportsQuery.isError ? (
            <InlineError
              message={adminErrorMessage(reportsQuery.error, 'Не удалось загрузить жалобы.')}
              onRetry={() => void reportsQuery.refetch()}
            />
          ) : reports.length === 0 ? (
            <p className="admin-moderation-empty">Открытых жалоб нет.</p>
          ) : (
            <div className="admin-moderation-list">
              {reports.map((report) => (
                <article className="admin-moderation-item" key={report.id}>
                  <div className="admin-moderation-item__head">
                    <strong>{report.comment?.user_name ?? 'Комментарий удалён'}</strong>
                    <span>{formatDateTime(report.created_at)}</span>
                  </div>
                  {report.comment ? (
                    <Link
                      className="admin-moderation-item__manga"
                      to={`/manga/${report.comment.manga_id}#comments`}
                    >
                      {report.comment.body}
                    </Link>
                  ) : null}
                  <p className="admin-moderation-item__reason">Причина: {report.reason}</p>
                  <div className="admin-moderation-item__actions">
                    {report.comment ? (
                      <button
                        type="button"
                        className="btn btn--outline btn--sm"
                        disabled={moderateMutation.isPending}
                        onClick={() =>
                          moderateMutation.mutate({
                            id: report.comment!.id,
                            action: report.comment!.status === 'hidden' ? 'restore' : 'hide',
                          })
                        }
                      >
                        {report.comment.status === 'hidden' ? 'Восстановить' : 'Скрыть'}
                      </button>
                    ) : null}
                    <button
                      type="button"
                      className="btn btn--ghost btn--sm"
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
        </div>

        <div className="admin-moderation-column">
          <h3>Комментарии с жалобами</h3>
          {commentsQuery.isLoading ? (
            <Skeleton height="120px" />
          ) : commentsQuery.isError ? (
            <InlineError
              message={adminErrorMessage(commentsQuery.error, 'Не удалось загрузить комментарии.')}
              onRetry={() => void commentsQuery.refetch()}
            />
          ) : comments.length === 0 ? (
            <p className="admin-moderation-empty">Нет комментариев с жалобами.</p>
          ) : (
            <div className="admin-moderation-list">
              {comments.map((comment) => (
                <article className="admin-moderation-item" key={comment.id}>
                  <div className="admin-moderation-item__head">
                    <strong>{comment.user_name}</strong>
                    <span>
                      {comment.report_count} жалоб · {comment.status}
                    </span>
                  </div>
                  <p className="admin-moderation-item__body">{comment.body}</p>
                  <div className="admin-moderation-item__actions">
                    <Link className="btn btn--ghost btn--sm" to={`/manga/${comment.manga_id}#comments`}>
                      Открыть тайтл
                    </Link>
                    <button
                      type="button"
                      className="btn btn--outline btn--sm"
                      disabled={moderateMutation.isPending}
                      onClick={() =>
                        moderateMutation.mutate({
                          id: comment.id,
                          action: comment.status === 'hidden' ? 'restore' : 'hide',
                        })
                      }
                    >
                      {comment.status === 'hidden' ? 'Восстановить' : 'Скрыть'}
                    </button>
                  </div>
                </article>
              ))}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
