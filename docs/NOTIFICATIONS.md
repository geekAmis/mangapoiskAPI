# Уведомления о новых главах

Issue: [#42](https://github.com/geekAmis/mangapoiskAPI/issues/42).

## Что реализовано

Подписчик нажимает «Следить за главами» на странице тайтла. Когда scheduler
обнаруживает новую главу при штатном refresh каталога, он передаёт события в
comments-сервис. Тот создаёт in-app уведомление каждому подписчику и просит
notifier отправить Web Push. Одна и та же глава не может создать второе
уведомление в канале: дедупликация обеспечивается уникальными индексами БД, а
не только логикой приложения.

```
catalog /internal/maintenance/refresh
        │  new_chapters[]
        ▼
scheduler ──► comments /internal/notifications/chapters
                 │  title_follows + aliases (source variants)
                 │  chapter_notifications  UNIQUE(user, manga, chapter)
                 ▼
             notifier /internal/push/chapters
                 │  push_deliveries UNIQUE(user, manga, chapter)
                 │  push_batches (hourly rate limit)
                 ▼
             browser service worker ──► showNotification()
```

Telegram-уведомление scheduler'а сохранено как отдельный, независимый канал.

## Подписки и настройки

Пользователь следует за каноническим id тайтла. Gateway при подписке
запрашивает `/manga/{id}/variants` у каталога и передаёт comments-сервису все
id источников. Поэтому новая глава, найденная на любом варианте тайтла,
доходит до одного и того же подписчика.

API (публичный, JWT):

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/api/v1/notifications/follows` | список подписок |
| POST | `/api/v1/notifications/follows` | подписаться (идемпотентно) |
| GET | `/api/v1/notifications/follows/{manga_id}` | статус подписки |
| DELETE | `/api/v1/notifications/follows/{manga_id}` | отписаться |
| GET/PUT | `/api/v1/notifications/settings` | настройки каналов |
| GET | `/api/v1/notifications/push/config` | VAPID public key и готовность |
| POST/DELETE | `/api/v1/notifications/push/subscribe` | подписка устройства |
| GET | `/api/v1/notifications/push/status` | активные устройства |

Настройки: `in_app_enabled`, `web_push_enabled`, `max_pushes_per_hour`,
`quiet_hours_start`, `quiet_hours_end`. Они хранятся в аккаунте и переживают
перезапуск и смену сессии.

Лента `/api/v1/notifications` объединяет комментарии (`reply`, `like`,
`moderation`) и главы (`chapter`) в один хронологический список с общим
unread badge и read-state. В уведомлении о главе есть ссылка на читалку и
кнопка отписки от тайтла.

## Web Push

- Транспорт: `pywebpush` 2.x (VAPID + http-ece шифрование payload).
- Payload: `title`, `body`, `tag=chapter-{manga_id}`, `data.url` на
  `/reader/{chapter_id}`. Service worker показывает уведомление и по клику
  фокусирует вкладку или открывает новую.
- Permission prompt вызывается только по явному действию: переключатель
  «Web Push на этом устройстве» в профиле. На первом заходе браузер ничего не
  спрашивает.
- Push только для авторизованных аккаунтов. Анонимных подписок нет.
- При отказе в разрешении in-app уведомления продолжают работать.
- Повторная подписка того же browser endpoint идемпотентна. Endpoint,
  reassigned другому пользователю на этом устройстве, переезжает к актуальному
  аккаунту, а не создаёт дубль.

### Генерация VAPID-ключей

```bash
cd apps/web
npx web-push generate-vapid-keys
```

Или без Node, после установки `services/notifier/requirements.txt`:

```bash
python - <<'PY'
from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid

vapid = Vapid()
vapid.generate_keys()
private = vapid.private_key.private_numbers().private_value.to_bytes(32, "big")
public = vapid.public_key.public_bytes(
    serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
)
import base64
b64 = lambda raw: base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
print("VAPID_PRIVATE_KEY=" + b64(private))
print("VAPID_PUBLIC_KEY=" + b64(public))
PY
```

`VAPID_PRIVATE_KEY` принимает base64url или PEM, `VAPID_PUBLIC_KEY` —
base64url. **Никогда не коммитьте приватный ключ.** `.env` уже в
`.gitignore`; в репозитории есть только пустые значения в `.env.example`.
Смена пары ключей инвалидирует старые browser-подписки (браузеру придётся
подписаться заново).

### Переменные окружения

```env
VAPID_PUBLIC_KEY=
VAPID_PRIVATE_KEY=
VAPID_SUBJECT=mailto:admin@example.com
WEB_PUSH_ENABLED=true
PUSH_MAX_PER_HOUR=10
PUSH_TTL_SECONDS=86400
PUSH_QUIET_HOURS_START=
PUSH_QUIET_HOURS_END=
PUSH_ENDPOINT_ALLOWED_HOSTS=google.com,googleapis.com,updates.push.services.mozilla.com,push.services.mozilla.com,notify.windows.com,web.push.apple.com,push.apple.com
CHAPTER_NOTIFICATIONS_ENABLED=true
CHAPTER_NOTIFICATIONS_PUSH_ENABLED=true
COMMENTS_URL=http://comments:8109
NOTIFIER_DATABASE_URL=sqlite+aiosqlite:////data/notifier.db
COMMENTS_DATABASE_URL=sqlite+aiosqlite:////data/comments.db
```

Без VAPID-ключей сервис работает в режиме «только in-app»: `/push/config`
возвращает `enabled=false`, UI честно показывает, что Web Push не настроен.

## Rate limit, батчинг, тихие часы

- Лимит по умолчанию: 10 push/час на пользователя (`PUSH_MAX_PER_HOUR`).
  Пользователь может выбрать меньше в профиле (1–10; серверный потолок задаёт
  `PUSH_MAX_PER_HOUR`). Счётчик — логические push-уведомления, а не устройства.
- Несколько глав одного тайтла в одном событии scheduler'а объединяются в один
  push: «Новые главы — Название», тело содержит до трёх глав.
- Тихие часы опциональны. **Время трактуется как UTC** (в UI это написано).
  В тихие часы Web Push пропускается, in-app уведомление создаётся. Окно
  через полночь поддерживается (`22 → 8`); `start == end` считается
  выключенными тихими часами.
- При превышении лимита Web Push пропускается, in-app остаётся. Это осознанный
  выбор: пользователь не теряет событие, но не получает шквал системных
  уведомлений.

## Android / Capacitor

Проверено: Android System WebView, который использует Capacitor 6, **не
реализует Push API** (`window.PushManager` отсутствует). Service Worker и
`Notification` частично доступны, но push-подписка и доставка требуют нативной
интеграции FCM, `@capacitor/push-notifications`, разрешения
`POST_NOTIFICATIONS` (Android 13+) и notification channel. В этом изменении
нативная push-интеграция не добавлялась и не имитировалась.

Поведение:

- `lib/push.ts` определяет `Capacitor.isNativePlatform()` и отключает
  Web Push-переключатель.
- В профиле показывается объяснение ограничения.
- In-app колокольчик работает в WebView и является fallback. Пока приложение
  открыто, лента обновляется раз в 60 секунд; после запуска — при первом
  запросе ленты.
- Полноценные фоновые Android-уведомления потребуют отдельной задачи:
  FCM + Capacitor Push Notifications + серверный FCM-канал. Это не входит в
  текущий scope.

## Тесты

```bash
pytest tests/comments/test_chapter_notifications.py
pytest tests/notifier
pytest tests/scheduler/test_chapter_notifications.py
pytest tests/integration/test_real_chapter_import.py
```

`tests/integration/test_real_chapter_import.py` — тест на реальном импорте:
каталог импортирует главу 1, затем refresh обнаруживает главу 2; события
проходят через настоящий `CatalogService`, comments fan-out и notifier
dedupe/rate-limit. Отправка push подменена recording sender'ом, production
push не выполняется.

Тестовые VAPID-ключи и endpoint'ы — фиктивные. Реальный browser QA проверяет
permission denied/granted, offline и unsubscribe без отправки production push.

## Известные ограничения

- Web Push at-most-once: если push-сервис вернул ошибку, повторная попытка для
  этой главы не делается (запись `push_deliveries` уже создана). In-app
  уведомление при этом на месте.
- Несколько вкладок/устройств одного пользователя получают один логический
  push на все активные подписки; счётчик rate limit считает событие один раз.
- Нет email-уведомлений (по условиям issue).
- Нет анонимных подписок.
- VAPID-ключи не ротируются автоматически.
- Браузерные push-сервисы могут задерживать доставку; tag схлопывает
  уведомления одного тайтла.
