# Интеграция v1.2

Ветка: `release/v1.2-integration`  
База: `main` @ `b0080b2` (`merge: docs encoding and HTTPS public URL fixes`)  
Назначение: reviewable integration branch для EPIC
[#48](https://github.com/geekAmis/mangapoiskAPI/issues/48). В `main` не
мержилась, деплой не выполнялся.

## 1. Порядок merge

Все merge выполнены с `--no-ff`. Исходные ветки не переписывались.

| № | Ветка | Исходный commit | Merge commit | Что вошло |
|---:|---|---|---|---|
| 1 | `fix/catalogue-reliability` | `6ff8be0` | `8ed0ade` | retries, per-source circuit breaker, enrichment queue, admin catalogue panel |
| 2 | `fix/media-cache-lru` | `f17bec5` | `26f45a3` | image LRU, hourly archive eviction, media storage admin panel |
| 3 | `feat/retention` | `83b8440` | `dddd738` | continue reading, recommendations, series/related, streak, analytics |
| 4 | `feat/chapter-notifications` | `448f545` | `1f773e5` | title follows, in-app feed, Web Push, service worker |
| 5 | `feat/ads-settings` | `e65d2f6` | `ede33cb` | ad providers/secrets/slots/audiences, admin AdsPanel |
| 6 | `feat/ops-dashboard` | `e2087b1` | `5f5f07a` | crawler/storage snapshot, admin crawler panel, ETA |
| 7 | `fix/android-https` | `a9ac0e5` | `cb0db11` | Capacitor HTTPS build, network security config |
| 8 | `feat/search` | `a8e73f2` | `e7ebf53` | PG `pg_trgm`/`unaccent`, SQLite FTS5, typo/translit/synonyms, `/manga/suggest`, combobox/history |
| 9 | `fix/ops-critical` (draft PR #62) | `80d72c8` | `ae2e3db` | UFW/backup/swap runbooks, restic backup/restore scripts, systemd units, control memory drop-in |

## 2. Разрешённые конфликты

Функциональность ни одной ветки не удалена. При пересечении реализаций выбрана
более полная, недостающее поведение портировано.

| Файл / область | Решение |
|---|---|
| `apps/web/src/pages/AdminPage.tsx`, `styles/admin.css` | сохранены все секции: crawler status, catalogue/enrichment, media storage, ads, servers/moderation; CSS объединён |
| `apps/web/src/api/admin.ts` | сохранены типы и методы storage, crawler, ads; `getMediaStats` и `getCrawlerStatus` оба доступны |
| `services/gateway/app/api.py` | сохранены `/admin/catalogue`, `/admin/media/stats`, `/admin/crawl`, retention/notifications/search routes |
| `services/gateway/app/clients.py`, `main.py` | сохранены enrichment stats, search suggest, notifier/comments clients и все routers |
| `services/catalog/app/{models,schemas,service,repository,migrations}.py` | одновременно enrichment/circuit-breaker, `eta_seconds`, `MangaRelation`, search columns/FTS/trgm; `CatalogStats` отдаёт `pending`, `pending_enrichment`, `retrying_enrichment` |
| `services/catalog/app/service.py` | объединены импорты recommendations, relations, enrichment и search |
| `services/scheduler/app/catalogue.py` | failure/health поля circuit breaker + `eta_seconds` |
| `services/media/app/{api,archive,cache}.py` | выбран LRU-вариант (более полный); `_build_crawler_status` научен читать вложенный `image_cache` для ops-панели |
| `apps/web/src/pages/MangaPage.tsx` | resume из retention + follow status из notifications; дублирующий server-only progress query убран |
| `apps/web/src/pages/HomePage.tsx` | anonymous continue reading + recommendations + `AdSlot placement="in-feed"` |
| `apps/web/src/components/layout/AppLayout.tsx` | `useProgressSync` + header/mobile-sticky ad slots |
| `apps/mobile/README.md` | HTTPS-инструкции Android + ограничение Web Push/Capacitor |
| `docs/OPS.md` | объединены три части: аудит надёжности #44, media LRU #56, firewall/backup/swap runbook PR #62 |
| `apps/web/src/api/client.ts`, `packages/manga_common/schemas.py` | сохранены retention/search/notifications типы |

Добавлены/расширены тесты на стыках:

- `tests/gateway/test_crawler_status.py` — вложенный `image_cache` из media LRU
  и fallback `pending_enrichment`;
- `tests/catalog/test_catalog_api.py` — одновременно `pending` и
  `pending_enrichment` в `/internal/stats`.

## 3. Тестовая матрица

Финальный прогон на `release/v1.2-integration` после merge `fix/ops-critical`.

| Проверка | Команда | Результат |
|---|---|---|
| Lint | `ruff check packages services tests` | PASS |
| Backend | `pytest` | **331 passed, 1 skipped** (network), 14 warnings, 155.74 s |
| Web types | `npm run typecheck` | PASS |
| Web build | `npm run build` | PASS |
| Web unit | `npm run test:unit` | 4/4 PASS |
| Mobile web build | `npm run build:www` (apps/mobile) | PASS, plain-HTTP fallback отсутствует |
| Ops scripts syntax | `bash -n scripts/ops/*.sh` | PASS |
| Search benchmark (SQLite) | `scripts/benchmark_search.py --titles 5000 --runs 7` | search p50 25.37 ms / p95 40.43 ms; suggest p50 19.70 ms / p95 32.81 ms |

Коммит-доказательство бенчмарка:
`docs/benchmarks/search-sqlite-5000.json` (search p95 40.43 ms, suggest p95
32.81 ms). Локальный прогон интеграции немного шумнее, но укладывается в
требование p95 < 100 ms.

## 4. Совместная проверка фич

- Каталог + поиск: search-колонки, FTS/trgm и enrichment-очередь работают на
  одной модели `Manga`; `/internal/stats` совмещает backlog, pending by source и
  search-индексы.
- MangaPage: resume, recommendations/related, follow, Web Push prompt и ads
  слоты сосуществуют; дублирующий progress query удалён.
- HomePage: anonymous и authenticated continue reading, recommendations,
  streak, in-app ad slot.
- Admin: crawler status, catalogue/enrichment, media storage, ads, servers,
  moderation — все панели на одной странице.
- Notifications: in-app comments/chapter feed, follows и Web Push не конфликтуют
  с retention analytics; scheduler fan-out сохраняет circuit-breaker поведение.
- Media/Ops: LRU-статистика отображается и в media panel, и в crawler snapshot.
- Android: HTTPS build и notifications fallback описаны совместно.

## 5. Известные пробелы и что нужно от lead

1. **PostgreSQL search path не проверен вживую.** Локально нет PostgreSQL;
   проверены SQL-компиляция, миграция и SQLite FTS5. Перед production нужно
   прогнать `BENCHMARK_DATABASE_URL=postgresql+asyncpg://... python
   scripts/benchmark_search.py` и проверить `pg_trgm`/`unaccent` + GIN-индексы
   на копии БД.
2. **Android APK не собран в этой сессии.** Нет Android SDK; проверен
   `apps/mobile` web build и `npm run build:www`. Release signing/on-device QA
   остаются за владельцем Android-ветки.
3. **PR #62 — draft.** Скрипты `scripts/ops/*` не содержат секретов и читают
   `RESTIC_PASSWORD_FILE`, но перед production нужны approval lead/DevOps на:
   включение UFW с dead-man rollback, инициализацию restic-репозитория,
   распространение password-файла, установку systemd units/timer и
   `mangapoisk-control` memory drop-in.
4. **Web Push требует VAPID env.** Без `VAPID_PUBLIC_KEY`/`VAPID_PRIVATE_KEY`
   сервис работает в режиме только in-app; ключи в репозиторий не коммитились.
5. **Ads:** реальные сетевые SDK Яндекс/AdFox/Google остаются placeholder;
   custom HTML/script и слоты работают. CSP-заголовок пока не включён nginx.
6. **Браузерный QA интеграционной ветки не повторялся.** Фичи проверены
   владельцами отдельно (скриншоты в ветках); в интеграции выполнены
   typecheck/build/tests. Перед деплоем нужен общий smoke на 1440×900 и
   390×844.
7. Полный `pytest -m network` не запускался (сетевые тесты по умолчанию
   skipped).

## 6. Hotfix #63 — startup backfill

Ветка: `fix/catalog-migration-startup` от `b480407`.
Production RC падал на 80-секундном health gate: старый
`ensure_runtime_schema` перебирал 78 275 строк в Python (~2m43s) в одной
транзакции.

Исправление:

- startup — только additive schema (колонки/индексы/FTS) + один
  `UPDATE ... SET search_indexed = true WHERE search_blob <> ''`;
- legacy-FTS bootstrap (~1.3 с на 78k) делает строки доступными до
  нормализации;
- `SearchBackfillWorker` — батчи 500 строк, WAL/busy_timeout, retry/backoff,
  lease в `search_backfill_state`, прогресс в `/internal/search/backfill` и
  `/internal/stats`, продолжение после рестарта без дублей;
- поиск/подсказки во время миграции используют legacy-колонки и не дают 500.

Замер на 78 275 строках: **lifespan 1.37 с** (было 123.6 с), процесс →
`/health` **6.9 с**, фоновый backfill 179 с (~436 строк/с), повторный запуск
0 строк.  JSON: `docs/benchmarks/migration-sqlite-78275.json`.

Перед повторным деплоем:

1. Бэкап `catalog.db` / `pg_dump` (OPS §9.1).
2. Опционально `scripts/reindex_catalog.py` на остановленном каталоге.
3. Deploy; контроль `/health` < 10 с и
   `/internal/search/backfill` до `status=completed`.
4. Rollback — OPS §9.4.
