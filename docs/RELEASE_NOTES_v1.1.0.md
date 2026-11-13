# MangaPoisk Reborn 1.1.0 — черновик release notes

> **Статус: historical draft.** Тег `v1.1.0` не создавался; работа вошла в
> `v1.3.0`. Текст сохранён как история. Порты `:8443`/`:8088` в этом файле
> устарели: production v1.3.2 работает на 80/443, `:8443` — legacy API для
> APK 1.3.0, `:8088` — redirect (кроме `/ads.txt`).

## Что нового

1.1.0 — это офлайн-библиотека с prepare-загрузками, комментарии, Remanga,
HTTPS, более живые загрузчики и укрепление админки. API `/api/v1` остаётся
совместимым с 1.0.0; ломающих изменений нет.

### Офлайн-библиотека

- Скачивание одной главы или всего тайтла прямо из карточки манги.
- Очередь сохраняется после каждой страницы: после перезапуска приложения
  загрузка продолжается, уже скачанные страницы пропускаются.
- Прогресс, размер, статус (`queued/running/done/failed`), отмена, retry и
  удаление — в библиотеке, вкладка «Скачано».
- Чтение скачанного без сети: отдельные страницы офлайн-читалки и прогресс.
- Хранение: IndexedDB в браузере, Filesystem + Preferences в Capacitor,
  Room + WorkManager в нативном Kotlin-клиенте. Байты изображений не пишутся
  в `localStorage`.
- Офлайн-данные локальны для устройства и не синхронизируются между web,
  Capacitor и Kotlin.
- Prepare-фаза: `POST /manga/{id}/prepare` и `GET /manga/{id}/prepare`
  идемпотентны, прогресс (`prepared/pending/failed`) сохраняется между
  перезапусками; клиент ждёт до 5 подготовленных глав и скачивает батчами.
- Искусственный throttle 2–4.89 с для whole-title убран; отмена и повтор
  подготовки доступны из библиотеки.

### Комментарии

- Отдельный сервис `comments` (`:8109`), комментарии только к тайтлам.
- Ответы одного уровня, лайки, спойлеры, редактирование и удаление своих
  комментариев.
- Жалобы и админ-модерация: hide/restore, resolve/dismiss.
- Уведомления о reply/like и колокольчик с unread badge.
- Не-ASCII имена передаются в gateway percent-encoded.

### Архив глав

- Маленькие главы — BLOB в SQLite, большие — ZIP.
- Archive LRU около 25 GiB (`last_accessed_at`, prune при старте и после
  архивирования); метаданные и обложки не вытесняются.
- `POST /api/v1/manga/{id}/warm` ставит в очередь архивирование всех глав.

### Dancing loaders

- 16 GIF `dance-01..16` (256×256) вместо круговых спиннеров.
- `DancingLoader` выбирает GIF на каждый mount; `DancingSpinner` работает
  внутри кнопок и статусов.
- Boot-loader и route fallback используют тот же компонент, поэтому загрузка
  выглядит цельно, а не как серая полоса.

### Админка и безопасность

- Production не стартует с дефолтным `ADMIN_PASSWORD`.
- Админ-JWT содержит HMAC-отпечаток текущих `ADMIN_USERNAME`/`ADMIN_PASSWORD`;
  после смены учётных данных старые сессии получают
  `401 admin_session_expired` и требуют повторного входа.
- Админ-вход: 5 неудачных попыток на IP за 5 минут, токен 60 минут по
  умолчанию (`ADMIN_TOKEN_MINUTES`).
- Rate limit доверяет только nginx `X-Real-IP`, а не клиентскому
  `X-Forwarded-For`.
- Media прокси перепроверяет DNS и каждый redirect, режет private/link-local/
  metadata-хосты и не-растровые ответы.
