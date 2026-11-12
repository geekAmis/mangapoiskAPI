import { useState, type FormEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { commentsApi, type CommentOut } from '../api/comments';
import { formatRelative, initials } from '../lib/format';
import { humanizeError } from '../lib/errors';
import { useAuthStore } from '../stores/auth';
import { toast } from '../stores/toast';
import { Icon } from './Icon';
import { Modal } from './Modal';
import '../styles/comments.css';

type Sort = 'new' | 'top';

function Avatar({ name }: { name: string }) {
  return (
    <span className="comment-avatar" aria-hidden="true">
      {initials(name) || '?'}
    </span>
  );
}

function CommentBody({ comment }: { comment: CommentOut }) {
  const [revealed, setRevealed] = useState(!comment.spoiler);
  if (comment.spoiler && !revealed) {
    return (
      <button type="button" className="comment-spoiler" onClick={() => setRevealed(true)}>
        <Icon name="eye" size={14} />
        Показать спойлер
      </button>
    );
  }
  return <p className="comment-text">{comment.body}</p>;
}

interface CommentItemProps {
  comment: CommentOut;
  mangaId: string;
  depth?: number;
  onReply: (comment: CommentOut) => void;
  onEdit: (comment: CommentOut) => void;
  onReport: (comment: CommentOut) => void;
  onDelete: (comment: CommentOut) => void;
  replyToId: string | null;
  editingId: string | null;
}

function CommentItem({
  comment,
  mangaId,
  depth = 0,
  onReply,
  onEdit,
  onReport,
  onDelete,
  replyToId,
  editingId,
}: CommentItemProps) {
  const queryClient = useQueryClient();
  const [replyBody, setReplyBody] = useState('');
  const [editBody, setEditBody] = useState(comment.body);
  const [editSpoiler, setEditSpoiler] = useState(comment.spoiler);
  const [busy, setBusy] = useState(false);

  const like = useMutation({
    mutationFn: () => commentsApi.like(comment.id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['comments', mangaId] });
    },
    onError: (error) => toast.error(humanizeError(error, 'Не удалось поставить лайк')),
  });

  const createReply = async (event: FormEvent) => {
    event.preventDefault();
    if (!replyBody.trim()) return;
    setBusy(true);
    try {
      await commentsApi.create(mangaId, replyBody.trim(), false, comment.id);
      setReplyBody('');
      await queryClient.invalidateQueries({ queryKey: ['comments', mangaId] });
      toast.success('Ответ отправлен');
    } catch (error) {
      toast.error(humanizeError(error, 'Не удалось отправить ответ'));
    } finally {
      setBusy(false);
    }
  };

  const saveEdit = async () => {
    if (!editBody.trim()) return;
    setBusy(true);
    try {
      await commentsApi.update(comment.id, editBody.trim(), editSpoiler);
      await queryClient.invalidateQueries({ queryKey: ['comments', mangaId] });
      onEdit(comment);
      toast.success('Комментарий обновлён');
    } catch (error) {
      toast.error(humanizeError(error, 'Не удалось изменить комментарий'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <article className={`comment${depth ? ' comment--reply' : ''}`}>
      <Avatar name={comment.user_name} />
      <div className="comment__main">
        <header className="comment__head">
          <strong>{comment.is_own ? 'Вы' : comment.user_name}</strong>
          <span>{formatRelative(comment.created_at)}</span>
          {comment.edited_at ? <span className="comment__edited">изменён</span> : null}
        </header>

        {editingId === comment.id ? (
          <div className="comment-editor">
            <textarea
              className="textarea"
              value={editBody}
              onChange={(event) => setEditBody(event.target.value)}
              maxLength={2000}
              rows={3}
            />
            <div className="comment-editor__actions">
              <label className="comment-check">
                <input
                  type="checkbox"
                  checked={editSpoiler}
                  onChange={(event) => setEditSpoiler(event.target.checked)}
                />
                Спойлер
              </label>
              <button type="button" className="btn btn--primary btn--sm" onClick={() => void saveEdit()} disabled={busy}>
                Сохранить
              </button>
              <button type="button" className="btn btn--ghost btn--sm" onClick={() => onEdit(comment)} disabled={busy}>
                Отмена
              </button>
            </div>
          </div>
        ) : (
          <CommentBody comment={comment} />
        )}

        <div className="comment__actions">
          <button
            type="button"
            className={`comment-action${comment.liked_by_me ? ' is-active' : ''}`}
            onClick={() => like.mutate()}
            disabled={like.isPending}
            aria-pressed={comment.liked_by_me}
          >
            <Icon name="heart" size={14} />
            {comment.likes_count > 0 ? comment.likes_count : 'Нравится'}
          </button>
          {!depth ? (
            <button type="button" className="comment-action" onClick={() => onReply(comment)}>
              <Icon name="message" size={14} />
              Ответить
            </button>
          ) : null}
          {comment.can_edit ? (
            <button type="button" className="comment-action" onClick={() => onEdit(comment)}>
              Изменить
            </button>
          ) : null}
          {comment.can_delete ? (
            <button type="button" className="comment-action comment-action--danger" onClick={() => onDelete(comment)}>
              Удалить
            </button>
          ) : null}
          {!comment.is_own ? (
            <button type="button" className="comment-action" onClick={() => onReport(comment)}>
              Жалоба
            </button>
          ) : null}
        </div>

        {replyToId === comment.id ? (
          <form className="comment-reply" onSubmit={(event) => void createReply(event)}>
            <textarea
              className="textarea"
              value={replyBody}
              onChange={(event) => setReplyBody(event.target.value)}
              placeholder="Ваш ответ…"
              maxLength={2000}
              rows={2}
              autoFocus
            />
            <div className="comment-editor__actions">
              <button type="submit" className="btn btn--primary btn--sm" disabled={busy || !replyBody.trim()}>
                Отправить
              </button>
              <button type="button" className="btn btn--ghost btn--sm" onClick={() => onReply(comment)}>
                Отмена
              </button>
            </div>
          </form>
        ) : null}

        {comment.replies && comment.replies.length > 0 ? (
          <div className="comment__replies">
            {comment.replies.map((reply) => (
              <CommentItem
                key={reply.id}
                comment={reply}
                mangaId={mangaId}
                depth={1}
                onReply={onReply}
                onEdit={onEdit}
                onReport={onReport}
                onDelete={onDelete}
                replyToId={replyToId}
                editingId={editingId}
              />
            ))}
            {comment.replies_count > comment.replies.length ? (
              <p className="comment__more">
                Ещё {comment.replies_count - comment.replies.length} ответов
              </p>
            ) : null}
          </div>
        ) : null}
      </div>
    </article>
  );
}

export function CommentsSection({ mangaId }: { mangaId: string }) {
  const queryClient = useQueryClient();
  const user = useAuthStore((state) => state.user);
  const [sort, setSort] = useState<Sort>('new');
  const [page, setPage] = useState(1);
  const [body, setBody] = useState('');
  const [spoiler, setSpoiler] = useState(false);
  const [replyToId, setReplyToId] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [reportTarget, setReportTarget] = useState<CommentOut | null>(null);
  const [reportReason, setReportReason] = useState('');
  const [reportBusy, setReportBusy] = useState(false);

  const commentsQuery = useQuery({
    queryKey: ['comments', mangaId, sort, page],
    queryFn: () => commentsApi.list(mangaId, page, sort),
  });

  const createMutation = useMutation({
    mutationFn: () => commentsApi.create(mangaId, body.trim(), spoiler),
    onSuccess: () => {
      setBody('');
      setSpoiler(false);
      void queryClient.invalidateQueries({ queryKey: ['comments', mangaId] });
      toast.success('Комментарий опубликован');
    },
    onError: (error) => toast.error(humanizeError(error, 'Не удалось отправить комментарий')),
  });

  const sendReport = async () => {
    if (!reportTarget || !reportReason.trim()) return;
    setReportBusy(true);
    try {
      await commentsApi.report(reportTarget.id, reportReason.trim());
      toast.success('Жалоба отправлена модератору');
      setReportTarget(null);
      setReportReason('');
    } catch (error) {
      toast.error(humanizeError(error, 'Не удалось отправить жалобу'));
    } finally {
      setReportBusy(false);
    }
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!body.trim()) return;
    createMutation.mutate();
  };

  const data = commentsQuery.data;
  const comments = data?.items ?? [];

  return (
    <section className="comments-section" id="comments" aria-labelledby="comments-title">
      <div className="comments-head">
        <h2 id="comments-title">
          Комментарии {data ? <span className="comments-count">{data.total}</span> : null}
        </h2>
        <div className="comments-sort" role="group" aria-label="Сортировка комментариев">
          <button
            type="button"
            className={`chip${sort === 'new' ? ' is-active' : ''}`}
            onClick={() => {
              setSort('new');
              setPage(1);
            }}
          >
            Новые
          </button>
          <button
            type="button"
            className={`chip${sort === 'top' ? ' is-active' : ''}`}
            onClick={() => {
              setSort('top');
              setPage(1);
            }}
          >
            Лучшие
          </button>
        </div>
      </div>

      {user ? (
        <form className="comment-form" onSubmit={submit}>
          <textarea
            className="textarea"
            value={body}
            onChange={(event) => setBody(event.target.value)}
            placeholder="Поделитесь мнением о тайтле…"
            maxLength={2000}
            rows={3}
          />
          <div className="comment-form__foot">
            <label className="comment-check">
              <input type="checkbox" checked={spoiler} onChange={(event) => setSpoiler(event.target.checked)} />
              Спойлер
            </label>
            <span className="comment-form__hint">{body.length} / 2000</span>
            <button type="submit" className="btn btn--primary btn--sm" disabled={!body.trim() || createMutation.isPending}>
              <Icon name="send" size={15} />
              Отправить
            </button>
          </div>
        </form>
      ) : (
        <div className="comment-login">
          <span>Войдите, чтобы оставить комментарий и отвечать другим.</span>
          <Link to="/login" className="btn btn--outline btn--sm">
            Войти
          </Link>
        </div>
      )}

      {commentsQuery.isLoading ? (
        <div className="comment-list" aria-hidden="true">
          {Array.from({ length: 3 }, (_, index) => (
            <div className="comment comment--skeleton" key={index}>
              <span className="comment-avatar" />
              <div>
                <span className="skeleton-line" style={{ width: '32%' }} />
                <span className="skeleton-line" style={{ width: '88%', marginTop: 10 }} />
              </div>
            </div>
          ))}
        </div>
      ) : commentsQuery.isError ? (
        <div className="comment-empty">
          <Icon name="alert" size={18} />
          <span>{humanizeError(commentsQuery.error, 'Не удалось загрузить комментарии.')}</span>
          <button type="button" className="btn btn--outline btn--sm" onClick={() => void commentsQuery.refetch()}>
            Повторить
          </button>
        </div>
      ) : comments.length > 0 ? (
        <>
          <div className="comment-list">
            {comments.map((comment) => (
              <CommentItem
                key={comment.id}
                comment={comment}
                mangaId={mangaId}
                onReply={(item) =>
                  setReplyToId((current) => (current === item.id ? null : item.id))
                }
                onEdit={(item) => {
                  setEditingId((current) => (current === item.id ? null : item.id));
                  setReplyToId(null);
                }}
                onReport={setReportTarget}
                onDelete={async (item) => {
                  if (!window.confirm('Удалить этот комментарий?')) return;
                  try {
                    await commentsApi.remove(item.id);
                    await queryClient.invalidateQueries({ queryKey: ['comments', mangaId] });
                    toast.success('Комментарий удалён');
                  } catch (error) {
                    toast.error(humanizeError(error, 'Не удалось удалить комментарий'));
                  }
                }}
                replyToId={replyToId}
                editingId={editingId}
              />
            ))}
          </div>
          {data && (data.has_next || page > 1) ? (
            <div className="comments-pager">
              <button
                type="button"
                className="btn btn--ghost btn--sm"
                disabled={page <= 1}
                onClick={() => setPage((value) => Math.max(1, value - 1))}
              >
                Назад
              </button>
              <span>
                {page} / {Math.max(1, Math.ceil(data.total / data.limit))}
              </span>
              <button
                type="button"
                className="btn btn--outline btn--sm"
                disabled={!data.has_next}
                onClick={() => setPage((value) => value + 1)}
              >
                Дальше
              </button>
            </div>
          ) : null}
        </>
      ) : (
        <div className="comment-empty">
          <Icon name="message" size={20} />
          <span>Пока нет комментариев. Будьте первым.</span>
        </div>
      )}

      <Modal
        open={Boolean(reportTarget)}
        onClose={() => {
          setReportTarget(null);
          setReportReason('');
        }}
        title="Пожаловаться на комментарий"
        size="sm"
        footer={
          <>
            <button type="button" className="btn btn--ghost" onClick={() => setReportTarget(null)}>
              Отмена
            </button>
            <button
              type="button"
              className="btn btn--danger"
              onClick={() => void sendReport()}
              disabled={reportBusy || reportReason.trim().length < 3}
            >
              Отправить жалобу
            </button>
          </>
        }
      >
        <textarea
          className="textarea"
          value={reportReason}
          onChange={(event) => setReportReason(event.target.value)}
          placeholder="Почему этот комментарий нарушает правила? (3–500 символов)"
          maxLength={500}
          rows={4}
          autoFocus
        />
      </Modal>
    </section>
  );
}
