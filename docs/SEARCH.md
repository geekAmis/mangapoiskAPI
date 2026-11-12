# Поиск каталога

## Выбранная схема

Выбран **PostgreSQL `pg_trgm` + `unaccent` + нормализованные поисковые колонки**
без отдельного поискового сервиса.  Причина: каталог уже живёт в PostgreSQL,
а требования (опечатки, транслит, синонимы, альтернативные названия, p95 <
100 мс) закрываются триграммами и Python-нормализацией.  Meilisearch добавил
бы ещё один процесс, хранилище, резервное копирование и сетевой хоп без
измеримой пользы для текущего объёма.

Для SQLite (локальная разработка, тестовые БД) используется встроенный
**FTS5-миррор** той же поисковой строки.  Это не новая инфраструктурная
зависимость: FTS5 входит в поставляемый с Python SQLite.

### Колонки

На `manga` добавлены:

| Колонка | Содержимое |
|---|---|
| `authors`, `artists` | JSON-массивы имён из detail import (MangaLib, Remanga, MangaPoisk, если источник отдаёт) |
| `search_title` | нормализованный `title`, транслит, фонетика, скелеты согласных |
| `search_alt` | `title_en`, `title_alt` |
| `search_author` | `authors` + `artists` (плюс legacy `metadata.authors/artists`) |
| `search_names` | `search_title` + `search_alt` для триграммных запросов |
| `search_meta` | жанры (метки + канонические slug), тип контента и медиа-синонимы |
| `search_description` | нормализованное описание (низкий вес, только фразовое совпадение) |
| `search_blob` | объединённый документ title/alt/author/meta/description для `LIKE`/FTS |
| `search_doc_version` | версия алгоритма нормализации; старые строки автоматически уходят в bounded reindex |
| `search_indexed` | `false`, пока строка ещё не прошла фоновую нормализацию |

Нормализация выполняется в Python при каждой записи, а для старых строк —
фоновым воркером (`search_backfill.py`), не на старте сервиса:

* casefold, `ё → е`, снятие диакритики, пунктуация → пробел;
* русская транслитерация (`человек → chelovek`);
* фонетическая кириллица для латиницы (`chainsaw → чейнсо`);
* скелет согласных (`чейнсо мен → чнсмн`) — ловит ошибки в гласных;
* confusable-скелет: гласные удаляются, а `з/с/ц → с`, `ч/ц → ц`,
  `е/э/и/ы/й → е/и`, `о/а → а` (`чензо`, `ченсо → цнс`; `чейнсо → цинс`;
  транслит `chenzo`, `chenso`, `chainsaw → chns`);
* синонимы: жанровые алиасы (`боевик → action`), типы контента
  (`манхва → manhwa`), слова действия чтения (`читать`, `читка`) игнорируются.

Скелеты участвуют в отборе кандидатов и в точном/префиксном совпадении, но
не в fuzzy-расстоянии: иначе короткие несвязанные слова (`манхва` и
`Менхера`) становились бы похожими.  Fuzzy-Левенштейн работает по обычным
токенам, транслиту и фонетике.

### Ранжирование

Вес полей: `title 1.0`, `alt 0.82`, `author 0.62`, `meta 0.38`,
`description 0.12`.  Точное совпадение названия, префикс, фраза и покрытие
всех токенов дают основной вклад; популярность (рейтинг/число оценок/главы) —
только тай-брейкер.  Кандидаты, попавшие в выборку только по общему
двухбуквенному терму, отсекаются относительным порогом.  Для multi-word
запросов с коротким токеном (`чензо мен`) дополнительно требуется покрытие
всех значимых токенов, если такие строки существуют.

Опечатки: distance-aware Левенштейн + триграммы, порог зависит от длины
токена (1 правка для 3–7 символов, 2 до 12, 3 дальше).  Транслит,
consonant- и confusable-скелеты дают точные варианты для `чензо мен` →
`чейнсо`/`chns`, `ченсо мен` и `chenzo man`.  Confusable-подстановки
(`з/с/ц`, `ч/ц`, `е/э`, `о/а`) добавляются в SQL-кандидаты и на SQLite, и на
PostgreSQL; раньше PostgreSQL LIKE-фильтр их не получал, поэтому production
не находил Chainsaw Man, хотя SQLite-тесты проходили.

