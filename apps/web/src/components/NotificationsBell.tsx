import { useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { commentsApi, type CommentNotification } from '../api/comments';
import { notificationsApi } from '../api/notifications';
import { humanizeError } from '../lib/errors';
import { formatRelative, initials } from '../lib/format';
import { useOnClickOutside } from '../lib/hooks';
import { toast } from '../stores/toast';
import { Icon } from './Icon';

function notificationText(item: CommentNotification): string {
  if (item.type === 'reply') return 'ответил(а) на ваш комментарий';
  if (item.type === 'like') return 'оценил(а) ваш комментарий';
  if (item.type === 'moderation') return 'ваш комментарий скрыт модератором';
  return 'новое уведомление';
}

export function NotificationsBell() {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  useOnClickOutside(rootRef, () => setOpen(false), open);

  const notificationsQuery = useQuery({
    queryKey: ['notifications'],
    queryFn: () => commentsApi.notifications(1, 15),
    refetchInterval: 60_000,
    staleTime: 20_000,
  });

  const readMutation = useMutation({
    mutationFn: (ids: string[]) => commentsApi.markNotificationsRead(ids),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['notifications'] });
    },
    onError: (error) => toast.error(humanizeError(error, 'Не удалось обновить уведомления')),
  });

  const unfollowMutation = useMutation({
    mutationFn: (mangaId: string) => notificationsApi.unfollow(mangaId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['notifications'] });
      void queryClient.invalidateQueries({ queryKey: ['follow'] });
      toast.info('Вы отписались от новых глав');
    },
    onError: (error) => toast.error(humanizeError(error, 'Не удалось отписаться')),
  });

  const data = notificationsQuery.data;
  const unread = data?.unread_count ?? 0;
  const items = data?.items ?? [];

  const markAll = () => {
    const ids = items.filter((item) => !item.read_at).map((item) => item.id);
    if (ids.length > 0) readMutation.mutate(ids);
  };

  const openItem = (item: CommentNotification) => {
    if (!item.read_at) readMutation.mutate([item.id]);
    if (item.type === 'chapter' && item.chapter) {
      setOpen(false);
      navigate(item.chapter.url || `/manga/${item.chapter.manga_id}`);
      return;
    }
    if (item.comment) {
      setOpen(false);
      navigate(`/manga/${item.comment.manga_id}#comments`);
    }
  };

  const unsubscribe = (item: CommentNotification) => {
    if (!item.chapter) return;
    unfollowMutation.mutate(item.chapter.manga_id);
  };

  return (
    <div className="notifications" ref={rootRef}>
      <button
        type="button"
        className="btn btn--ghost btn--icon notifications__toggle"
        onClick={() => setOpen((value) => !value)}
        aria-label={unread > 0 ? `Уведомления, ${unread} новых` : 'Уведомления'}
        aria-expanded={open}
        aria-haspopup="dialog"
      >
        <Icon name="bell" size={20} />
        {unread > 0 ? (
          <span className="notifications__badge" aria-hidden="true">
            {unread > 99 ? '99+' : unread}
          </span>
        ) : null}
      </button>

      {open ? (
        <div className="notifications__popover" role="dialog" aria-label="Уведомления">
          <div className="notifications__head">
            <strong>Уведомления</strong>
            {unread > 0 ? (
              <button
                type="button"
                className="notifications__read-all"
                onClick={markAll}
                disabled={readMutation.isPending}
              >
                Прочитать все
              </button>
            ) : null}
          </div>

          {notificationsQuery.isLoading ? (
            <div className="notifications__empty">Загружаем…</div>
          ) : notificationsQuery.isError ? (
            <div className="notifications__empty">
              {humanizeError(notificationsQuery.error, 'Не удалось загрузить уведомления')}
            </div>
          ) : items.length === 0 ? (
            <div className="notifications__empty">
              Пока тихо. Здесь появятся ответы, лайки и новые главы.
            </div>
          ) : (
            <div className="notifications__list">
              {items.map((item) =>
                item.type === 'chapter' && item.chapter ? (
                  <div
                    key={item.id}
                    className={`notifications__item notifications__item--chapter${item.read_at ? '' : ' is-unread'}`}
                  >
                    <button
                      type="button"
                      className="notifications__main"
                      onClick={() => openItem(item)}
                    >
                      <span
                        className="notifications__avatar notifications__avatar--chapter"
                        aria-hidden="true"
                      >
                        <Icon name="book" size={15} />
                      </span>
                      <span className="notifications__body">
                        <span className="notifications__line">
                          <strong>{item.chapter.manga_title}</strong>{' '}
                          {item.chapter.chapter_label}
                        </span>
                        <span className="notifications__excerpt">Новая глава тайтла</span>
                        <span className="notifications__time">
                          {formatRelative(item.created_at)}
                        </span>
                      </span>
                      {!item.read_at ? (
                        <span className="notifications__dot" aria-hidden="true" />
                      ) : null}
                    </button>
                    <button
                      type="button"
                      className="notifications__unsub"
                      onClick={() => unsubscribe(item)}
                      disabled={unfollowMutation.isPending}
                      title="Отписаться от новых глав этого тайтла"
                      aria-label={`Отписаться от ${item.chapter.manga_title}`}
                    >
                      <Icon name="bell-off" size={15} />
                    </button>
                  </div>
                ) : (
                  <button
                    type="button"
                    key={item.id}
                    className={`notifications__item${item.read_at ? '' : ' is-unread'}`}
                    onClick={() => openItem(item)}
                  >
                    <span className="notifications__avatar" aria-hidden="true">
                      {initials(item.comment?.user_name ?? '?') || '?'}
                    </span>
                    <span className="notifications__body">
                      <span className="notifications__line">
                        <strong>{item.comment?.user_name ?? 'Читатель'}</strong>{' '}
                        {notificationText(item)}
                      </span>
                      {item.comment ? (
                        <span className="notifications__excerpt">{item.comment.body}</span>
                      ) : null}
                      <span className="notifications__time">
                        {formatRelative(item.created_at)}
                      </span>
                    </span>
                    {!item.read_at ? (
                      <span className="notifications__dot" aria-hidden="true" />
                    ) : null}
                  </button>
                ),
              )}
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}