- Пользовательские access/refresh-токены это не затрагивает.
- Публичный деплой переведён на HTTPS: `https://85.192.37.58.nip.io:8443`
  (Let's Encrypt, HSTS, CSP); HTTP `:8088` оставлен для совместимости.
- UI админки очищает устаревшие ошибки сервера и показывает контекст
  jump-host в логе деплоя.
- Cookie источников: persistent store, ручное значение и импорт `.har`
  (серверный endpoint + browser-side extraction для больших файлов).
  Значение cookie не возвращается в API, не пишется в audit/log и не уходит
  клиентам.

### Server manager и мультисерверность

- Частичный деплой больше не затирает inventory: результаты мержатся в
  существующий список серверов.
- Сервисы можно ставить на jump-host; control отдаёт обычные app-серверы
  раньше jump-хостов.
- Деплой показывает потоковый лог, корректно завершает self-deploy control и
  проверяет health удалённых узлов.
- Gateway выбирает endpoint по `priority` (rendezvous hash с весом), fallback
  идут последними; записи и stateful-чтение — на лидере.
- **Репликация данных в разработке и не включена в production.**
  Приоритетный роутинг и failover есть, но полноценный failover с сохранением
  данных на втором узле — следующий шаг, не обещание 1.1.0. Сервис репликации
  SQLite-снимков и архива глав уже есть в `main`, но на демо-сервере не
  развёрнут и требует отдельной проверки перед публикацией.

## Уже было в 1.0.0 (важно для контекста)

Эти функции не новые в 1.1.0, но входят в продукт с релиза 1.0.0:

- варианты источников и фильтр переводов `source/translator/count`
  (`GET /api/v1/manga/{id}/variants`);
- серверный архив глав: SQLite BLOB для маленьких глав, ZIP для больших,
  `POST /api/v1/manga/{id}/warm`;
- серверный экспорт CBZ / PDF / HTML-ZIP через API;
- шесть тем: `midnight`, `noir`, `oni`, `crimson`, `sunset`, `paper`;
- React web, Kotlin/Compose и Node.js/Capacitor клиенты;
- админка `/admin` с SSH-деплоем, health registry и failover.

## Обновление

1. Сделайте бэкап `.env` и баз данных.
2. Обновите код и пересоберите сервисы.
3. Проверьте, что `ADMIN_PASSWORD` не дефолтный: production-валидация не
   пропустит `change-me-admin-password`.
4. После смены `ADMIN_USERNAME`/`ADMIN_PASSWORD` все старые админ-сессии
   завершатся — это ожидаемо.
5. Проверьте `/api/v1/health`, `GET /api/v1/manga/{id}/variants`,
   `POST/GET /api/v1/manga/{id}/prepare` и комментарии к тестовому тайтлу.
6. Проверьте статус cookie источников в `/admin` (значение не должно
   возвращаться в API) и импорт `.har` на небольшом файле.

Схема БД создаётся идемпотентно; отдельных Alembic-миграций в 1.1.0 нет.

## Ограничения

- HTTPS — основной режим; HTTP `:8088` оставлен для совместимости и будет
  выведен.
- Release APK не подписан, iOS-сборки нет.
- SQLite на одном узле; репликация в разработке и в production не включена.
- ReadManga и MangaDex выключены по умолчанию. Remanga доступен, но требует
  соблюдения robots/прав источника; для части глав нужен cookie.
- Android-клиент не запускает экспорт CBZ/PDF/HTML и не имеет UI импорта;
  офлайн-каталог целиком не кэшируется.
- Пользовательский UI экспорта CBZ/PDF/HTML убран; публичные export-маршруты
  будут удалены/скрыты в рамках cleanup.

## Ссылки

- Демо: <https://85.192.37.58.nip.io:8443>
- Админка: <https://85.192.37.58.nip.io:8443/admin>
- API health: <https://85.192.37.58.nip.io:8443/api/v1/health>
- Архитектура: [docs/ARCHITECTURE.md](https://github.com/geekAmis/mangapoiskAPI/blob/main/docs/ARCHITECTURE.md)
- API: [docs/API.md](https://github.com/geekAmis/mangapoiskAPI/blob/main/docs/API.md)
- QA: [docs/QA.md](https://github.com/geekAmis/mangapoiskAPI/blob/main/docs/QA.md)
- Roadmap: [docs/ROADMAP.md](https://github.com/geekAmis/mangapoiskAPI/blob/main/docs/ROADMAP.md)
- Эпик v1.1: [#29](https://github.com/geekAmis/mangapoiskAPI/issues/29)
- Эпик v1.2: [#48](https://github.com/geekAmis/mangapoiskAPI/issues/48)
- Загрузки: [#31](https://github.com/geekAmis/mangapoiskAPI/issues/31)
- Комментарии: [#33](https://github.com/geekAmis/mangapoiskAPI/issues/33)
- Cookie/HAR: [#34](https://github.com/geekAmis/mangapoiskAPI/issues/34)
- Cleanup/LRU: [#36](https://github.com/geekAmis/mangapoiskAPI/issues/36)

## Полный список изменений

См. [docs/CHANGELOG.md](https://github.com/geekAmis/mangapoiskAPI/blob/main/docs/CHANGELOG.md)
и [сравнение `v1.0.0...main`](https://github.com/geekAmis/mangapoiskAPI/compare/v1.0.0...main).