### Подсказки и история

* `GET /api/v1/manga/suggest` — только локальный индекс, **никогда** не
  вызывает парсер.  Отдельный эндпоинт специально не имеет флага `live`.
  Подсказки ищут по title/alt/author/meta, возвращают `authors` и `reason`
  (`title`, `alternative`, `author`, `genre`, `description`).
* Фронтенд: debounce 180 мс, `combobox/listbox`, `aria-activedescendant`,
  стрелки/Enter/Escape/Home/End, фокус остаётся на поле.
* История: `localStorage`, до 8 записей, namespace по `user.id` (анонимные
  запросы — отдельный bucket), очистка и приватный режим (не читает и не
  пишет историю).  История никогда не уходит на сервер.

### Кандидаты и стоимость

SQLite: FTS5 `MATCH` + `bm25` отбирает 300 кандидатов, затем Python
переранжирует их.  PostgreSQL: `LIKE '%term%'` по `search_blob` с GIN
`gin_trgm_ops`; тот же Python-ранкер.  Для авторов есть отдельный GIN-индекс
`ix_manga_search_author_trgm` и ветка `_candidate_order` по `search_author`.
Ограничение кандидатов — 300 (подсказки — 180), поэтому стоимость запроса не
растёт линейно с каталогом.

### Старт и фоновая миграция (фикс #63)

Старт **не перебирает строки в Python**.  `ensure_runtime_schema()` только
добавляет колонки/индексы, создаёт FTS-таблицу и одним SQL-запросом помечает
`search_indexed = true` те строки, у которых уже есть `search_blob` текущей
`search_doc_version`; строки со старой версией алгоритма уходят в фоновый
reindex.  Затем
`bootstrap_search_index()` за ~1.3 с заливает legacy-текст в FTS5 для
оставшихся строк — поиск и подсказки работают сразу.

Дальше `SearchBackfillWorker`:

* батчи по 500 строк, `asyncio.to_thread` для CPU-нормализации;
* коммит на каждый батч + `asyncio.sleep(yield)` и WAL/busy_timeout;
* повтор с экспоненциальным backoff при `database is locked`;
* lease в `search_backfill_state`: два процесса каталога не дублируют работу,
  lease переживает рестарт и истекает через 120 с;
* прогресс: `GET /internal/search/backfill`, `CatalogStats.search_backfill`,
  логи `search backfill progress: N/M`;
* рестарт продолжает с `WHERE search_indexed = false`, без дублей.

Пока строка не индексирована, SQLite ищет её по legacy-FTS, PostgreSQL — по
`lower(title/title_en/title_alt/description)`, а ранкер строит нормализованный
документ на лету.  Ни один путь не возвращает 500.

Пред-деплойный запуск (опционально, сервис должен быть остановлен):

```bash
.venv/bin/python scripts/reindex_catalog.py \
  --database-url "$CATALOG_DATABASE_URL" --batch-size 500
```

`--force` переиндексирует всё (после изменения алгоритма), `--rebuild-fts`
пересобирает SQLite-миррор.  Rollout/rollback — в `docs/OPS.md`.

### Авторы/художники и backfill

Detail import пишет `authors`/`artists` из MangaLib (`authors`, `artists`),
Remanga (`creators` + явные поля) и MangaPoisk (поля `authors`/`artists`, если
источник их начнёт отдавать).  Summary/search-импорт без людей не затирает уже
сохранённые значения.  `merge_group_metadata` объединяет людей между
source-вариантами одной группы, поэтому автор, найденный в MangaLib, доступен
и на карточке MangaPoisk.

Backfill идёт двумя bounded-путями:

1. При смене `SEARCH_DOC_VERSION` `ensure_runtime_schema` помечает старые
   строки `search_indexed = false`; `SearchBackfillWorker` переиндексирует их
   батчами и попутно копирует `metadata.authors/artists` в новые колонки.
2. Строки без людей обновляются обычной ротацией enrichment
   (`rotate_enrichment`, 100 тайтлов за incremental-цикл): scheduler заново
   импортирует detail и записывает авторов.

Прогресс виден в `GET /internal/stats` (`authors_missing`,
`artists_missing`), `GET /internal/search/backfill` и в админке («Без
авторов»).  Это не блокирует старт: поиск по уже известным авторам работает
сразу, остальные находятся по мере enrichment.

