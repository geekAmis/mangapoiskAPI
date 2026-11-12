import { useId, useMemo, useState, type FormEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  adminApi,
  adminErrorMessage,
  type AdminCollectionInput,
} from '../../api/admin';
import { api } from '../../api/client';
import type {
  CollectionKind,
  CollectionOut,
  CollectionRule,
} from '../../api/types';
import { EmptyState } from '../EmptyState';
import { ErrorState } from '../ErrorState';
import { Icon } from '../Icon';
import { DancingSpinner } from '../DancingLoader';
import { Modal } from '../Modal';
import { Skeleton } from '../Skeleton';
import { formatDateTime, formatInt } from '../../lib/format';
import { toast } from '../../stores/toast';

const RULE_LABELS: Record<CollectionRule, string> = {
  weekly_best: 'Лучшее за неделю',
  beginners: 'Для новичков',
  completed: 'Завершённые',
  short: 'Короткие (до 30 глав)',
  new: 'Новые',
};

const AUDIT_LABELS: Record<string, string> = {
  'collection.created': 'Создана подборка',
  'collection.updated': 'Изменена подборка',
  'collection.deleted': 'Удалена подборка',
  'collection.item_added': 'Добавлен тайтл',
  'collection.item_removed': 'Удалён тайтл',
  'collection.reordered': 'Изменён порядок',
};

interface CollectionDraft {
  title: string;
  slug: string;
  description: string;
  kind: CollectionKind;
  rule: CollectionRule;
  enabled: boolean;
  position: string;
  limit: string;
}

function emptyDraft(): CollectionDraft {
  return {
    title: '',
    slug: '',
    description: '',
    kind: 'manual',
    rule: 'weekly_best',
    enabled: true,
    position: '100',
    limit: '12',
  };
}

function draftFrom(collection: CollectionOut): CollectionDraft {
  return {
    title: collection.title,
    slug: collection.slug,
    description: collection.description,
    kind: collection.kind,
    rule: (collection.rule as CollectionRule | null) ?? 'weekly_best',
    enabled: collection.enabled,
    position: String(collection.position),
    limit: String(collection.limit),
  };
}

