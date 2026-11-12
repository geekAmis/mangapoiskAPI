# OPS — надёжность, бэкапы, алерты и стоимость

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