## Бенчмарк

```powershell
.venv/Scripts/python scripts/benchmark_search.py --titles 5000 --runs 7
# PostgreSQL (нужен пустой DSN; миграция создаст pg_trgm/unaccent и GIN-индексы):
$env:BENCHMARK_DATABASE_URL="postgresql+asyncpg://..."
.venv/Scripts/python scripts/benchmark_search.py --titles 5000 --runs 7
```

31 relevance-запрос (опечатки, транслит, RU/EN alt titles, авторы/художники,
автор+название, жанры, пустые и длинные запросы), 5000 реалистичных тайтлов.
Локальный результат SQLite (Windows, Python 3.13, 7 прогонов, медиана по
каждому запросу):

| Метрика | Значение |
|---|---|
| search p50 | 50.17 мс |
| search p95 | 81.89 мс |
| search p95 по сырым замерам | 93.31 мс |
| suggest p50 | 35.01 мс |
| suggest p95 | 63.21 мс |
| suggest p95 по сырым замерам | 69.90 мс |
| размер БД | 29.0 МБ |
| текст в FTS-мирроре | 2.33 МБ |

Сырой JSON: `docs/benchmarks/search-sqlite-5000.json`.  На общем Windows-хосте
бывают выбросы планировщика; скрипт печатает и p95 по медианам запросов, и
p95 по сырым замерам, чтобы это было видно.

`index_bytes` для SQLite не выводится: в этой сборке Python нет `dbstat`.
На PostgreSQL скрипт печатает `pg_indexes_size('manga')` и
`pg_total_relation_size('manga')`.

### Стартовая миграция на 78 275 строках

`scripts/benchmark_migration.py --titles 78275 --batch-size 500`
(фикстура v1.2: search-колонки есть, `search_indexed` ещё нет):

| Метрика | Было (`ensure_runtime_schema` с Python backfill) | Стало |
|---|---|---|
| schema + indexes + mark | 123.6 с | **0.15 с** |
| legacy FTS bootstrap | входил в backfill | **1.22 с** |
| **startup до health** | **123.6 с** | **1.37 с** |
| фоновый backfill | — | 178.6 с, 436 строк/с |
| повторный запуск | — | 0 строк, без дублей |
| search во время backfill | — | 256 мс, результаты есть |
| suggest во время backfill | — | 145 мс, результаты есть |

JSON: `docs/benchmarks/migration-sqlite-78275.json`.  Реальный запуск
`uvicorn` на этой БД: **6.9 с от старта процесса до `/health` 200** (4.74 с
внутри lifespan, остальное — импорт Python/uvicorn).  Это и есть причина,
почему 80-секундный health gate control больше не срабатывает: каталог
становится healthy после схемы и legacy-FTS, а нормализация идёт фоном.

## Ограничения и риски

* **Автор/художник**: поля есть в контракте и индексируются, но не все
  источники их отдают.  MangaLib отдаёт `authors`/`artists`, Remanga —
  `creators`, MangaPoisk на 2026-11-13 людей в Inertia-payload не отдаёт.
  Такие строки остаются в `authors_missing` и обновляются при enrichment;
  поиск по ним не работает, пока источник не вернёт имя.  Для старых строк
  без колонок confusable/people-поля подхватываются из `metadata` при
  переиндексации.
* **PostgreSQL не запускался в этой среде** (нет Docker/локального сервера).
  SQL для PG компилируется, миграция идемпотентна; перед выкаткой нужно один
  раз прогнать `benchmark_search.py` с `BENCHMARK_DATABASE_URL` на реальном
  инстансе и проверить `pg_indexes_size`.
* Первый старт после миграции больше не ждёт Python-нормализацию: схема +
  legacy-FTS ~1.5 с на 78k, остальное — фоновый воркер (~2.5 минуты при
  текущей скорости).  Дальше документ обновляется при каждом upsert.
* Если фоновая миграция упала, сервис остаётся healthy, `search_backfill.status
  = failed`, а поиск продолжает работать по legacy-фолбэку.  Повторный старт
  или `scripts/reindex_catalog.py` продолжает с места остановки.
* `search_blob` ограничен 20 000 символов; описание — 1200 символов.  Это
  защищает от гигантских upstream-описаний.