export function CollectionsPanel() {
  const queryClient = useQueryClient();
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<CollectionOut | null>(null);
  const [draft, setDraft] = useState<CollectionDraft>(emptyDraft);
  const [managingId, setManagingId] = useState<string | null>(null);
  const [search, setSearch] = useState('');

  const collectionsQuery = useQuery({
    queryKey: ['admin', 'collections'],
    queryFn: ({ signal }) => adminApi.listCollections(signal),
  });
  const auditQuery = useQuery({
    queryKey: ['admin', 'collections', 'audit'],
    queryFn: ({ signal }) => adminApi.getCollectionAudit(40, signal),
  });
  const metricsQuery = useQuery({
    queryKey: ['admin', 'analytics', 'surfaces'],
    queryFn: ({ signal }) => adminApi.getSurfaceMetrics(30, signal),
  });

  const collections = collectionsQuery.data?.items ?? [];
  const current = useMemo(
    () => collections.find((item) => item.id === managingId) ?? null,
    [collections, managingId],
  );

  const searchQuery = useQuery({
    queryKey: ['admin', 'collections', 'search', search],
    queryFn: ({ signal }) => api.listManga({ query: search.trim(), limit: 8 }, signal),
    enabled: search.trim().length >= 2,
    staleTime: 60_000,
  });

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['admin', 'collections'] });
    void queryClient.invalidateQueries({ queryKey: ['admin', 'collections', 'audit'] });
    void queryClient.invalidateQueries({ queryKey: ['collections'] });
  };

  const saveMutation = useMutation({
    mutationFn: async (values: { draft: CollectionDraft; collection: CollectionOut | null }) => {
      const payload: AdminCollectionInput = {
        title: values.draft.title.trim(),
        description: values.draft.description.trim(),
        kind: values.draft.kind,
        rule: values.draft.kind === 'smart' ? values.draft.rule : null,
        enabled: values.draft.enabled,
        position: Number(values.draft.position) || 100,
        limit: Number(values.draft.limit) || 12,
      };
      if (values.draft.slug.trim()) payload.slug = values.draft.slug.trim();
      if (values.collection) {
        return adminApi.updateCollection(values.collection.id, payload);
      }
      return adminApi.createCollection(payload);
    },
    onSuccess: (collection) => {
      setFormOpen(false);
      setEditing(null);
      invalidate();
      toast.success(`Подборка «${collection.title}» сохранена`);
    },
    onError: (error) => toast.error(adminErrorMessage(error, 'Не удалось сохранить подборку')),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => adminApi.deleteCollection(id),
    onSuccess: () => {
      setManagingId(null);
      invalidate();
      toast.success('Подборка удалена');
    },
    onError: (error) => toast.error(adminErrorMessage(error, 'Не удалось удалить подборку')),
  });

  const addMutation = useMutation({
    mutationFn: (values: { id: string; mangaId: string }) =>
      adminApi.addCollectionItem(values.id, values.mangaId),
    onSuccess: () => {
      setSearch('');
      invalidate();
      toast.success('Тайтл добавлен в подборку');
    },
    onError: (error) => toast.error(adminErrorMessage(error, 'Не удалось добавить тайтл')),
  });

  const removeMutation = useMutation({
    mutationFn: (values: { id: string; mangaId: string }) =>
      adminApi.removeCollectionItem(values.id, values.mangaId),
    onSuccess: () => {
      invalidate();
      toast.success('Тайтл убран из подборки');
    },
    onError: (error) => toast.error(adminErrorMessage(error, 'Не удалось убрать тайтл')),
  });

  const reorderMutation = useMutation({
    mutationFn: (values: { id: string; mangaIds: string[] }) =>
      adminApi.reorderCollection(values.id, values.mangaIds),
    onSuccess: () => {
      invalidate();
      toast.success('Порядок сохранён');
    },
    onError: (error) => toast.error(adminErrorMessage(error, 'Не удалось изменить порядок')),
  });

  const openCreate = () => {
    setEditing(null);
    setDraft(emptyDraft());
    setFormOpen(true);
  };

  const openEdit = (collection: CollectionOut) => {
    setEditing(collection);
    setDraft(draftFrom(collection));
    setFormOpen(true);
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!draft.title.trim()) {
      toast.error('Укажите название подборки');
      return;
    }
    saveMutation.mutate({ draft, collection: editing });
  };

  const moveItem = (collection: CollectionOut, index: number, delta: number) => {
    const target = index + delta;
    if (target < 0 || target >= collection.items.length) return;
    const ids = collection.items.map((item) => item.id);
    [ids[index], ids[target]] = [ids[target], ids[index]];
    reorderMutation.mutate({ id: collection.id, mangaIds: ids });
  };

  const titleId = useId();

  return (
    <section className="admin-panel" aria-labelledby={titleId}>
      <div className="admin-panel__head">
        <div>
          <h2 id={titleId}>Подборки</h2>
          <p>
            Публичные разделы главной и страницы <code>/collections/…</code>. Умные подборки
            обновляются из каталога, ручные собираются вручную и сохраняют порядок.
          </p>
        </div>
        <button type="button" className="btn btn--primary btn--sm" onClick={openCreate}>
          <Icon name="plus" size={15} />
          Новая подборка
        </button>
      </div>

      {collectionsQuery.isLoading ? (
        <Skeleton height="220px" />
      ) : collectionsQuery.isError ? (
        <ErrorState
          title="Подборки недоступны"
          message={adminErrorMessage(collectionsQuery.error)}
          onRetry={() => void collectionsQuery.refetch()}
        />
      ) : collections.length === 0 ? (
        <EmptyState compact icon="list" title="Подборок пока нет" description="Создайте первую подборку." />
      ) : (
        <div className="admin-collections">
          {collections.map((collection) => (
            <article
              key={collection.id}
              className={`admin-collection-card${collection.enabled ? '' : ' is-disabled'}`}
            >
              <div className="admin-collection-card__main">
                <div className="admin-collection-card__title">
                  <strong>{collection.title}</strong>
                  <span className={`badge${collection.kind === 'smart' ? ' badge--success' : ''}`}>
                    {collection.kind === 'smart' ? 'умная' : 'ручная'}
                  </span>
                  {!collection.enabled ? <span className="badge badge--danger">скрыта</span> : null}
                </div>
                <code>/{collection.slug}</code>
                <p>{collection.description || 'Без описания'}</p>
                <span className="admin-collection-card__meta">
                  {formatInt(collection.item_count)} тайтлов · позиция {collection.position}
                </span>
              </div>
              <div className="admin-collection-card__actions">
                <button type="button" className="btn btn--outline btn--sm" onClick={() => openEdit(collection)}>
                  <Icon name="edit" size={14} />
                  Изменить
                </button>
                <button
                  type="button"
                  className="btn btn--ghost btn--sm"
                  onClick={() => {
                    setManagingId(collection.id);
                    setSearch('');
                  }}
                >
                  <Icon name="list" size={14} />
                  Тайтлы
                </button>
                <button
                  type="button"
                  className="btn btn--ghost btn--sm"
                  onClick={() => {
                    if (window.confirm(`Удалить подборку «${collection.title}»?`)) {
                      deleteMutation.mutate(collection.id);
                    }
                  }}
                >
                  <Icon name="trash" size={14} />
                  Удалить
                </button>
              </div>
            </article>
          ))}
        </div>
      )}

      <div className="admin-collections__insights">
        <div>
          <h3>Клики и показы</h3>
          {metricsQuery.isLoading ? (
            <Skeleton height="120px" />
          ) : metricsQuery.isError ? (
            <p className="muted small">Метрики недоступны: {adminErrorMessage(metricsQuery.error)}</p>
          ) : (metricsQuery.data?.items.length ?? 0) === 0 ? (
            <p className="muted small">Событий пока нет. Показы и клики пишутся без PII.</p>
          ) : (
            <div className="admin-table-wrap">
              <table className="admin-table admin-table--compact">
                <thead>
                  <tr>
                    <th>Блок</th>
                    <th>Показы</th>
                    <th>Клики</th>
                    <th>CTR</th>
                  </tr>
                </thead>
                <tbody>
                  {metricsQuery.data?.items.slice(0, 12).map((item) => (
                    <tr key={item.surface}>
                      <td><code>{item.surface}</code></td>
                      <td>{formatInt(item.impressions)}</td>
                      <td>{formatInt(item.clicks)}</td>
                      <td>{(item.ctr * 100).toFixed(1)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
        <div>
          <h3>Аудит редактуры</h3>
          {auditQuery.isLoading ? (
            <Skeleton height="120px" />
          ) : auditQuery.isError ? (
            <p className="muted small">Аудит недоступен: {adminErrorMessage(auditQuery.error)}</p>
          ) : (auditQuery.data?.length ?? 0) === 0 ? (
            <p className="muted small">Действий пока нет.</p>
          ) : (
            <ul className="admin-collection-audit">
              {auditQuery.data?.slice(0, 10).map((entry) => (
                <li key={entry.id}>
                  <strong>{AUDIT_LABELS[entry.action] ?? entry.action}</strong>
                  <span>
                    {String(entry.details.title || entry.details.slug || '')}
                    {entry.details.manga_title ? ` · ${String(entry.details.manga_title)}` : ''}
                  </span>
                  <time>{formatDateTime(entry.created_at)}</time>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <Modal
        open={formOpen}
        onClose={() => {
          if (!saveMutation.isPending) {
            setFormOpen(false);
            setEditing(null);
          }
        }}
        title={editing ? 'Изменить подборку' : 'Новая подборка'}
        size="md"
        footer={
          <>
            <button
              type="button"
              className="btn btn--ghost"
              onClick={() => setFormOpen(false)}
              disabled={saveMutation.isPending}
            >
              Отмена
            </button>
            <button
              type="submit"
              form="collection-form"
              className="btn btn--primary"
              disabled={saveMutation.isPending}
            >
              {saveMutation.isPending ? <DancingSpinner size={16} /> : <Icon name="check" size={16} />}
              Сохранить
            </button>
          </>
        }
      >
        <form id="collection-form" className="admin-collection-form" onSubmit={submit}>
          <label className="field">
            <span>Название</span>
            <input
              className="input"
              value={draft.title}
              onChange={(event) => setDraft({ ...draft, title: event.target.value })}
              maxLength={128}
              required
              data-autofocus
            />
          </label>
          <label className="field">
            <span>Slug</span>
            <input
              className="input"
              value={draft.slug}
              onChange={(event) => setDraft({ ...draft, slug: event.target.value })}
              placeholder="автоматически из названия"
              maxLength={64}
            />
          </label>
          <label className="field">
            <span>Описание</span>
            <textarea
              className="input"
              value={draft.description}
              onChange={(event) => setDraft({ ...draft, description: event.target.value })}
              maxLength={512}
              rows={3}
            />
          </label>
          <div className="admin-collection-form__row">
            <label className="field">
              <span>Тип</span>
              <select
                className="input"
                value={draft.kind}
                onChange={(event) =>
                  setDraft({ ...draft, kind: event.target.value as CollectionKind })
                }
              >
                <option value="manual">Ручная</option>
                <option value="smart">Умная</option>
              </select>
            </label>
            <label className="field">
              <span>Правило</span>
              <select
                className="input"
                value={draft.rule}
                onChange={(event) =>
                  setDraft({ ...draft, rule: event.target.value as CollectionRule })
                }
                disabled={draft.kind !== 'smart'}
              >
                {Object.entries(RULE_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="admin-collection-form__row">
            <label className="field">
              <span>Позиция</span>
              <input
                className="input"
                type="number"
                min={0}
                max={10000}
                value={draft.position}
                onChange={(event) => setDraft({ ...draft, position: event.target.value })}
              />
            </label>
            <label className="field">
              <span>Тайтлов на главной</span>
              <input
                className="input"
                type="number"
                min={1}
                max={60}
                value={draft.limit}
                onChange={(event) => setDraft({ ...draft, limit: event.target.value })}
              />
            </label>
          </div>
          <label className="admin-check">
            <input
              type="checkbox"
              checked={draft.enabled}
              onChange={(event) => setDraft({ ...draft, enabled: event.target.checked })}
            />
            <span>Показывать на сайте</span>
          </label>
        </form>
      </Modal>

      <Modal
        open={Boolean(current)}
        onClose={() => setManagingId(null)}
        title={current ? `Тайтлы: ${current.title}` : 'Тайтлы'}
        size="lg"
      >
        {current ? (
          <div className="admin-collection-items">
            {current.kind === 'smart' ? (
              <p className="admin-collection-items__hint">
                Умная подборка рассчитывается правилом «{RULE_LABELS[current.rule as CollectionRule] ?? current.rule}».
                Ручной список недоступен; измените правило или создайте ручную подборку.
              </p>
            ) : (
              <>
                <form
                  className="admin-collection-search"
                  onSubmit={(event) => {
                    event.preventDefault();
                    const first = searchQuery.data?.items[0];
                    if (first) addMutation.mutate({ id: current.id, mangaId: first.id });
                  }}
                >
                  <input
                    className="input"
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                    placeholder="Найти тайтл по названию…"
                    aria-label="Поиск тайтла для подборки"
                  />
                  <button type="submit" className="btn btn--outline btn--sm" disabled={!search.trim()}>
                    <Icon name="plus" size={14} />
                    Добавить первый
                  </button>
                </form>
                {search.trim().length >= 2 ? (
                  <div className="admin-collection-search__results">
                    {searchQuery.isLoading ? <Skeleton height="54px" /> : null}
                    {searchQuery.data?.items.map((manga) => (
                      <button
                        key={manga.id}
                        type="button"
                        className="admin-collection-search__result"
                        onClick={() => addMutation.mutate({ id: current.id, mangaId: manga.id })}
                        disabled={addMutation.isPending}
                      >
                        <strong>{manga.title}</strong>
                        <span>
                          {manga.chapters_count} гл. · {manga.source}
                        </span>
                        <Icon name="plus" size={14} />
                      </button>
                    ))}
                    {!searchQuery.isLoading && (searchQuery.data?.items.length ?? 0) === 0 ? (
                      <p className="muted small">Ничего не найдено.</p>
                    ) : null}
                  </div>
                ) : null}

                {current.items.length === 0 ? (
                  <EmptyState compact icon="list" title="Список пуст" description="Найдите тайтл выше." />
                ) : (
                  <ol className="admin-collection-items__list">
                    {current.items.map((item, index) => (
                      <li key={item.id}>
                        <span className="admin-collection-items__index">{index + 1}</span>
                        <div>
                          <strong>{item.title}</strong>
                          <span>
                            {item.chapters_count} гл. · {item.rating ? `${item.rating.toFixed(1)} / 10` : 'без рейтинга'}
                          </span>
                        </div>
                        <div className="admin-collection-items__actions">
                          <button
                            type="button"
                            className="btn btn--icon btn--ghost btn--sm"
                            aria-label="Выше"
                            disabled={index === 0 || reorderMutation.isPending}
                            onClick={() => moveItem(current, index, -1)}
                          >
                            <Icon name="chevron-up" size={15} />
                          </button>
                          <button
                            type="button"
                            className="btn btn--icon btn--ghost btn--sm"
                            aria-label="Ниже"
                            disabled={index === current.items.length - 1 || reorderMutation.isPending}
                            onClick={() => moveItem(current, index, 1)}
                          >
                            <Icon name="chevron-down" size={15} />
                          </button>
                          <button
                            type="button"
                            className="btn btn--icon btn--ghost btn--sm"
                            aria-label="Убрать из подборки"
                            disabled={removeMutation.isPending}
                            onClick={() =>
                              removeMutation.mutate({ id: current.id, mangaId: item.id })
                            }
                          >
                            <Icon name="close" size={15} />
                          </button>
                        </div>
                      </li>
                    ))}
                  </ol>
                )}
              </>
            )}
          </div>
        ) : null}
      </Modal>
    </section>
  );
}
