# OPS — надёжность, бэкапы, алерты, стоимость и медиа-хранилище

Документ объединяет два эксплуатационных раздела: аудит production-контура
(issue [#44](https://github.com/geekAmis/mangapoiskAPI/issues/44)) и дисковые
лимиты/LRU медиа-хранилища
(issue [#56](https://github.com/geekAmis/mangapoiskAPI/issues/56)).

---

# 1. Надёжность, бэкапы, алерты и стоимость

Аудит production-контура MangaPoisk Reborn по issue
[#44](https://github.com/geekAmis/mangapoiskAPI/issues/44). Все проверки
выполнены **read-only** (`systemctl status`, `journalctl`, `df`, `free`,
`du`, `psql`/`sqlite3` SELECT). Ничего на серверах не менялось и не
перезапускалось.

Дата аудита: **2026-11-12**. Production: `85.192.37.58` (app), jump-host
`83.141.92.137`. Доступ к app — только через jump-host.

---

## 1. Кратко

| Область | Состояние | Риск |
|---|---|---|
| Сервисы | 11/11 systemd-юнитов active, `/health` 200 за 1.4–2.2 мс | нет |
| HTTP 5xx | 0,2 % за последний час; 592 ответа 502 за сутки — почти все в окна деплоя | средний |
| CPU | 2 vCPU, load average 0,7 | нет |
| RAM | 3,9 ГБ всего, 3,1 ГБ занято, available 755 МБ, **swap отсутствует** | **критичный** |
| Диск | 59 ГБ, занято 22 ГБ (39 %), inode 6 % | средний |
| Бэкапы | **нет ни одного бэкапа проекта, restore drill не проводился** | **критичный** |
| Алерты | есть Telegram для новых глав, **нет алертов по down/5xx/диску/бэкапам/краулеру** | высокий |
| Краулер | MangaPoisk завершён, Remanga идёт, MangaLib падает с 403/404 | высокий |
| Очередь обогащения | 27 597 из 28 929 тайтлов (95 %) без деталей | высокий |
| Архив глав | 733 МБ, 109 готовых глав, 331 failed (помечены при рестарте) | средний |
| Кэш изображений | 1,8 ГБ, **без LRU-лимита** | высокий |
| Изоляция | UFW выключен, replica API слушает `0.0.0.0:8108` и доступен из интернета | **критичный** |

---

## 2. Что реально работает

```text
mangapoisk-gateway    active  127.0.0.1:8100   health 200
mangapoisk-parser     active  127.0.0.1:8101   health 200
mangapoisk-catalog    active  127.0.0.1:8102   health 200
mangapoisk-library    active  127.0.0.1:8103   health 200
mangapoisk-media      active  127.0.0.1:8104   health 200
mangapoisk-control    active  127.0.0.1:8005   health 200
mangapoisk-notifier   active  127.0.0.1:8106   health 200
mangapoisk-replica    active  0.0.0.0:8108     health 200
mangapoisk-comments   active  127.0.0.1:8109   health 200
mangapoisk-scheduler  active  (без HTTP)
mangapoisk-web        active  nginx :8088/:8443
```

- Gateway `/api/v1/health`: `{"status":"ok","checks":{"catalog":true,"parser":true,"library":true,"media":true}}`.
- Smoke-задержки (10 запросов на endpoint, локально): health p95 = 13 мс,
  каталог p95 = 112 мс, главная p95 = 124 мс, поиск p95 = 197 мс.
- За последний час: 969 ответов 200, 26 client-abort 499, 2 ответа 502
  (0,2 %). Всплеск 502 в 03:00–04:00 совпал с деплоем/рестартом gateway.
- Ошибок уровня `err` в journald за 24 часа: 0 по всем 11 юнитам.
- `Restart=always`, `NRestarts=0`; последние старты — 12.11 04:58–05:38 UTC.

---

## 3. Находки

### 3.1 Критично

1. **Бэкапов проекта нет.**
   - `/root/backups/db` содержит только старые базы другого проекта
     (`air-20261026…`, `app-20261027…`), последний файл — 27.10.2026.
   - Нет cron, systemd-таймера, borg/restic, snapshot-политики для
     `/opt/mangapoisk-reborn/data`.
   - `data/replica` — это локальная реплика на том же диске; она не защищает
     от потери диска/сервера и не является offsite-бэкапом.
   - Доказательств успешного restore нет. Issue: **#51**.

2. **Сервер фактически без firewall, replica API опубликован наружу.**
   - `ufw status` → `inactive`; цепочки INPUT/FORWARD/OUTPUT в политике ACCEPT
     (кроме tailscale-правил).
   - `mangapoisk-replica` слушает `0.0.0.0:8108`; внешняя проверка
     `http://85.192.37.58:8108/health` вернула **200**.
   - `/internal/replica/*` защищён `X-Internal-Token`, но сервис не должен
     быть доступен из интернета. Issue: **#52**.

3. **RAM на пределе, swap = 0.**
   - 3,9 ГБ total, 3,1 ГБ used, available 755 МБ; `vm.swappiness=60`, но swap
     не подключён.
   - Крупнейший потребитель — `control`: RSS ~993 МБ (24,7 % RAM), затем
     `scheduler` 197 МБ, `catalog` 174 МБ, `media` 169 МБ.
   - Любой всплеск (импорт, экспорт, crawl) приводит к OOM-kill без swap.
     Issue: **#53**.

### 3.2 Высокий риск

4. **Нет алертов.** Telegram настроен, но notifier отправляет только
   «новые главы». Нет проверки down, 5xx, диска, backup fail, crawler stalled.
   При падении сервиса узнаем только от пользователей. Issue: **#54**.

5. **MangaLib-краулер падает.**
   - full: страница 201, `NotFoundError: MangaLib: resource not found`,
     `items_seen=12000`, `total_pages` не определён;
   - incremental: `UpstreamError: Upstream returned HTTP 403`.
   - Повтор каждые 900 с без circuit breaker. Это и потеря данных, и лишняя
     нагрузка на источник. Issue: **#55**.

6. **Очередь обогащения 27 597 тайтлов (95 %).**
   - mangalib 11 552, remanga 9 923, mangapoisk 6 122.
   - Полный обход сбрасывает `last_synced_at` для всех тайтлов источника
     (`reset-enrichment`), после чего enrichment идёт с concurrency 2 и
     batch 50. При текущем темпе это многие часы; дашборд показывает backlog.
   - Это не ошибка сама по себе, но метрика должна быть видимой и иметь
     порог. Issue: **#57**.

7. **Кэш изображений без LRU.**
   - `media-cache` = 1,8 ГБ и растёт; лимита нет, очистка только экспортов.
   - Архив глав имеет лимит `25 GiB` (`ARCHIVE_MAX_BYTES`) и LRU, но
     eviction запускается только при старте и после записи новой главы.
   - На диске 59 ГБ; при 50k тайтлов и росте кэша места останется мало.
     Issue: **#56**.

### 3.3 Средний риск

8. **SQLite и один писатель.** `catalog.db` 149 МБ, `archives.db` 1,7 МБ.
   При чтении ad-hoc во время crawl получено `database is locked` — это
   ожидаемо для rollback-journal SQLite под записью. Репликация есть, но
   переключение — ручное. Issue: **#58**.

9. **`control` потребляет ~1 ГБ RSS.** Для сервиса, который делает health
   checks и SSH-деплой, это много; нужен профиль/лимит и проверка утечки.
   Часть issue #53.

10. **`nginx.service` в failed.** Production-сайт обслуживает отдельный
    standalone nginx (`mangapoisk-web`, :8088/:8443), поэтому сайт работает,
    но системный юнит создаёт ложный сигнал в мониторинге. Низкий приоритет.

11. **Нет p95/error-rate метрик.** Есть только access log без
    `$request_time`; p95 считается только ручным smoke-тестом. Дашборд
    краулера добавлен, но HTTP-метрики требуют Prometheus/OTel или
    log-based экспортёра. Issue: **#58**.

12. **331 failed-архив.** Все записи помечены `Сервис был перезапущен`:
    `_startup_sync` переводит `queued/running` в `failed` при рестарте.
    Это ожидаемое поведение, но failed-главы не перезапускаются
    автоматически. Дашборд показывает счётчик; нужен retry-политика.

---

## 4. Бэкапы и restore

### 4.1 Что нужно бэкапить

| Данные | Путь | Размер (12.11) | Частота | Retention |
|---|---|---:|---|---|
| Каталог | `data/catalog.db` | 149 МБ | каждые 6 ч + перед деплоем | 7 daily, 4 weekly, 3 monthly |
| Библиотека | `data/library.db` | 112 КБ | каждые 6 ч | то же |
| Комментарии | `data/comments.db` | 108 КБ | каждые 6 ч | то же |
| Control | `data/control.db` | 704 КБ | каждые 6 ч | то же |
| Архив metadata | `data/archives.db` | 1,7 МБ | каждые 6 ч | то же |
| Архив глав | `data/chapter-archives` | 690 МБ | ежедневно (инкрементально) | 14 daily |
| Конфиг | `.env`, `env/*.env` | < 5 КБ | при изменении | 30 версий, шифровать |

`media-cache` и `exports` можно не бэкапить: кэш восстановим, экспорты
живут 48 часов. Но их размер нужно контролировать.

### 4.2 Рекомендуемая схема

- **SQLite:** `sqlite3 <db> ".backup '/backup/<db>-$(date +%F-%H%M).db'"` —
  безопасно при работающем сервисе, в отличие от `cp`.
- **Архив:** `restic`/`borg` с инкрементальным бэкапом
  `data/chapter-archives`, шифрование, offsite (S3/B2/другой хост).
- **Конфиг:** restic snapshot `.env` и `env/`; ключ `CONTROL_SECRET_KEY`
  хранить отдельно от бэкапа.
- **Расписание:** systemd timer `mangapoisk-backup.timer` каждые 6 часов,
  ежедневная проверка `restic check`, ежемесячный restore drill.
- **Алерт:** если последний успешный бэкап старше 26 часов — critical.
- **Проверка:** после каждого бэкапа `PRAGMA integrity_check` на копии;
  раз в месяц поднять staging из бэкапа и сравнить `catalog/stats`.

### 4.3 Restore (черновик, выполнять только на копии/staging)

```bash
# 1. Остановить писателей (на staging, не на production без окна)
systemctl stop mangapoisk-scheduler mangapoisk-catalog mangapoisk-library \
  mangapoisk-media mangapoisk-comments

# 2. Сохранить текущие файлы (не удалять без копии)
ts=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p /opt/mangapoisk-reborn/data.pre-restore-$ts
cp -a /opt/mangapoisk-reborn/data/*.db /opt/mangapoisk-reborn/data.pre-restore-$ts/

# 3. Восстановить БД из restic/копии
restic restore latest --target /tmp/restore --include /opt/mangapoisk-reborn/data
install -o mangapoisk -g mangapoisk -m 640 \
  /tmp/restore/opt/mangapoisk-reborn/data/catalog.db /opt/mangapoisk-reborn/data/catalog.db
# повторить для library.db, comments.db, control.db, archives.db

# 4. Восстановить архив глав
rsync -a --delete /tmp/restore/opt/mangapoisk-reborn/data/chapter-archives/ \
  /opt/mangapoisk-reborn/data/chapter-archives/

# 5. Проверить целостность и поднять сервисы
sqlite3 /opt/mangapoisk-reborn/data/catalog.db "PRAGMA integrity_check;"
systemctl start mangapoisk-catalog mangapoisk-library mangapoisk-media \
  mangapoisk-comments mangapoisk-scheduler
curl -fsS http://127.0.0.1:8100/api/v1/health
curl -fsS -H "X-Internal-Token: $INTERNAL_TOKEN" http://127.0.0.1:8102/internal/stats
```

**Критерий успеха restore drill:** `/internal/stats` возвращает непустые
`manga/chapters`, `/api/v1/health` = ok, выборочная глава открывается из
архива, запись в `docs/BACKUP_DRILL.md` с датой, длительностью и checksum.

---

## 5. Алерты и пороги

Пока алертов нет. Минимальный набор (внешний uptime-монитор + systemd
`OnFailure` + скрипт, дергающий notifier):

| Алерт | Условие | Severity | Действие |
|---|---|---|---|
| Сервис down | `/health` != 200 > 2 мин | critical | рестарт по runbook, эскалация |
| 5xx rate | > 2 % за 5 мин | high | смотреть gateway/upstream, откат |
| p95 latency | > 2 с за 10 мин | high | проверить catalog/DB |
| Диск | > 80 % warning, > 90 % critical | high | очистка кэша/экспортов, расширение |
| RAM available | < 10 % или OOM-kill | high | рестарт control, добавить swap/RAM |
| Backup fail | нет успешного бэкапа > 26 ч | critical | проверить timer/restic |
| Crawler stalled | running и нет прогресса > 30 мин | high | source 403/404, circuit breaker |
| Crawler failed | status=failed | high | разобрать `last_error`, не долбить источник |
| Enrichment backlog | > 10 000 | warning | проверить worker/concurrency |
| Archive LRU | usage > 80 % | warning | расширить диск/лимит, проверить eviction |
| Media cache | > 10 ГБ | warning | добавить LRU/очистку |
| SQLite lock | > 5 ошибок/мин | high | проверить writers, WAL, размер |
| TLS | < 14 дней | warning | certbot renew |
| Replica lag | snapshot старше 10 мин | high | проверить replica/sync |

Notifier уже умеет `POST /internal/notify` (Telegram). Достаточно добавить
`ALERT_CHAT_ID`/второй канал и не смешивать с лентой новых глав.

---

## 6. Стоимость

### 6.1 Что есть сейчас

| Компонент | Факт | Оценка, USD/мес |
|---|---|---:|
| App VPS | 2 vCPU (Ryzen 9 7950X3D), 4 ГБ RAM, 60 ГБ ext4; PTR `*.ptr.network` (PQ.Hosting и похожие) | 6–10 |
| Jump VPS | 1 vCPU, 2 ГБ RAM, 30 ГБ | 3–5 |
| Replica | тот же app-хост (порт 8108); отдельной машины нет | 0 |
| Домен | `85.192.37.58.nip.io` — бесплатный wildcard DNS | 0 |
| TLS | Let's Encrypt/certbot | 0 |
| CDN | нет, nginx отдаёт напрямую | 0 |
| Бэкапы | **нет** (после внедрения +2–4) | 0 → 2–4 |
| **Итого сейчас** | | **9–15** (после бэкапов 11–19) |

Допущения: цены — рыночный диапазон для 2 vCPU/4 ГБ и 1 vCPU/2 ГБ в
2026; точный тариф провайдера в репозитории не зафиксирован. Трафик
сейчас небольшой (~360 запросов/час фоном + всплески деплоя), egress не
тарифицируется отдельно.

### 6.2 Прогноз

| Сценарий | Конфигурация | Оценка, USD/мес | Комментарий |
|---|---|---:|---|
| Сейчас (28,9k тайтлов) | 2 vCPU / 4 ГБ / 60 ГБ + jump | 9–19 | впритык по RAM; бэкапы обязательны |
| 10k тайтлов | 2 vCPU / 4 ГБ / 60–80 ГБ + jump | 10–20 | меньше текущего каталога; запас по диску |
| 50k тайтлов | 4 vCPU / 8 ГБ / 100–160 ГБ + jump | 25–45 | +бэкап-хранилище 50 ГБ (2–5), CDN опционально |
| 50k + CDN 1 ТБ | то же + Bunny/Cloudflare | 30–60 | egress 1 ТБ ≈ 5–15 |
| 50k + CDN 10 ТБ | то же + CDN | 75–150 | egress 10 ТБ ≈ 50–150; зависит от картинок |

Расчёт роста: `catalog.db` 149 МБ на 28,9k тайтлов ≈ 5,2 КБ/тайтл
(metadata+индексы); 50k ≈ 260 МБ. Архив глав ограничен 25 GiB LRU;
медиа-кэш нужно ограничить 10 ГБ. Итого data ≈ 40 ГБ, плюс OS/логи/запас
→ диск 100–160 ГБ. RAM 8 ГБ нужен из-за `control` (~1 ГБ) и пиков
crawler/enrichment. CPU 4 vCPU — для пиков импорта и WebP-конвертации.

---

## 7. Нагрузка на источники

- `SCRAPER_REQUESTS_PER_MINUTE=36` (1 запрос / 1,67 с), crawler дополнительно
  ставит `burst=1` и `CATALOGUE_CRAWL_DELAY_SECONDS=1,75`.
- `scraper_max_retries=3`, backoff `1,5 × 2^n` c jitter, `Retry-After`
  учитывается, максимум 30 с. Повторяются 429/500/502/503/504; 403 не
  повторяется.
- Full crawl: MangaPoisk завершён (163/163 страниц, 6 484 импорта),
  Remanga идёт (340 страниц, 10 168 найдено, 10 167 импортировано,
  `total_pages` неизвестен), MangaLib failed на 201-й странице (404) и
  incremental 403.
- Incremental: каждые 900 с, 2 страницы `updated` + `popular`; full —
  раз в 7 дней.
- Вывод: лимиты вежливые, но MangaLib-ретраи каждые 15 минут при 403 —
  лишняя нагрузка. Нужен circuit breaker: после 2–3 подряд 403/404
  останавливать источник до ручного вмешательства/обновления cookie.

---

## 8. Дашборд «Состояние краулера»

Добавлен в `/admin` (секция после верхних карточек, перед инвентарём).

- API: `GET /api/v1/admin/crawl` (admin JWT). Собирает:
  - `catalog /internal/stats` — тайтлы, главы, pending по источникам;
  - `catalog /internal/crawl-state` — full/incremental cursor, страница,
    ETA, ошибки, last/next run;
  - `media /internal/stats` — архив (done/failed/pending/bytes/cap),
    кэш изображений.
- Панель обновляется каждые 15 с и показывает:
  - сводку: тайтлы, главы, очередь обогащения, архив, кэш;
  - карточки источников: прогресс, страница/всего, ETA, импорт, очередь,
    последняя ошибка, следующий запуск;
  - предупреждения: failed-обход, stalled > 15 мин, backlog ≥ 5 000,
    архив ≥ 80 %.
- ETA считается в crawler при каждом сохранении страницы
  (`eta_seconds`) и дублируется клиентским fallback по двум снимкам.
- Секретов endpoint не отдаёт: только счётчики, статусы и тексты ошибок.

Скриншоты QA: `docs/screenshots/ops-admin-crawler-desktop-1440.png`,
`ops-admin-crawler-mobile-390.png` (заполняются после browser QA).

---

## 9. Runbook

### 9.1 Ежедневно (5 минут)

```bash
# на app-хосте
systemctl --no-pager --failed
for s in gateway parser catalog library media control notifier replica comments scheduler web; do
  systemctl is-active "mangapoisk-$s"; done
curl -fsS http://127.0.0.1:8100/api/v1/health
free -m; df -h /
journalctl -u 'mangapoisk-*' --since '24 hours ago' -p err --no-pager
```

Открыть `/admin` → «Состояние краулера»: проверить failed/stalled/backlog.

### 9.2 Сервис не отвечает

1. `systemctl status mangapoisk-<service> --no-pager -l`.
2. `journalctl -u mangapoisk-<service> -n 200 --no-pager`.
3. Проверить `df -h`, `free -m` (OOM?).
4. Если это gateway — проверить `/api/v1/health` и nginx upstream.
5. Рестарт — только по согласованию с lead; не делать массовый рестарт
   всех юнитов.
6. После рестарта: `/health`, `crawl-state`, выборочная глава.

### 9.3 Краулер встал / источник 403

1. `systemctl status mangapoisk-scheduler`.
2. `journalctl -u mangapoisk-scheduler -n 300 | grep -E 'catalogue|403|404'`.
3. `curl -fsS -H "X-Internal-Token: $TOKEN" http://127.0.0.1:8102/internal/crawl-state`.
4. Не запускать массовый retry вручную. Для MangaLib — проверить cookie,
   robots, 403; включить circuit breaker (issue #55).
5. Если источник легально недоступен — отключить его в `CATALOGUE_SOURCES`
   и зафиксировать в `docs/SOURCES.md`.

### 9.4 Диск растёт

1. `du -sh /opt/mangapoisk-reborn/data/* | sort -h`.
2. `media-cache` — добавить/включить LRU (issue #56), сейчас лимита
   нет.
3. `exports` — проверить TTL (48 ч) и `maintenance/cleanup`.
4. `chapter-archives` — проверить `ARCHIVE_MAX_BYTES=25GiB` и eviction:
   `GET /internal/stats` на media.
5. Не удалять `catalog.db`/`archives.db` вручную.

### 9.5 Деплой (только lead)

Деплой не выполнялся. Перед деплоем: бэкап БД, `pytest`, `ruff`,
`npm run typecheck && npm run build`, затем штатный control deploy.
После — `health`, `/admin/crawl`, проверить 5xx 15 минут.

---

## 10. Что сделано в этой ветке

- `GET /api/v1/admin/crawl` — снимок краулера/архива для админки.
- `GET /internal/stats` в media — архив и кэш.
- `pending` в `/internal/stats` catalog.
- `eta_seconds` в crawl state (миграция additive).
- Панель «Состояние краулера» (desktop/mobile).
- Тесты: gateway merge, media stats, catalog pending/ETA, scheduler ETA.
- Этот документ.

## 11. Открытые задачи

Созданы по этому аудиту:

| Issue | Severity | Тема | Owner |
|---|---|---|---|
| [#51](https://github.com/geekAmis/mangapoiskAPI/issues/51) | CRITICAL | Нет бэкапов/restore drill | DevOps/backend |
| [#52](https://github.com/geekAmis/mangapoiskAPI/issues/52) | CRITICAL | Firewall выключен, replica наружу | DevOps/security |
| [#53](https://github.com/geekAmis/mangapoiskAPI/issues/53) | HIGH | RAM/swap/control RSS | DevOps/backend |
| [#54](https://github.com/geekAmis/mangapoiskAPI/issues/54) | HIGH | Нет алертов | DevOps |
| [#55](https://github.com/geekAmis/mangapoiskAPI/issues/55) | HIGH | MangaLib 403/404 | Backend/parser |
| [#56](https://github.com/geekAmis/mangapoiskAPI/issues/56) | HIGH | LRU кэша/архива | Backend/media |
| [#57](https://github.com/geekAmis/mangapoiskAPI/issues/57) | HIGH | Enrichment backlog | Backend/catalog |
| [#58](https://github.com/geekAmis/mangapoiskAPI/issues/58) | MEDIUM | SQLite lock и p95/5xx метрики | Backend/DevOps |

---

# 2. Медиа-хранилище и LRU

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

---

# 3. Firewall, off-host backup and swap guardrails

Runbook from PR #62 (draft). Production evidence from 2026-11-12 UTC.
Credentials are never stored in the repository: scripts read the restic
password from `RESTIC_PASSWORD_FILE` (default `/root/.restic-password`) and
access details stay in the workspace access file.

Last verified: 2026-11-12 (UTC).  Scope: production nodes `primary-85`,
`jump-83` and `aeza-2`.  Credentials are **not** stored in this repository;
use the workspace access file and never commit passwords, tokens or private
keys.

## 1. Topology

| Name | Public address | Role | Notes |
| --- | --- | --- | --- |
| `primary-85` | `85.192.37.58` | Main writer: catalog, library, comments, control, gateway, parser, media, scheduler, replica | Tailscale `100.119.186.58`. Reached through `jump-83`. |
| `jump-83` | `83.141.92.137` | Jump host + warm standby: library, media, replica; Caddy; xray/tagasay | 2 GB RAM, 1 GB swap added 2026-11-12. |
| `aeza-2` | `85.192.30.224` | Fallback writer: catalog, library, media, parser, gateway, replica; nginx | Already had 4 GB swap. Reached with the credentials in the control inventory. |

Replica service listens on `8108`.  Every node pulls SQLite snapshots from the
healthy leader selected from the control registry
(`http://85.192.37.58:8088/api/v1/registry`).  `jump-83` and `aeza-2` pull from
`primary-85`; `primary-85` snapshots its own live files.

`primary-85` binds application services to `127.0.0.1`.  `jump-83` and `aeza-2`
bind fallback services to `0.0.0.0`, because they are selected by the control
registry.  Firewall rules preserve the existing fallback endpoints.

## 2. Access

```bash
# jump host
ssh root@83.141.92.137

# primary through the jump host (local port forward is the stable path)
ssh -J root@83.141.92.137 root@85.192.37.58
```

The workspace `data.txt` contains the current root passwords.  Do not copy it
to the repository, shell history, tickets or chat.  For automation, use the
dedicated `mpbackup` key described in §4.

## 3. Firewall (UFW)

UFW is active on all three nodes with `default deny incoming` and
`default allow outgoing`.  Rules were added **before** enabling, a five-minute
dead-man rollback timer was armed, and a second SSH session plus external
checks were used before the timer was cancelled.

### 3.1 Current rules

`primary-85`:

```text
22/tcp                         ALLOW IN  Anywhere      # SSH
80/tcp                         ALLOW IN  Anywhere      # ACME HTTP (certbot webroot/standalone)
8088/tcp                       ALLOW IN  Anywhere      # MangaPoisk HTTP
8443/tcp                       ALLOW IN  Anywhere      # MangaPoisk HTTPS
8080/tcp                       ALLOW IN  Anywhere      # existing ytdl service
8108/tcp                       ALLOW IN  83.141.92.137  # jump-83 replica
8108/tcp                       ALLOW IN  85.192.30.224  # aeza-2 replica
8108/tcp                       ALLOW IN  100.64.0.0/10  # tailscale replica
Anywhere on tailscale0         ALLOW IN  Anywhere      # tailscale interface
41641/udp                      ALLOW IN  Anywhere      # tailscale direct
```

`jump-83`:

```text
22/tcp                         ALLOW IN  Anywhere      # SSH
80/tcp                         ALLOW IN  Anywhere      # ACME HTTP / Caddy
443/tcp                        ALLOW IN  Anywhere      # HTTPS / Caddy
8080/tcp                       ALLOW IN  Anywhere      # existing tagasay service
8103/tcp                       ALLOW IN  Anywhere      # library fallback
8104/tcp                       ALLOW IN  Anywhere      # media fallback
8443/tcp                       ALLOW IN  Anywhere      # existing xray service
8108/tcp                       ALLOW IN  85.192.37.58   # primary-85 replica
8108/tcp                       ALLOW IN  85.192.30.224  # aeza-2 replica
```

`aeza-2`:

```text
22/tcp     ALLOW IN  Anywhere   # SSH
80/tcp     ALLOW IN  Anywhere   # HTTP nginx
443/tcp    ALLOW IN  Anywhere   # HTTPS nginx
8080/tcp   ALLOW IN  Anywhere   # existing ytdl service
1107/tcp   ALLOW IN  Anywhere   # existing node service
1108/tcp   ALLOW IN  Anywhere   # existing node service
8875/tcp   ALLOW IN  Anywhere   # gateway fallback
8904/tcp   ALLOW IN  Anywhere   # catalog fallback
8905/tcp   ALLOW IN  Anywhere   # media fallback
8907/tcp   ALLOW IN  Anywhere   # library fallback
8908/tcp   ALLOW IN  Anywhere   # parser fallback
8909/tcp   ALLOW IN  Anywhere   # media fallback
9179/tcp   ALLOW IN  Anywhere   # existing pyneon service
8108/tcp   ALLOW IN  85.192.37.58   # primary-85 replica
8108/tcp   ALLOW IN  83.141.92.137  # jump-83 replica
```

Ports `8103/8104` on `jump-83` and the `8875/8904/8905/8907/8908/8909`
fallback ports on `aeza-2` remain public to preserve the current failover
behaviour.  They are not part of the replica exposure and are listed as a
follow-up hardening item.

### 3.2 Safe change procedure

Never enable UFW in a single blind step.  Use this sequence on each node:

```bash
# 0. Back up state (root only)
ts=$(date -u +%Y%m%dT%H%M%SZ)
dir=/root/backups/ops-$(date -u +%Y%m%d)/$(hostname -s)
install -d -m 700 "$dir"
ufw status verbose     > "$dir/ufw-status-$ts.txt" 2>&1 || true
iptables-save          > "$dir/iptables-$ts.txt"   2>/dev/null || true
ip6tables-save         > "$dir/ip6tables-$ts.txt"  2>/dev/null || true
tar czf "$dir/etc-ufw-$ts.tar.gz" /etc/ufw

# 1. Add every rule while UFW is still inactive
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
# ... add the host-specific rules from §3.1 ...

# 2. Arm a dead-man rollback before enabling
systemd-run --unit=ufw-rollback --on-active=300 \
  --timer-property=AccuracySec=1s /usr/sbin/ufw --force disable

# 3. Enable and verify in the same SSH session
ufw --force enable
ufw status verbose
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8088/health
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8108/health

# 4. From a second connection and from an external host, verify SSH and the
#    intended public endpoints, then cancel the dead-man:
systemctl stop ufw-rollback.timer
systemctl reset-failed ufw-rollback.service
```

If a mistake is made, do **not** wait for the timer:

```bash
ufw --force disable          # immediate rollback
tar xzf /root/backups/ops-*/<host>/etc-ufw-*.tar.gz -C /
ufw --force enable           # only after the rules are corrected
```

### 3.3 Verification

From a machine outside the production network:

```bash
curl --max-time 5 -sS -o /dev/null -w '%{http_code}\n' http://85.192.37.58:8108/health   # expected 000/timeout
curl --max-time 5 -sS -o /dev/null -w '%{http_code}\n' http://83.141.92.137:8108/health  # expected 000/timeout
curl --max-time 5 -sS -o /dev/null -w '%{http_code}\n' http://85.192.30.224:8108/health  # expected 000/timeout
curl --max-time 5 -sS -o /dev/null -w '%{http_code}\n' http://85.192.37.58:8088/health  # expected 200
curl --max-time 5 -sk -o /dev/null -w '%{http_code}\n' https://85.192.37.58.nip.io:8443/health # expected 200
```

Between nodes (must still work):

```bash
# from jump-83
curl -sS http://85.192.37.58:8108/health
# from aeza-2
curl -sS http://85.192.37.58:8108/health
curl -sS http://83.141.92.137:8108/health
# from primary-85
curl -sS http://85.192.30.224:8108/health
```

Replication health:

```bash
TOKEN=$(grep '^INTERNAL_TOKEN=' /opt/mangapoisk-reborn/.env | cut -d= -f2-)
curl -sS -H "X-Internal-Token: $TOKEN" http://127.0.0.1:8108/internal/replica/status \
  | python3 -m json.tool | head -40
```

The `last_success_at` value must advance and `last_error` must stay `null`.
Catalog snapshots are large; a pull can take several minutes on a slow link.

## 4. Backups and restore

### 4.1 Design

* Restic repository: `sftp:mpbackup-jump:/srv/mangapoisk-backups/restic` on
  `jump-83` (off-host from `primary-85`).  Restic encrypts client-side.
* Repository password: `/root/.restic-password` (mode 0600) on `primary-85`
  and a root-only copy on `jump-83` for disaster recovery.  Store a copy in the
  team password manager; losing it makes the repository unrecoverable.
* Dedicated backup account: `mpbackup` on `jump-83`, home
  `/srv/mangapoisk-backups`, shell `/bin/sh`, key restricted with
  `restrict,command="/usr/lib/openssh/sftp-server"` in
  `/srv/mangapoisk-backups/.ssh/authorized_keys`.  Only the SFTP subsystem is
  usable.
* Primary key: `/root/.ssh/mpbackup_ed25519`; SSH alias `mpbackup-jump` in
  `/root/.ssh/config`.

Backup scope:

* SQLite databases snapshotted with `.backup` (online backup API) and checked
  with `PRAGMA integrity_check`: `catalog.db`, `library.db`, `comments.db`,
  `control.db`, `archives.db` (media metadata).
* `chapter-archives/` (user-downloaded ZIPs).
* Critical config: `.env`, `env/*.env`, nginx config, systemd units,
  `source-cookies.json`, `/etc/ufw`, `/etc/ssh/sshd_config`, `/etc/fstab`,
  `/etc/sysctl.d`, `/etc/letsencrypt`.
* Not backed up: `media-cache/` (regenerable), `data/replica/` (derived
  snapshots), `exports/` (transient).  This keeps the backup near 1 GB instead
  of >3 GB.
* The timer runs on `primary-85` because it is the writer.  `jump-83` and
  `aeza-2` hold replicated snapshots and fallback copies; after a promotion,
  install/enable the same timer on the new writer and add its live data to the
  scope.

### 4.2 Schedule and retention

* `mangapoisk-backup.timer` runs at `00:15, 06:15, 12:15, 18:15 UTC`
  (`Persistent=true`, random delay up to 5 min).  RPO is therefore **≤ 6 h**
  for databases and archives.
* Retention: **7 daily + 4 weekly + 3 monthly** (`restic forget --prune` at most
  once per UTC day).
* Weekly repository check: `restic check --read-data-subset=2%`.
* Log: `/var/log/mangapoisk-backup.log`, rotated weekly by
  `/etc/logrotate.d/mangapoisk-backup` (8 rotations).  Also in the journal:
  `journalctl -u mangapoisk-backup`.

### 4.3 Manual commands

```bash
# run a backup now
/usr/local/sbin/mangapoisk-backup.sh
tail -50 /var/log/mangapoisk-backup.log

# inspect snapshots
restic -r sftp:mpbackup-jump:/srv/mangapoisk-backups/restic \
  --password-file /root/.restic-password snapshots

# timer status
systemctl list-timers mangapoisk-backup.timer
systemctl status mangapoisk-backup.service

# restore drill (isolated /var/tmp; never touches production)
/usr/local/sbin/mangapoisk-restore-drill.sh latest

# disaster-recovery drill from jump-83 (local repository)
RESTIC_REPOSITORY=/srv/mangapoisk-backups/restic \
  /usr/local/sbin/mangapoisk-restore-drill.sh latest
```

The restore drill restores the latest snapshot under
`/var/tmp/mangapoisk-restore-drill-<timestamp>`, verifies every SQLite file with
`PRAGMA integrity_check`, compares every `row.<db>.<table>=<count>` entry from
`MANIFEST.txt`, and checks the ZIP count.  It prints `RESTORE DRILL PASS` only
when all checks succeed.  Remove the target after reviewing:

```bash
rm -rf /var/tmp/mangapoisk-restore-drill-*
```

### 4.4 Restore procedure (production, planned)

1. Announce the maintenance window and stop the writers for the databases being
   restored:
   ```bash
   systemctl stop mangapoisk-catalog mangapoisk-library mangapoisk-comments \
     mangapoisk-media mangapoisk-scheduler
   ```
2. Restore the snapshot into a staging directory (same command as the drill).
3. Verify `PRAGMA integrity_check` and row counts.
4. Copy the verified database over the live file, keeping a `.bak`:
   ```bash
   install -o mangapoisk -g mangapoisk -m 640 \
     /var/tmp/mangapoisk-restore-drill-*/var/tmp/mangapoisk-backup/db/catalog.db \
     /opt/mangapoisk-reborn/data/catalog.db
   ```
   Repeat for `library.db`, `comments.db`, `control.db`, `archives.db`.
5. Restore `chapter-archives/` if needed:
   ```bash
   rsync -a --delete \
     /var/tmp/mangapoisk-restore-drill-*/opt/mangapoisk-reborn/data/chapter-archives/ \
     /opt/mangapoisk-reborn/data/chapter-archives/
   ```
6. Restore config from the snapshot if the host was rebuilt, then
   `systemctl daemon-reload` and start the services.
7. Verify `/health`, `/ready`, the gateway registry, and replica status.

RTO: about **15–30 minutes** for the databases, **30–60 minutes** including
chapter archives and validation on a healthy host.  A bare-metal rebuild is
longer and depends on OS/package installation.

### 4.5 Monitoring

* `systemctl list-timers mangapoisk-backup.timer` — next run.
* `systemctl status mangapoisk-backup.service` — last result.
* `journalctl -u mangapoisk-backup -n 100` — errors.
* `restic snapshots` — latest snapshot age (alert if > 12 h).
* `restic check` — repository integrity (weekly, logged).
* `df -h /srv` on `jump-83` — repository space.
* A failed backup does not stop services; it leaves the previous snapshot in
  place.  Escalate if two consecutive runs fail.
* The repository is on a separate host but in the same provider/region.  For
  geographic DR, replicate the restic repository to S3-compatible object
  storage as a next step.

### 4.6 Off-host configuration copies

The pre-change configuration for each node is stored under
`/root/backups/ops-20261112/<host>/` and copied off-host:

* `primary-85` → `jump-83:/root/backups/ops-20261112/offhost/primary-85/`
* `jump-83` → `primary-85:/root/backups/ops-20261112/jump-83-offhost/`
* `aeza-2` → `primary-85:/root/backups/ops-20261112/aeza-2/` and
  `jump-83:/root/backups/ops-20261112/offhost/aeza-2/`

These directories are root-only (0700).  The unencrypted configuration tars
must never live in `/srv/mangapoisk-backups` (the `mpbackup` home); only the
encrypted restic repository belongs there.

Each directory contains UFW state, iptables/ip6tables, listening sockets,
systemd unit list, `/etc/fstab`, sysctl, SSH config and the app config tar
(secrets included, mode 0600).

## 5. Memory and swap

### 5.1 Swap

| Host | Swap | swappiness | File |
| --- | --- | --- | --- |
| `primary-85` | 2 GB | 10 | `/swapfile` |
| `jump-83` | 1 GB | 10 | `/swapfile` |
| `aeza-2` | 4 GB (pre-existing) | 60 | provider default |

Persistence is via `/etc/fstab`:

```text
/swapfile none swap sw 0 0
```

`/etc/sysctl.d/99-mangapoisk-memory.conf` sets `vm.swappiness = 10` on
`primary-85` and `jump-83`.  Verify:

```bash
swapon --show
free -m
sysctl vm.swappiness
grep swapfile /etc/fstab
```

### 5.2 Control-plane guardrail

`mangapoisk-control` showed a 910 MB RSS high-water on 2026-11-12 (252 MB →
910 MB over about 35 minutes).  After a controlled restart it grew to ~170 MB
and then stayed flat for the rest of a 10-minute sample; the 910 MB peak was
not reproduced without deployment activity.  A 24-hour observation and
metrics are tracked in issue #59.  The service is protected with a systemd
drop-in regardless:

```text
/etc/systemd/system/mangapoisk-control.service.d/memory.conf
[Service]
MemoryAccounting=yes
MemoryHigh=1G
MemoryMax=1536M
```

`MemoryHigh` reclaims/throttles first; `MemoryMax` is a safety valve that
restarts the service instead of letting the host OOM-kill other services.  The
runtime values were applied with `systemctl set-property --runtime` so no
restart was needed.  Check:

```bash
systemctl show mangapoisk-control -p MemoryCurrent,MemoryHigh,MemoryMax,MemoryPeak
```

Root cause and permanent fix (shared `httpx.AsyncClient` for the 10-second
health loop; avoid per-check client creation) are tracked in the follow-up
issue.  Do not raise `MemoryMax` without fixing the leak.

## 6. Replication

`8108` is reachable only from the peer allowlist.  The registry advertises
public replica URLs, so the firewall rules must include every node that may
pull:

* `primary-85` allows `jump-83` and `aeza-2`.
* `jump-83` allows `primary-85` and `aeza-2`.
* `aeza-2` allows `primary-85` and `jump-83`.

If a new node is added to the control inventory with a replica service, add its
public IP to every peer's UFW rule **before** enabling replication:

```bash
ufw allow from <new-node-ip> to any port 8108 proto tcp comment '<name> replica'
```

After a firewall change, verify a full sync from the peer, not only `/health`:

```bash
TOKEN=$(grep '^INTERNAL_TOKEN=' /opt/mangapoisk-reborn/.env | cut -d= -f2-)
curl -sS -H "X-Internal-Token: $TOKEN" http://127.0.0.1:8108/internal/replica/status
```

## 7. Incident checklist

1. Is the site down? Check `curl -k https://85.192.37.58.nip.io:8443/health`,
   then each service's `/health` on `127.0.0.1`.
2. Is the firewall the cause? `ufw status verbose`; check the allowlist and
   `/var/log/ufw.log`.  Disable UFW only as a last resort and immediately
   re-enable with corrected rules.
3. Is memory the cause? `free -m`, `swapon --show`,
   `journalctl -k | grep -i oom`, `systemctl status mangapoisk-control`.
4. Is replication stale? Compare `last_success_at` on each replica; test the
   peer's `/health` and `/internal/replica/status`; check UFW.
5. Is the backup stale? `restic snapshots`; check the timer and log.  A stale
   backup is not a production outage, but escalate before the next change.
6. Restore only into `/var/tmp` until the verified copy is ready.  Keep the
   previous live file as `.bak` during a planned restore.

## 8. Rollback quick reference

Every change below is reversible.  Run commands on the named host as root.

**UFW:**

```bash
ufw --force disable
tar xzf /root/backups/ops-20261112/<host>/etc-ufw-before*.tar.gz -C /
ufw --force enable
```

If SSH is lost, wait for the five-minute `ufw-rollback` dead-man timer or use
the provider console.  Keep the current SSH session open during any firewall
change.

**Backups:**

```bash
systemctl disable --now mangapoisk-backup.timer
rm -f /etc/systemd/system/mangapoisk-backup.service \
      /etc/systemd/system/mangapoisk-backup.timer \
      /etc/systemd/system/mangapoisk-restore-drill.service
rm -f /usr/local/sbin/mangapoisk-backup.sh \
      /usr/local/sbin/mangapoisk-restore-drill.sh
systemctl daemon-reload
```

The restic repository on `jump-83` is not deleted by the rollback; it is the
off-host copy.  Delete it only with explicit approval.

**Swap:**

```bash
swapoff /swapfile
sed -i '\|^/swapfile[[:space:]]|d' /etc/fstab
rm -f /swapfile /etc/sysctl.d/99-mangapoisk-memory.conf
sysctl --system
```

**Control memory guardrail:**

```bash
rm -f /etc/systemd/system/mangapoisk-control.service.d/memory.conf
systemctl daemon-reload
systemctl set-property --runtime mangapoisk-control.service \
  MemoryHigh=infinity MemoryMax=infinity
```

A restart is not required; the runtime cgroup values change immediately.  The
next service restart uses the persistent drop-in (or no limit after removal).

**Replica allowlist:** remove the peer from the UFW rule on every node that
allowed it:

```bash
ufw delete allow from <peer-ip> to any port 8108 proto tcp
```

## 9. v1.2 search backfill rollout (#63)

`catalog` теперь делает только быстрые schema-изменения на старте.  Строки
каталога нормализуются фоновым воркером; health не ждёт 78k строк.

### 10.1 Backup

SQLite (каталог остановлен или используется online backup):

```bash
sqlite3 /opt/mangapoisk/data/catalog.db ".backup '/root/backups/catalog-$(date +%F-%H%M).db'"
```

PostgreSQL:

```bash
pg_dump "$CATALOG_DATABASE_URL" -Fc -f /root/backups/catalog-$(date +%F-%H%M).dump
```

Не копируйте `catalog.db` вместе с `-wal`/`-shm` во время работы сервиса.

### 10.2 Optional pre-deploy reindex

Можно прогнать заранее, пока каталог остановлен; это сокращает окно фоновой
работы после деплоя:

```bash
cd /opt/mangapoisk
.venv/bin/python scripts/reindex_catalog.py \
  --database-url "$CATALOG_DATABASE_URL" --batch-size 500
```

Ожидаемо: 78 275 строк ≈ 2.5 минуты (≈500 строк/с) после schema+bootstrap
≈1.5 с.  Команда идемпотентна; повторный запуск обработает 0 строк.  `--force`
— только после изменения алгоритма нормализации, `--rebuild-fts` — при
подозрении на повреждённый SQLite FTS.

### 10.3 Deploy and progress

1. Deploy catalog.  `/health` должен стать `ok` за **<10 с**; в логе:
   `catalog startup ready in ...` и `search backfill started in background`.
2. Progress:
   ```bash
   curl -fsS -H "X-Internal-Token: $INTERNAL_TOKEN" \
     http://127.0.0.1:8102/internal/search/backfill | jq
   ```
   Поля: `status`, `total`, `normalized`, `remaining`, `progress_percent`,
   `rate_per_second`, `eta_seconds`, `failed`, `last_error`.
3. `/internal/stats` содержит тот же блок `search_backfill`; gateway
   `/api/v1/admin/crawl` отдаёт его в `search_backfill` и предупреждает при
   `failed`.
4. Search/suggest во время миграции работают по legacy-FTS; тайтлы с
   `search_indexed=false` всё ещё находятся по старым колонкам.
5. `sqlite3 ... "PRAGMA wal_checkpoint(TRUNCATE);"` после завершения, если
   нужно уменьшить `-wal` перед бэкапом.

### 10.4 Rollback

1. Rollback control job to the previous release.
2. Если каталог не стартует или БД повреждена — восстановить backup из 10.1
   (для SQLite удалить `catalog.db-wal`/`catalog.db-shm` перед restore).
3. Если откат на `main b0080b2`: лишние search-колонки/таблицы игнорируются
   старым кодом, но старый код не должен запускаться на БД с активным
   фоновым writer'ом — новый процесс уже остановлен вместе с сервисом.
4. Не откатывать только код без БД, если в ней остались `search_indexed=false`
   после аварии: новый деплой просто продолжит backfill.  Перед повторным
   деплоем проверить `scripts/reindex_catalog.py` на staging-копии.

### 10.5 Ожидаемые числа

| Операция | 78 275 строк |
|---|---|
| schema + indexes + mark | ~0.15 с |
| legacy FTS bootstrap | ~1.2 с |
| lifespan startup | **~1.37 с** |
| процесс → `/health` 200 | **~6.9 с** |
| полный фоновый backfill | ~179 с (≈436 строк/с) |
| повторный запуск | 0 строк |

## 10. Change log

* 2026-11-12: search backfill moved out of catalog startup into a batched,
  resumable worker with WAL/busy_timeout and progress endpoint (#63).
* 2026-11-12: UFW enabled on `primary-85`, `jump-83`, `aeza-2`; `8108`
  restricted to peer IPs; HTTP/HTTPS/SSH and existing services preserved.
* 2026-11-12: encrypted restic backups to `jump-83`, 6-hourly timer,
  7 daily / 4 weekly / 3 monthly retention; restore drills passed on
  `primary-85` and `jump-83`.
* 2026-11-12: 2 GB swap on `primary-85`, 1 GB on `jump-83`,
  `vm.swappiness=10`; control cgroup guardrail `MemoryHigh=1G`,
  `MemoryMax=1536M`.

## 10. Deploy health and stale jobs

Control deploy jobs now use `DEPLOY_HEALTH_TIMEOUT_SECONDS` (default 600s,
allowed 30–7200s) instead of a fixed 80s gate.  Each service's deploy block
prints `HEALTH_WAIT`/`HEALTH_OK`/`HEALTH_FAIL` with the attempt number, so a
long catalog migration stays visible in the job log.

- `DEPLOY_READ_TIMEOUT_SECONDS` (default 900s) bounds silence on the SSH
  stream; a hung channel is closed and the job is failed.
- `DEPLOY_STALE_JOB_SECONDS` (default 1800s) is the job heartbeat limit.
  `last_output_at` and `updated_at` are refreshed by output; stale jobs are
  failed and their channel is closed by the control reaper.
- Cancel a running job with
  `POST /api/v1/admin/jobs/{job_id}/cancel`; do not start another deploy while
  the old job is still `running`.
- `GET /api/v1/admin/jobs/{job_id}` includes `last_output_at`.
- Set `DEPLOY_PRE_START_COMMAND`/`DEPLOY_PRE_START_TIMEOUT_SECONDS` to run a
  release migration after install and before restart when a CLI exists.

Checklist for slow releases: backup first; run the migration/backfill as a
pre-start step; deploy catalog alone and watch health attempts; cancel stale
jobs before retrying; deploy the remaining services; verify `/api/v1/health`,
sitemap/robots and admin panels; roll back and stop if catalog remains
unhealthy.
