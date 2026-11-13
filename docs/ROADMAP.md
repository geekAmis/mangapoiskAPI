# Roadmap

Обновлено 13.11.2026. Отмечено только то, что есть в production; планы без
галочек — не обещания. Текущий статус запуска — [LAUNCH.md](LAUNCH.md).

## 1.0.0 — released 2026-11-11

- [x] Микросервисы и общие контракты (`manga_common`)
- [x] MangaPoisk adapter end-to-end
- [x] MangaLib: поиск, каталог, карточка, главы и страницы
- [x] React web + Kotlin/Compose клиент
- [x] Офлайн-загрузки в Kotlin-клиенте (Room + WorkManager)
- [x] Аккаунты, библиотека, закладки, прогресс
- [x] Варианты источников и фильтр переводов `source/translator/count`
- [x] Серверный архив глав: SQLite BLOB / ZIP
- [x] Экспорт CBZ / PDF / HTML
- [x] Шесть тем и адаптивная вёрстка
- [x] Админка `/admin`: серверы, SSH-деплой, health, registry, failover
- [x] Node.js/Capacitor Android-сборка
- [x] Docker Compose, systemd-деплой, CI workflow, документация

## 1.1.0 / 1.2.0 — вошли в v1.3.0, отдельных тегов нет

- [x] Офлайн-библиотека в web/Capacitor: глава или весь тайтл, очередь,
      докачка, удаление, чтение без сети (IndexedDB / Filesystem + Preferences)
- [x] Prepare-then-download: `POST/GET /manga/{id}/prepare`, прогресс
      `prepared/pending/failed`, батчи по 5 глав, persisted queue
- [x] Remanga: адаптер, бесплатные/платные главы, cookie-store, admin UI +
      импорт `.har`
- [x] Комментарии к тайтлам: ответы, лайки, спойлеры, жалобы, модерация,
      уведомления
- [x] Archive LRU около 25 GiB; метаданные и обложки не вытесняются
- [x] `DancingSpinner`, boot-loader и route fallback; 16 GIF
- [x] Админка: запрет дефолтного пароля, инвалидация админ-сессий,
      `401 admin_session_expired`
- [x] Security hardening: rate limits, `X-Real-IP`, DNS/redirect в media
- [x] Server manager: partial deploy, jump-host, потоковый лог, self-deploy
- [x] Приоритетный роутинг: rendezvous hash, fallback, jump-хосты
- [x] Поиск v1.2: нормализация, транслит, подсказки, FTS5/`pg_trgm`
- [x] Retention: continue reading, рекомендации, серии, streak
- [x] Уведомления о новых главах: in-app/Telegram; Web Push ограничен WebView
- [x] Профили, XP, достижения, события, приватность
- [x] Реклама: провайдеры, ключи, аудитории, consent
- [x] «Похожее» и публичные подборки
- [x] Возрастной gate и legal-страницы

## 1.3.0 — released 2026-11-13 (`71be724`)

- [x] SEO v2: slug-URL, 301, prerender, noindex, sitemap без 18+
- [x] Yandex ID OAuth с DB-only ключами
- [x] Legal: `/terms`, `/privacy`, `/dmca`, `/contacts`, `/age`
- [x] Catalogue performance: materialised cards, `has_chapters`, p95 stats
- [x] Admin tabs + restricted server console
- [x] Observability, backup `VACUUM INTO`, CI hardening, Pillow 13/cryptography 50
- [x] Reader resume fix (#81)
- [x] Android 1.3.0 signed APK

## 1.3.2 — hotfix, released 2026-11-13 (`affe7d0`)

- [x] Standard ports 80/443, redirects http/www, cert SAN+webroot
- [x] Legacy `:8443` API-only, `:8088` redirect except `/ads.txt`
- [x] Yandex RTB loader/block/provider, `ads.txt` direct 200
- [x] Cookie-only consent banner
- [x] Legal `/privacy` mobile overflow fix
- [x] Android 1.3.2 packaged `www`, API 443 (#84 regression fixed)
- [ ] Android QA completion (#84, paused by owner)
- [ ] GitHub release/APK asset for 1.3.2 (not published)

## Ближайшее

- [ ] Android QA 1.3.2 и публикация APK (#84)
- [ ] Yandex Metrika + traffic panel (#85)
- [ ] РСЯ: включить площадку/блок и повторная модерация после 20.11.2026 (#83)
- [ ] Search author/typo fix (#76)
- [ ] SSH key-only (#78), admin MFA/IP allowlist и CSP tightening (#79)
- [ ] HentaiLib age-gated source (#45, branch ready)
- [ ] AI deploy supervisor (#75, branch ready)
- [ ] Общая БД/репликация для failover каталога/библиотеки
- [ ] Alembic-миграции и zero-downtime обновление
- [ ] Redis-backed rate limiting и общий response cache
- [ ] S3-совместимое хранилище для media/exports
- [ ] Проверенные MangaDex/ReadManga (сейчас выключены)

## Идеи

- Публичный read-only API каталога для небольших клиентов.
- EPUB для новелл.
- Discord/Telegram-бот.
- Закладки на конкретную страницу, списки чтения.
- Синхронизация прогресса web ↔ Android в реальном времени.
