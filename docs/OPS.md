# OPS — медиа-хранилище и LRU

Документ описывает дисковые лимиты MangaPoisk Reborn, фоновую очистку и
диагностику. Относится к issue
[#56](https://github.com/geekAmis/mangapoiskAPI/issues/56).

## 1. Что и чем ограничено

| Хранилище | Переменная | По умолчанию | Что удаляется |
|---|---|---:|---|
| Архив глав (ZIP + SQLite blobs) | `ARCHIVE_MAX_BYTES` | `25 GiB` | только строки `chapter_archives`/`page_blobs` со статусом `done` и их ZIP-файлы |
| Кэш изображений (оригиналы, WebP-варианты, JSON-sidecar) | `MEDIA_CACHE_MAX_BYTES` | `10 GiB` | только файлы, созданные `MediaCache` |
| Метаданные каталога | — | без лимита | **не удаляются** сервисом media |
| Экспорты CBZ/PDF/HTML | `EXPORT_TTL_HOURS` | `48 ч` | отдельный `ExportManager` |

`0` в `ARCHIVE_MAX_BYTES` или `MEDIA_CACHE_MAX_BYTES` отключает eviction для
соответствующего хранилища. Для production рекомендуются значения из таблицы:
они оставляют запас на 60-гигабайтном диске и не затрагивают каталог.

## 2. Расписание очистки

- **Старт сервиса:** `ArchiveManager.prune()` и первый проход image-cache
  выполняются до `yield` в lifespan.
- **Архив глав:** после успешной записи каждой новой главы и затем каждый час
  (`ARCHIVE_PRUNE_INTERVAL_SECONDS=3600`), даже если новых глав нет.
- **Кэш изображений:** каждый час
  (`MEDIA_CACHE_PRUNE_INTERVAL_SECONDS=3600`), даже если новых картинок нет.
- **LRU-порядок архива:** `last_accessed_at`, fallback `updated_at`; каждое
  чтение страницы обновляет `last_accessed_at`.
- **LRU-порядок изображений:** `mtime` файла; успешное чтение из кэша
  обновляет `mtime` не чаще одного раза в 60 секунд.
- **Grace period:** изображение моложе
  `MEDIA_CACHE_PRUNE_MIN_AGE_SECONDS` (300 с) не удаляется, чтобы не оборвать
  текущую отдачу файла. Старые записи при этом evict-ятся как обычно.

Очистка идемпотентна: если ZIP занят читателем (Windows), строка архива
сохраняется и попадает в следующий проход; на Unix удаление также
обрабатывается без падения сервиса.

## 3. Предупреждения 80/90%

`/internal/stats` возвращает `level` (`ok`, `warning`, `critical`,
`unbounded`) и `usage_percent` для обоих хранилищ. При 80% и 90% в ответ
добавляются текстовые `warnings`, а фоновый pruner пишет `warning`/`error` в
лог. Админ-панель показывает те же предупреждения в секции
«Хранилище медиа».

Пороговые значения фиксированы: **80% — warning, 90% — critical**.

## 4. Статистика

Внутренний endpoint (нужен `X-Internal-Token`):

```bash
curl -fsS -H "X-Internal-Token: $INTERNAL_TOKEN" \
  http://127.0.0.1:8104/internal/stats | jq
```

Пример полей:

```json
{
  "generated_at": "2026-11-12T12:00:00Z",
  "image_cache": {
    "used_bytes": 1932735283,
    "cap_bytes": 10737418240,
    "files": 42117,
    "evictions": 0,
    "last_pruned_at": "2026-11-12T11:00:00Z",
    "usage_percent": 18.0,
    "level": "ok"
  },
  "archives": {
    "total": 733,
    "done": 402,
    "failed": 331,
    "pending": 0,
    "done_bytes": 723517440,
    "db_bytes": 1782579,
    "cap_bytes": 26843545600,
    "evictions": 0,
    "last_pruned_at": "2026-11-12T11:00:00Z",
    "usage_percent": 2.7,
    "level": "ok"
  },
  "warnings": []
}
```

`evictions` — счётчик с момента старта процесса media; после рестарта
обнуляется. `last_pruned_at` — время последнего **фактического** прохода
(не dry-run).

Админ-панель получает тот же снимок через
`GET /api/v1/admin/media/stats` (admin JWT) и обновляет его раз в минуту.

## 5. Ручная проверка и dry-run

Безопасный проход по умолчанию **ничего не удаляет** (`dry_run=true`):

```bash
curl -fsS -X POST \
  -H "X-Internal-Token: $INTERNAL_TOKEN" \
  "http://127.0.0.1:8104/internal/maintenance/prune?dry_run=true" | jq
```

Ответ показывает `removed`, `freed_bytes`, `used_bytes` и `cap_bytes` для
`image_cache` и `archives`. Для реальной очистки нужно явно передать
`dry_run=false`; endpoint защищён internal-токеном и не публикуется через
gateway.

```bash
# Освободить место немедленно (только по согласованию с lead)
curl -fsS -X POST \
  -H "X-Internal-Token: $INTERNAL_TOKEN" \
  "http://127.0.0.1:8104/internal/maintenance/prune?dry_run=false" | jq
```

## 6. Что не удаляется

Image LRU сканирует только имена, которые создаёт сам кэш:

- `sha256.<jpg|jpeg|png|webp|gif|avif>` — оригинал;
- `sha256-w<width>.webp` — reader-вариант;
- `<image>.json` — sidecar, удаляется **только вместе со своим image**.

ZIP-архивы, `archives.db`, `catalog.db`, экспорты и произвольные JSON-файлы
не являются кандидатами на удаление. Пользовательские метаданные каталога
хранятся в catalog-сервисе и не зависят от media LRU. Если cover вытеснен,
он будет скачан повторно при следующем запросе; запись тайтла, главы,
закладка или прогресс чтения не пострадают.

## 7. Ожидаемый эффект

На данных аудита 12.11.2026: `media-cache` = 1,8 ГБ, архив глав = 690 МБ.
После включения лимитов в 10 GiB и 25 GiB eviction не сработает сразу, но
рост кэша перестанет быть неограниченным. При устойчивом росте image-cache
выше 10 GiB каждый час будет освобождаться примерно столько байт, сколько
нужно для возврата под cap; при 50k тайтлов это защищает диск от
исчерпания. Архив выше 25 GiB начнёт удалять самые давно читаемые главы,
а не случайные свежие.

## 8. Ограничения и остаточные риски

- Eviction и счётчики process-local: при нескольких репликах media с общим
  volume каждый процесс считает свои evictions. Удаление файлов между
  процессами не координируется; повторный проход безопасен, но метрика
  `evictions` будет суммой по процессам, а не глобальной.
- `done_bytes` архива — логический размер страниц (`total_bytes`), а не
  сжатый размер ZIP. Это консервативно: cap может сработать чуть раньше, чем
  закончится физическое место.
- Изображение, которое отдаётся дольше grace period (300 с), теоретически
  может быть удалено во время стриминга. Клиент повторит запрос; для
  обычных страниц это не наблюдалось.
- `MEDIA_CACHE_MAX_BYTES` ограничивает только image-байты. Метаданные
  каталога по-прежнему не имеют лимита — это требование продукта.
- Ручной `dry_run=false` не является обязательным в runbook: фоновый pruner
  и так удерживает cap. Используйте его только при нехватке диска.

## 9. Проверки после деплоя

```bash
# 1. Stats и уровни
curl -fsS -H "X-Internal-Token: $INTERNAL_TOKEN" \
  http://127.0.0.1:8104/internal/stats | jq '.image_cache, .archives, .warnings'

# 2. Dry-run (ничего не удаляет)
curl -fsS -X POST -H "X-Internal-Token: $INTERNAL_TOKEN" \
  "http://127.0.0.1:8104/internal/maintenance/prune?dry_run=true" | jq

# 3. Архив читается после eviction: открыть главу в reader и проверить 200.
# 4. Админка: /admin → «Хранилище медиа», нет warning/critical без причины.
```
