# Roadmap

Обновлено 13.11.2026. Отмечено только то, что есть в репозитории или в
production; планы без галочек — не обещания. Эпики:
[#29 (v1.1)](https://github.com/geekAmis/mangapoiskAPI/issues/29) и
[#48 (v1.2)](https://github.com/geekAmis/mangapoiskAPI/issues/48).

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
- [x] Импорт по ссылке из UI
- [x] Docker Compose, systemd-деплой, CI workflow, документация

## 1.1.0 — main, release draft

- [x] Офлайн-библиотека в web/Capacitor: глава или весь тайтл, очередь,
      докачка, удаление, чтение без сети (IndexedDB / Filesystem + Preferences)
- [x] Prepare-then-download: `POST/GET /manga/{id}/prepare`, прогресс
      `prepared/pending/failed`, батчи по 5 глав, persisted queue
- [x] Remanga: адаптер, бесплатные/купленные главы, cookie-store, admin UI +
      импорт `.har`; включать с учётом robots/разрешения источника
- [x] Комментарии к тайтлам: ответы, лайки, спойлеры, жалобы, модерация,
      уведомления
- [x] Archive LRU около 25 GiB; метаданные и обложки не вытесняются
- [x] `DancingSpinner` в кнопках/статусах, boot-loader и route fallback;
      16 GIF вместо круговых спиннеров
- [x] Админка: запрет дефолтного пароля в production, инвалидация админ-сессий
      при смене логина/пароля, `401 admin_session_expired`
- [x] Security hardening: 5 попыток входа за 5 минут, 60-минутный админ-токен,
      rate limit по `X-Real-IP`, проверка DNS/redirect в media
- [x] Server manager: слияние inventory при частичном деплое, сервисы на
      jump-host, потоковый лог, health удалённых узлов, self-deploy
- [x] Приоритетный роутинг: rendezvous hash с весом `priority`, fallback
      последними, jump-хосты после обычных узлов в registry
- [x] HTTPS `https://85.192.37.58.nip.io:8443`; HTTP `:8088` — fallback
- [ ] Общая БД или репликация для настоящего failover каталога/библиотеки
      (in progress; сейчас SQLite на одном узле)
- [ ] Зелёный CI на `main` и публикация `v1.1.0`
- [ ] Пересборка APK под HTTPS и подписанный release APK

## 1.2.0 — main, EPIC #48

- [x] SEO: метаданные на маршрут, JSON-LD, `robots.txt`, динамический sitemap
- [ ] Поиск уровня MangaLib: релевантность, подсказки, фильтры, кэш
- [ ] Удержание: продолжение чтения, рекомендации, серии, streak
- [ ] Уведомления о новых главах: in-app, Web Push, Telegram
- [ ] Профили: карточки, достижения, события, уровни, звания
- [ ] Реклама: провайдеры, ключи, аудитории
- [ ] Похожие тайтлы и публичные подборки
- [ ] Надёжность и стоимость: общая БД/репликация, лимиты, мониторинг
- [ ] Возрастной gate и отдельные каталоги для взрослого контента
- [ ] Финальный аудит перед публичным запуском

## Дальше

- [ ] Alembic-миграции и zero-downtime обновление
- [ ] Redis-backed rate limiting и общий response cache
- [ ] S3-совместимое хранилище для media/exports
- [ ] Полнотекстовый поиск PostgreSQL (`tsvector` + `pg_trgm`)
- [ ] Проверенные MangaDex/ReadManga (сейчас выключены)
- [ ] Web push и Telegram-команды
- [ ] Закладки на конкретную страницу, списки чтения
- [ ] Синхронизация прогресса web ↔ Android в реальном времени
- [ ] Source health и «избранное» в админке
- [ ] Prometheus/Grafana и OpenAPI-генерация клиентов

## Идеи

- Рекомендации по жанрам/истории.
- Публичный read-only API каталога для небольших клиентов.
- EPUB для новелл.
- Discord/Telegram-бот.
