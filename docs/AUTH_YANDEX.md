# Авторизация через Яндекс ID (OAuth 2.0)

Задача: [#67](https://github.com/geekAmis/mangapoiskAPI/issues/67).

**Статус production (2026-11-13):** интеграция включена. Реальный вход через
Яндекс ID подтверждён на `https://85.192.37.58.nip.io`; приложение в
Яндекс.Консоли в статусе **«Подключен»**, redirect URI —
`https://85.192.37.58.nip.io/api/v1/auth/yandex/callback`, scopes
`login:email login:info login:avatar`. `login:info` должен быть включён в
Консоли — без него не приходят `id`/`display_name`/`real_name`.

Вход и регистрация через Яндекс ID работают на веб-клиенте и в мобильной
оболочке Capacitor. Провайдер полностью опционален: без настроенной интеграции
(БД или bootstrap `.env`) кнопка скрыта, а `GET /api/v1/auth/yandex/start`
отвечает `503`. Обычный вход по email/паролю при этом не меняется.

## Как это устроено

```text
Браузер / WebView
   │  1. GET /api/v1/auth/yandex/start?next=/library
   ▼
Gateway ── 2. POST /internal/auth/yandex/start ──► Library
   │                                              │ создаёт state (TTL 10 мин)
   │◄──────────── authorize_url ──────────────────┘
   │  3. 302 + HttpOnly cookie mp_yandex_flow
   ▼
https://oauth.yandex.ru/authorize
   │  4. пользователь подтверждает доступ
   ▼
GET /api/v1/auth/yandex/callback?code=...&state=...
   │  5. Gateway → Library: проверка state + cookie,
   │     обмен code на токен Яндекса, профиль, создание/связывание user
   ▼
302 /auth/yandex/finish?code=<one-time handoff>&next=/library
   │  6. SPA: POST /api/v1/auth/yandex/exchange {code}
   ▼
TokenPair (access + refresh) — сохраняется как при обычном входе
```

Ключевые свойства:

- `state` — 32 случайных байта (`secrets.token_urlsafe`), в БД лежит только
  SHA-256. Одноразовый, TTL 10 минут, привязан к HttpOnly cookie
  `mp_yandex_flow`, которая удаляется на callback.
- `code` обменивается на токен Яндекса **только на сервере**. `client_secret`
  никогда не покидает library service.
- В URL после callback нет access/refresh токенов. Вместо них — одноразовый
  handoff-код с TTL 60 секунд. Он обменивается через
  `POST /api/v1/auth/yandex/exchange` и хранится в БД только хешем.
- Профиль берётся из `https://login.yandex.ru/info?format=json`. Обязателен
  `default_email` — адрес, подтверждённый Яндексом. Если его нет, вход
  отклоняется с понятной ошибкой.
- Связывание: сначала ищем пользователя по `yandex_id`; если не найден — по
  `default_email`. Существующий email-аккаунт получает `yandex_id`, все его
  прежние refresh-сессии отзываются. Если email уже привязан к другому
  `yandex_id` — `409`, перезаписи нет.
- Новый пользователь создаётся с `display_name` из Яндекс ID и инициалами в
  интерфейсе (аватар Яндекса не скачивается). `auth_provider='yandex'`.
- Rate limit: отдельный bucket на `start`/`callback`/`exchange`
  (`GATEWAY_OAUTH_LIMIT_PER_MINUTE`, по умолчанию 20/мин на IP).
- Коды, state, токены и `client_secret` не логируются. Ошибки в callback
  превращаются в короткий `error=<code>` в URL, а не в 500.

## Регистрация приложения в Яндекс.Консоли

1. Откройте <https://oauth.yandex.ru/client/new>.
2. Платформа — **Веб-сервисы**.
3. Название и иконка — на усмотрение владельца.
4. Redirect URI (точный, без завершающего `/`):
   - production: `https://85.192.37.58.nip.io/api/v1/auth/yandex/callback`
   - localhost для разработки: `http://localhost:8000/api/v1/auth/yandex/callback`
     (и при необходимости `http://127.0.0.1:8000/...`).
5. Доступ к данным:
   - `login:email` — получить `default_email`;
   - `login:info` — получить `id`, `display_name`, `real_name`; **обязателен**
     и должен быть включён в Яндекс.Консоли;
   - `login:avatar` — `avatar_id` (сейчас не используется, но зарегистрирован
     владельцем).
6. В настройках приложения скопируйте `ClientID` и `Client secret`.

## Где хранятся ключи

**Основной источник — база control-сервиса.** Ключи задаются в админ-панели:
`Интеграции → Яндекс ID`. Значения `client_id`, `client_secret` и
`redirect_uri` шифруются Fernet-ключом, производным от `CONTROL_SECRET_KEY`
(та же схема, что у SSH-паролей и рекламных секретов). В API и UI возвращаются
только `configured`, маска `••••last4` и `updated_at`.

Gateway при каждом запросе к OAuth-маршрутам читает credentials из control
(короткий TTL-кеш 60 секунд). Если в БД **нет ни одного** значения, используется
`.env` как bootstrap-fallback:

```dotenv
YANDEX_CLIENT_ID=
YANDEX_CLIENT_SECRET=
YANDEX_REDIRECT_URI=
```

Как только в БД появляется хотя бы одно значение, БД выигрывает полностью:
неполная конфигурация в БД не «дополняется» из `.env`, а провайдер считается
выключенным. Это защищает от случайного смешивания старого и нового ключа.
Пустые значения в БД = провайдер выключен.

Production redirect URI (точный, без завершающего слэша):

```text
https://85.192.37.58.nip.io/api/v1/auth/yandex/callback
```

В production control-сервис принимает только HTTPS redirect URI и требует,
чтобы путь оканчивался на `/api/v1/auth/yandex/callback`.

### Админ-панель

Раздел `Интеграции → Яндекс ID` в табовой админке (компонент
`YandexIntegrationPanel`):

- поля Client ID, Client secret, Redirect URI;
- тумблер «Включить вход через Яндекс ID»;
- кнопка «Проверить конфигурацию» — проверяет наличие, расшифровку и форму
  значений, **не** вызывает Яндекс и не показывает секреты;
- удаление всех значений с подтверждением;
- подсказка, что в Яндекс.Консоли должен быть указан ровно тот же redirect URI.

API (только с admin Bearer-токеном):

| Метод | Путь | Назначение |
| --- | --- | --- |
| `GET` | `/api/v1/admin/integrations/yandex` | masked-состояние |
| `PUT` | `/api/v1/admin/integrations/yandex` | задать/заменить поля, `enabled` |
| `DELETE` | `/api/v1/admin/integrations/yandex` | удалить все значения |
| `POST` | `/api/v1/admin/integrations/yandex/test` | проверка формы без секретов |

Внутренний `GET /internal/integrations/yandex/credentials` отдаёт plaintext
только gateway по `X-Internal-Token`; публично он недоступен.

Аудит: `integration.yandex.updated` и `integration.yandex.deleted`. В деталях
только провайдер, список изменённых полей и `had_values`; значения, хинты и
секреты не пишутся.

### Миграция с `.env` на БД

1. Задеплоить версию с DB-backed настройками, **не удаляя** текущие
   `YANDEX_*` из `/opt/mangapoisk-reborn/.env` — они остаются bootstrap.
2. Открыть админку → `Интеграции → Яндекс ID`, ввести Client ID, Client secret
   и точный redirect URI, включить провайдер, сохранить.
3. Нажать «Проверить конфигурацию» и пройти ручной вход (см. чек-лист ниже).
4. Убедиться, что `GET /api/v1/auth/providers` → `{"yandex":true}`, а вход
   работает при временно пустых `YANDEX_*` (можно проверить на staging).
5. Только после этого удалить строки `YANDEX_CLIENT_ID`,
   `YANDEX_CLIENT_SECRET`, `YANDEX_REDIRECT_URI` из production `.env`.
   Пустые placeholders в deploy-шаблоне остаются; deploy-скрипт сохраняет
   непустые значения, пока они есть.

В production v1.3.2 миграция завершена: реальные ключи хранятся только в
зашифрованной БД control, `.env`-строки можно оставить пустыми. Проверка —
`GET /api/v1/auth/providers` → `{"yandex":true}` и реальный вход.

Важно: не удаляйте `.env`-строки раньше шага 4 — при откате на старую версию
без БД-пути они будут единственным источником конфигурации.

## API

| Метод | Путь | Назначение |
| --- | --- | --- |
| `GET` | `/api/v1/auth/providers` | `{"yandex": true/false}` для кнопки |
| `GET` | `/api/v1/auth/yandex/start?next=/library&client=web\|app` | 302 на Яндекс; 503 если не настроено |
| `GET` | `/api/v1/auth/yandex/callback?code=&state=` | 302 на `/auth/yandex/finish?code=...` |
| `POST` | `/api/v1/auth/yandex/exchange` | `{"code": "<handoff>"}` → `TokenPair` |
| `GET` | `/api/v1/admin/integrations/yandex` | masked-настройки (admin) |
| `PUT` | `/api/v1/admin/integrations/yandex` | сохранить настройки (admin) |
| `DELETE` | `/api/v1/admin/integrations/yandex` | удалить настройки (admin) |
| `POST` | `/api/v1/admin/integrations/yandex/test` | проверка формы (admin) |

Внутренние маршруты library (только с `X-Internal-Token`):
`/internal/auth/yandex/status`, `/start`, `/callback`, `/deny`, `/exchange`.
Внутренние маршруты control:
`/internal/integrations/yandex` (GET/PUT/DELETE), `/test`,
`/credentials` (plaintext только для gateway).

### Коды ошибок в `/auth/yandex/finish?error=...`

| Код | Что показать пользователю |
| --- | --- |
| `access_denied` | Пользователь отменил вход |
| `state_invalid` | Ссылка входа устарела/уже использована |
| `code_invalid` | Код Яндекса истёк |
| `email_missing` | Яндекс не вернул подтверждённый email |
| `account_conflict` | Email привязан к другому аккаунту |
| `account_disabled` | Аккаунт отключён |
| `yandex_unavailable` | Яндекс/сеть временно недоступны |
| `not_configured` | Провайдер выключен |
| `handoff_invalid` | Handoff-код устарел/использован |

Тексты сообщений задаются на клиенте; серверные сообщения не содержат
секретов и не отражают произвольный ввод.

## Мобильная оболочка Capacitor

SPA в Capacitor загружается с `https://localhost` (переопределяется
`YANDEX_APP_RETURN_URL`). Поэтому кнопка передаёт `client=app`, а callback
возвращает на `https://localhost/auth/yandex/finish?code=...` — это тот же
WebView и тот же origin localStorage, где хранится сессия. Для обычного веба
возврат идёт на `PUBLIC_WEB_URL/auth/yandex/finish`.

Если Яндекс ограничит вход во встроенном WebView, потребуется внешний браузер
(`@capacitor/browser`) и deep link; текущая реализация использует same-window
сценарий, разрешённый постановкой.

## Ручная проверка после деплоя

Выполнять без вывода секретов в терминал. `$HOST` =
`https://85.192.37.58.nip.io`.

0. **Настройки в админке**
   - Открыть `$HOST/admin` → `Интеграции → Яндекс ID`.
   - Ввести Client ID, Client secret и
     `https://85.192.37.58.nip.io/api/v1/auth/yandex/callback`, включить
     тумблер, сохранить.
   - Нажать «Проверить конфигурацию»: все пункты ✓, секреты показаны только
     маской `••••last4`.
   - `GET $HOST/api/v1/admin/integrations/yandex` (admin Bearer) не содержит
     `client_secret`/`client_id` в открытом виде.
1. **Провайдер включён и кнопка видна**
   - `curl -s $HOST/api/v1/auth/providers` → `{"yandex":true}`.
   - Открыть `$HOST/login` в приватном окне: под формой есть разделитель «или» и
     кнопка «Войти через Яндекс».
2. **Start**
   - `curl -sI "$HOST/api/v1/auth/yandex/start?next=/library"` →
     `302`, `Location: https://oauth.yandex.ru/authorize?...`,
     `Set-Cookie: mp_yandex_flow=...; HttpOnly; Path=/api/v1/auth/yandex`.
   - В `Location` есть `client_id`, `redirect_uri` с точным production URI,
     `scope=login%3Aemail+login%3Ainfo+login%3Aavatar` и `state`.
3. **Яндекс**
   - Нажать кнопку, войти тестовым Яндекс-аккаунтом, разрешить доступ.
   - Вернуться на `$HOST/auth/yandex/finish?code=<handoff>&next=/library`.
   - В адресной строке **нет** `access_token`/`refresh_token`.
4. **Exchange**
   - SPA сама вызывает `POST $HOST/api/v1/auth/yandex/exchange` с handoff-кодом
     и получает `TokenPair`; происходит переход на `/library`, в шапке —
     имя из Яндекс ID.
   - Повторный `POST` с тем же handoff-кодом → `401 handoff_invalid`.
5. **Профиль**
   - `GET $HOST/api/v1/auth/me` с выданным access-токеном возвращает
     `email` = `default_email` Яндекса и `display_name`.
   - В БД library у пользователя `yandex_id` заполнен, `auth_provider='yandex'`
     (для нового аккаунта) или `'password'` (для связанного существующего).
6. **Повторный вход**
   - Выйти и войти тем же Яндексом снова: новый пользователь не создаётся,
     `GET /auth/me` возвращает тот же `id`.
7. **Отказ**
   - На странице Яндекса нажать «Отмена»: возврат на
     `/auth/yandex/finish?error=access_denied`, понятный текст, без 500.
8. **Выключенный провайдер**
   - В админке выключить тумблер «Включить вход через Яндекс ID» (или удалить
     интеграцию): `GET /auth/yandex/start` → `503 yandex_not_configured`,
     кнопка скрыта, вход по email работает.
   - Если БД пуста, проверить bootstrap-режим: временно убрать три переменные
     из `.env` и перезапустить library+gateway — поведение то же.
9. **Мобильный WebView**
   - Собрать APK (`cd apps/mobile && npm run sync`), открыть `/login` при
     размере 390×844: кнопка не ломает вёрстку; вход возвращает в приложение,
     сессия сохраняется после перезапуска.

### QA-скриншоты

Реальный production-вход через Яндекс ID подтверждён 13.11.2026: кнопка
открывает `oauth.yandex.ru`, callback возвращает на
`https://85.192.37.58.nip.io/auth/yandex/finish`, сессия создаётся/связывается,
повторный вход не дублирует пользователя. Скриншоты ниже — локальный e2e с
mock-Яндексом и DB-only credentials (390×844 и 1440×900, 0 console errors на
auth-экранах):

- `docs/screenshots/yandex-login-mobile.png`
- `docs/screenshots/yandex-login-desktop.png`
- `docs/screenshots/yandex-authenticated-mobile.png`
- `docs/screenshots/yandex-error-mobile.png`
- `docs/screenshots/yandex-disabled-mobile.png`
- `docs/screenshots/yandex-admin-integration.png`
- `docs/screenshots/yandex-admin-integration-tested.png`

## Локальный end-to-end без реального Яндекса

Тесты используют `httpx.MockTransport`; для ручной проверки можно поднять
mock-сервер OAuth и указать:

```dotenv
YANDEX_CLIENT_ID=test-client
YANDEX_CLIENT_SECRET=test-secret
YANDEX_REDIRECT_URI=http://localhost:8000/api/v1/auth/yandex/callback
YANDEX_AUTHORIZE_URL=http://127.0.0.1:9999/authorize
YANDEX_TOKEN_URL=http://127.0.0.1:9999/token
YANDEX_PROFILE_URL=http://127.0.0.1:9999/info
```

Реальные ключи допустимо использовать только для локального e2e, если они не
попадают в репозиторий/логи. В production-тестах — только моки.

## Остаточный риск

Связывание по `default_email` доверяет подтверждению Яндекса. Если
злоумышленник заранее зарегистрировал email-аккаунт жертвы (до её первого входа
через Яндекс), при первом Яндекс-входе этот аккаунт будет связан, а прежние
сессии отозваны. Пароль, установленный злоумышленником, при этом сохраняется.
Полностью закрывает сценарий только подтверждение email при регистрации по
паролю или обязательный сброс пароля при связывании — отдельная задача.
