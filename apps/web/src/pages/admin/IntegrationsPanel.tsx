import { useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  adminApi,
  adminErrorMessage,
  type AdminSourceCookie,
} from '../../api/admin';
import { api } from '../../api/client';
import type { SourceOut } from '../../api/types';
import { EmptyState } from '../../components/EmptyState';
import { ErrorState } from '../../components/ErrorState';
import { Icon } from '../../components/Icon';
import { DancingSpinner } from '../../components/DancingLoader';
import { Skeleton } from '../../components/Skeleton';
import { formatDateTime } from '../../lib/format';
import { extractHarCookie } from '../../lib/har';
import { toast } from '../../stores/toast';
import { YandexIntegrationPanel } from '../../components/admin/YandexIntegrationPanel';

function SourceCookieRow({ source }: { source: SourceOut }) {
  const queryClient = useQueryClient();
  const [value, setValue] = useState('');
  const harInputRef = useRef<HTMLInputElement>(null);
  const stateQuery = useQuery({
    queryKey: ['admin', 'source-cookie', source.code],
    queryFn: ({ signal }) => adminApi.getSourceCookie(source.code, signal),
  });
  const state: AdminSourceCookie | undefined = stateQuery.data;
  const saveMutation = useMutation({
    mutationFn: (cookie: string) => adminApi.setSourceCookie(source.code, cookie),
    onSuccess: (next) => {
      setValue('');
      queryClient.setQueryData(['admin', 'source-cookie', source.code], next);
      toast.success(next.configured ? 'Cookie сохранён' : 'Cookie очищен');
    },
    onError: (error) => toast.error(adminErrorMessage(error, 'Не удалось сохранить cookie')),
  });
  const harMutation = useMutation({
    mutationFn: async (file: File) => {
      let text: string;
      try {
        text = await file.text();
      } catch {
        throw new Error('Не удалось прочитать HAR-файл. Проверьте доступ к файлу и его размер.');
      }
      const result = extractHarCookie(text, source.code);
      if (result.status === 'invalid-har') {
        throw new Error(
          'Файл не является корректным HAR. Сохраните его заново: DevTools → Network → Save all as HAR.',
        );
      }
      if (result.status === 'no-cookie') {
        throw new Error(
          'В HAR не нашлись cookie для этого источника. Откройте сайт, авторизуйтесь и сохраните HAR заново.',
        );
      }
      return adminApi.setSourceCookie(source.code, result.cookie);
    },
    onSuccess: (next) => {
      setValue('');
      queryClient.setQueryData(['admin', 'source-cookie', source.code], next);
      toast.success('Cookie из HAR сохранён');
    },
    onError: (error) => {
      toast.error(
        error instanceof Error && error.message ? error.message : 'Не удалось прочитать HAR-файл',
      );
    },
  });

  return (
    <div className="admin-cookie-row">
      <div className="admin-cookie-row__head">
        <div className="admin-cookie-row__title">
          <strong>{source.name}</strong>
          <span>{source.code}</span>
        </div>
        <span className={`badge${state?.configured ? ' badge--success' : ''}`}>
          {stateQuery.isLoading ? 'Проверка…' : state?.configured ? 'Настроен' : 'Не задан'}
        </span>
      </div>
      {state?.supported === false ? (
        <p className="admin-cookie-row__note">Источник не поддерживает cookie-авторизацию.</p>
      ) : (
        <>
          <div className="admin-cookie-row__form">
            <input
              className="input"
              type="password"
              value={value}
              onChange={(event) => setValue(event.target.value)}
              placeholder="Cookie или токен источника"
              autoComplete="off"
              spellCheck={false}
              aria-label={`Cookie для ${source.name}`}
            />
            <button
              type="button"
              className="btn btn--primary btn--sm"
              disabled={!value.trim() || saveMutation.isPending}
              onClick={() => saveMutation.mutate(value.trim())}
            >
              {saveMutation.isPending ? <DancingSpinner size={14} /> : <Icon name="check" size={14} />}
              Сохранить
            </button>
            <button
              type="button"
              className="btn btn--ghost btn--sm"
              disabled={!state?.configured || saveMutation.isPending}
              onClick={() => {
                if (!window.confirm(`Очистить cookie для ${source.name}?`)) return;
                saveMutation.mutate('');
              }}
            >
              Очистить
            </button>
            <input
              ref={harInputRef}
              type="file"
              accept=".har,application/json"
              hidden
              onChange={(event) => {
                const file = event.target.files?.[0];
                event.target.value = '';
                if (file) harMutation.mutate(file);
              }}
            />
            <button
              type="button"
              className="btn btn--outline btn--sm"
              disabled={harMutation.isPending}
              onClick={() => harInputRef.current?.click()}
              title="Извлечь cookie из сохранённого HAR-файла"
            >
              {harMutation.isPending ? <DancingSpinner size={14} /> : <Icon name="download" size={14} />}
              Из HAR
            </button>
          </div>
          <p className="admin-cookie-row__note">
            {state?.updated_at
              ? `Обновлён ${formatDateTime(state.updated_at)}. Значение хранится на сервере и никогда не возвращается в браузер.`
              : 'Можно вставить заголовок Cookie вручную или загрузить HAR — браузер извлечёт cookie локально, на сервер уйдёт только заголовок Cookie.'}
          </p>
        </>
      )}
    </div>
  );
}

function SourceCookiesPanel() {
  const sourcesQuery = useQuery({
    queryKey: ['sources'],
    queryFn: ({ signal }) => api.sources(signal),
  });
  const sources = sourcesQuery.data ?? [];

  return (
    <section className="admin-panel" aria-labelledby="admin-cookies-title">
      <div className="admin-panel__head">
        <div>
          <h2 id="admin-cookies-title">Источники и cookie</h2>
          <p>
            Авторизация для Remanga и других источников. Пустое значение означает
            анонимный доступ. Cookie применяется сразу, без перезапуска парсера.
          </p>
        </div>
      </div>
      {sourcesQuery.isLoading ? (
        <Skeleton height="180px" style={{ borderRadius: 12 }} />
      ) : sourcesQuery.isError ? (
        <ErrorState
          title="Источники недоступны"
          message={adminErrorMessage(sourcesQuery.error)}
          onRetry={() => void sourcesQuery.refetch()}
        />
      ) : sources.length === 0 ? (
        <EmptyState
          compact
          icon="server"
          title="Нет источников"
          description="Парсер не вернул ни одного источника."
        />
      ) : (
        <div className="admin-cookie-list">
          {sources.map((source) => (
            <SourceCookieRow key={source.code} source={source} />
          ))}
        </div>
      )}
    </section>
  );
}

export function IntegrationsPanel() {
  return (
    <div className="admin-panel-stack">
      <YandexIntegrationPanel />
      <SourceCookiesPanel />
    </div>
  );
}
