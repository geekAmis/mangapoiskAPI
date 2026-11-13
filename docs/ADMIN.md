# Админка Control

Панель: `/admin` (прямая ссылка; в публичном меню её нет). Вход — по
`ADMIN_USERNAME` / `ADMIN_PASSWORD` из окружения gateway. Админ-токен хранится
в `sessionStorage` и живёт `ADMIN_TOKEN_MINUTES` (по умолчанию 60 минут).
В production v1.3.2 смена этих переменных инвалидирует старые токены
(`401 admin_session_expired`).

## Вкладки и deep links

Каждая функция вынесена на отдельную вкладку. Активная вкладка хранится в URL:

| Вкладка | Deep link | Что внутри |
|---|---|---|
| Обзор | `/admin?tab=overview` | здоровье сервисов, observability (p95/5xx/locks/backup age), активные задачи, алерты, последние события |
| Серверы | `/admin?tab=servers` | inventory, health-check, deploy, реестр gateway, failover |
| Деплой | `/admin?tab=deploy` | очередь deployment jobs, журнал, слот AI supervisor |
| Краулер и каталог | `/admin?tab=crawler` | источники, backlog, ETA, enrichment, crawl states, редактор подборок |
| Медиа и хранилище | `/admin?tab=media` | LRU-кэш изображений, архивы глав, eviction |
| Реклама | `/admin?tab=ads` | провайдеры, ключи, слоты, аудитории; Яндекс RTB и Block ID |
| Комментарии | `/admin?tab=comments` | жалобы, модерация комментариев и профилей |
| Интеграции | `/admin?tab=integrations` | Яндекс ID (реальные ключи в БД), cookie источников, HAR |
| Аудит | `/admin?tab=audit` | последние 100 действий control |
| Терминал | `/admin?tab=terminal` | ограниченная серверная консоль |

Консоль можно открыть сразу для сервера:

```
/admin?tab=terminal&server=<server-uuid>
```

Кнопка «Консоль» в карточке сервера и алерты на обзоре ведут по такой ссылке.
Переключение вкладок добавляет запись в history, поэтому кнопки браузера
«Назад/Вперёд» возвращают предыдущую вкладку. Неизвестный `tab` открывает
обзор. Параметр `server` сохраняется при переключении вкладок, поэтому возврат
на «Терминал» восстанавливает выбранный сервер и черновик команды.

## Ленивая загрузка

Панели собраны через `React.lazy` и монтируются только при первом открытии
вкладки. После первого открытия панель остаётся смонтированной и скрывается
через `hidden`, чтобы не терять черновики форм, введённые фильтры и позицию
скролла. Запросы:

- `me`, `servers`, `jobs` — нужны для шапки, бейджей и терминала;
- `registry` — только на вкладке «Серверы»;
- `audit` — на «Обзоре» и «Аудите»;
- `catalogue` — на «Обзоре» и «Краулере»;
- `media`, `ads`, `comments`, `console history`, `collections`, `Yandex
  integration` — только при открытии соответствующей вкладки.

Бейджи: «Серверы» показывает число unhealthy HTTP-сервисов, «Деплой» — число
`queued`/`running` задач, «Краулер» — число failed enrichment + blocked
источников (после загрузки вкладки).

## Мобильная и клавиатурная навигация

- На ширине ≤767 px вместо горизонтального tablist показывается `<select>`;
  список вкладок на десктопе прокручивается горизонтально без overflow.
- Tablist имеет `role="tablist"`, кнопки — `role="tab"` с `aria-selected`,
  `aria-controls` и roving `tabindex`. Работают `←`, `→`, `Home`, `End`;
  `Enter`/`Space` активируют вкладку.
- Панели имеют `role="tabpanel"` и `aria-labelledby`.
- Проверено на 1440×900 и 390×844: `document.documentElement.scrollWidth`
  не превышает viewport, ошибок в console нет.

## Интеграции

- **Яндекс ID** — рабочая интеграция, не слот: Client ID, Client secret и
  Redirect URI шифруются в control и управляются в
  `Интеграции → Яндекс ID`. Реальный вход на production подтверждён;
  redirect URI — `https://85.192.37.58.nip.io/api/v1/auth/yandex/callback`.
  Подробности: [AUTH_YANDEX.md](AUTH_YANDEX.md).
- **Cookie источников** — статус/set/clear и импорт `.har`; значения не
  возвращаются в API и не пишутся в audit.
- **Реклама** — реальный RTB-провайдер `c57fb6e5-23e6-4d97-b7b4-66af8b7b9c43`
  (`R-A-20411736-1`) и поле Block ID. Реальный показ ждёт включения площадки в
  кабинете Яндекса; см. [ADS.md](ADS.md).
- **Traffic/Metrika** — в v1.3.2 панели нет; работа идёт в #85.
- **AI supervisor** — слот/заглушка в журнале деплоя; ветка #75 не входит в
  production.

## Тесты

Backend:

```bash
pytest tests/control/test_console.py
pytest tests/control/test_ads.py
```

Frontend:

```bash
cd apps/web
npm run test:admin-tabs
npm run typecheck
npm run build
```

`test:admin-tabs` проверяет полноту tab map, deep-link parser и fallback на
обзор. Backend-тесты консоли покрывают allowlist, инъекции, timeout, audit и
auth (см. `docs/SERVER_CONSOLE.md`).

## Ручная проверка

1. Открыть `/admin?tab=servers`, обновить страницу — активна вкладка «Серверы».
2. Переключиться на «Терминал», нажать «Назад» — возвращается предыдущая
   вкладка; «Вперёд» — снова терминал.
3. Открыть `/admin?tab=terminal&server=<id>` — терминал сразу выбранного сервера.
4. На 390×844 открыть select вкладок, проверить отсутствие горизонтального
   скролла и доступность быстрых кнопок.
5. Открыть DevTools → Console; переключить все вкладки — ошибок быть не должно.
6. `Интеграции → Яндекс ID`: маска ключей, без открытого `client_secret`;
   `GET /api/v1/admin/integrations/yandex` не отдаёт секреты.

## Ограничения

- AI supervisor report — заглушка; журнал deployment job доступен (#75).
- Traffic/Metrika panel не входит в v1.3.2 (#85).
- Нет IP allowlist/VPN и MFA для `/admin`; это открытый пункт #79. Считайте
  украденный 60-минутный токен действующим до истечения.
- Панели не сбрасывают данные при переключении, но `hidden`-панели с
  интервальными запросами (`media`, `crawler`) могут продолжать фоновое
  обновление, пока вкладка открыта в браузере.
