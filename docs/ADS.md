# Реклама: провайдеры, слоты, ключи и аудитории

Документ описывает управление рекламными интеграциями в MangaPoisk Reborn:
модель данных, API, шифрование ключей, поведение фронтенда, CSP, приватность
и порядок добавления нового провайдера.

Основные принципы:

- реклама не является обязательной частью страницы: при выключенном слоте,
  отсутствии ключа, ошибке control-сервиса или adblock страница работает как
  обычно, без ошибок в консоли и без «прыжков» layout;
- секретные ключи хранятся только на сервере в зашифрованном виде и никогда не
  возвращаются в публичный API или HTML;
- в reader реклама показывается только если администратор явно создал слот
  `post-chapter`;
- для 18+ тайтлов реклама по умолчанию скрыта.

## 0. Статус production (2026-11-13, v1.3.2)

- Провайдер: `c57fb6e5-23e6-4d97-b7b4-66af8b7b9c43`,
  `Yandex RTB — главная`, `type=yandex`, `placement=in-feed`,
  `audience=both`, `enabled=true`, priority 10, format horizontal,
  `config.block_id=R-A-20411736-1`, `require_consent=false`,
  `exclude_adult=true`, cap 0.
- Loader и CSP развёрнуты; guest и authenticated `/api/v1/ads/config` отдают
  только публичный `config`, без секретов.
- `ads.txt` — 9 строк, прямой `200 text/plain` на 80, 443 и 8088, без
  редиректа. В файле есть `yandex.com, 20411736, DIRECT` и
  `yandex.com, 334843219, DIRECT`.
- **Внешний блокер:** реальный Yandex SDK отвечает
  `PAGE_DISABLED Page "20411736" is disabled`, пока владелец не включит
  площадку/блок в кабинете РСЯ. Это не ошибка кода.
- **Модерация РСЯ:** отклонена из-за менее 100 реальных посетителей в неделю.
  Повторная подача — с **2026-11-20 05:55**. До этого реальный показ рекламы
  не гарантирован; накрутки и боты запрещены.
- Consent banner относится к cookie/статистике. Яндекс RTB показывается при
  `granted`, `denied` и `null`; другие провайдеры с `require_consent=true`
  по-прежнему ждут согласия.

## 1. Провайдеры и слоты

Одна запись в админке — это провайдер + один слот. Провайдер можно выключить,
не удаляя его настройки и ключи.

| Поле | Значения | Назначение |
| --- | --- | --- |
| `type` | `yandex`, `adfox`, `google`, `custom_html`, `custom_script` | Тип интеграции |
| `placement` | `header`, `sidebar`, `in-feed`, `post-chapter`, `mobile-sticky` | Где показывать |
| `audience` | `guest`, `authenticated`, `both` | Кому показывать |
| `priority` | 0–10000 | Меньшее число показывается первым |
| `frequency_cap` | 0–1000 | Показов на браузер за 24 часа; 0 — без лимита |
| `schedule_days` | `[]` или `[0..6]` | Дни недели, 0 — понедельник; пусто — каждый день |
| `schedule_start` / `schedule_end` | `ЧЧ:ММ` | Окно показа; окно через полночь поддерживается |
| `timezone` | IANA, например `Europe/Moscow` | Часовой пояс расписания |
| `width` / `height` / `format` | px / строка | Зарезервированный размер и подпись формата |
| `exclude_adult` | bool, по умолчанию `true` | Не показывать на 18+ тайтлах |
| `hide_for_donors` | bool | Скрывать для Pro/донатеров |
| `require_consent` | bool | Показывать только после согласия CMP |
| `config` | JSON-объект | Публичные несекретные параметры (например, `block_id`) |
| `custom_html` | HTML | Только для `custom_html`; очищается на сервере |
| `custom_script` | JS | Только для `custom_script`; выполняется в sandbox-iframe |

Слоты фронтенда:

| Слот | Где рендерится |
| --- | --- |
| `header` | под шапкой сайта, во всех публичных разделах |
| `sidebar` | на странице тайтла (на мобильных скрыт) |
| `in-feed` | на главной между блоками |
| `post-chapter` | в конце главы в reader (только при явной настройке) |
| `mobile-sticky` | фиксированная полоса над мобильной навигацией |

Для `custom_html` серверный санитайзер удаляет `script`, `iframe`, `object`,
`embed`, формы, `style`, обработчики `on*` и URL со схемами `javascript:`,
`vbscript:`, `data:`. Разметка дополнительно ограничена белым списком тегов.

Для `custom_script` исходник отдаётся браузеру как есть, поэтому в нём нельзя
размещать секреты. Он выполняется в `<iframe sandbox="allow-scripts">` без
`allow-same-origin`: скрипт не имеет доступа к DOM и cookie сайта.

## 2. Секретные ключи

Ключи хранятся в таблице `ad_secrets` в поле `value_encrypted`. Шифрование —
Fernet, ключ выводится из `CONTROL_SECRET_KEY` (тот же `SecretBox`, что и для
SSH-паролей control-сервиса).

- `GET /api/v1/admin/ads` возвращает только `name`, `hint` (`••••1234`) и
  `updated_at`; значение ключа не возвращается никогда;
- `PUT /api/v1/admin/ads/{id}/secrets/{name}` добавляет или заменяет ключ;
- `DELETE /api/v1/admin/ads/{id}/secrets/{name}` удаляет ключ;
- ключи можно называть произвольно (`api_key`, `adfox_token`, `partner_id`);
- все действия пишутся в `audit_log` как `ads.secret_set` /
  `ads.secret_deleted`; в аудите сохраняется имя и маска, но не значение;
- ключи не попадают в публичный конфиг, HTML, логи и audit details.

### Ротация ключей

1. Получите новый ключ у рекламной сети.
2. В админке откройте интеграцию → «Секретные ключи».
3. Сохраните новый ключ с тем же именем поверх старого.
4. Проверьте слот на тестовой странице (или временно выключите/включите
   провайдера).
5. После проверки отзовите старый ключ в кабинете провайдера.

Перезапуск сервисов не нужен: control-сервис читает актуальную строку из БД на
каждый запрос.

### Смена `CONTROL_SECRET_KEY`

`CONTROL_SECRET_KEY` — мастер-ключ. После его смены старые значения ключей
расшифровать нельзя. Порядок:

1. Сделайте резервную копию БД control.
2. Смените `CONTROL_SECRET_KEY` и перезапустите control (это единственный
   случай, когда перезапуск нужен).
3. Заново введите все рекламные ключи в админке.
4. Проверьте аудит и слоты.

Не используйте `CONTROL_SECRET_KEY` из `.env.example` в production.

## 3. API

### Админские маршруты (требуют admin JWT)

| Метод | Путь | Назначение |
| --- | --- | --- |
| `GET` | `/api/v1/admin/ads` | Список провайдеров и масок ключей |
| `POST` | `/api/v1/admin/ads` | Создать провайдера/слот |
| `PATCH` | `/api/v1/admin/ads/{id}` | Изменить провайдера/слот |
| `DELETE` | `/api/v1/admin/ads/{id}` | Удалить провайдера и его ключи |
| `PUT` | `/api/v1/admin/ads/{id}/secrets/{name}` | Добавить/заменить ключ |
| `DELETE` | `/api/v1/admin/ads/{id}/secrets/{name}` | Удалить ключ |

### Публичный маршрут

`GET /api/v1/ads/config` — возвращает только включённые слоты, подходящие
текущей аудитории, расписанию и политикам. Параметры:

- `adult=1` — страница 18+ тайтла;
- `consent=1` — пользователь дал согласие (передаётся фронтендом из CMP).

Аудитория определяется по JWT: без токена — `guest`, с валидным токеном —
`authenticated`. Ответ не содержит ключей и административных полей. Публичный
`config` отдаётся как есть (для Яндекса — `block_id`), поэтому секреты в него
класть нельзя.

Пример синтетического ответа:

```json
[
  {
    "id": "00000000-0000-0000-0000-000000000000",
    "name": "QA header",
    "type": "custom_html",
    "placement": "header",
    "priority": 100,
    "audience": "both",
    "frequency_cap": 3,
    "format": "728x90",
    "width": 728,
    "height": 90,
    "content": "<div class=\"qa-banner\">Синтетическая реклама</div>",
    "content_type": "html",
    "require_consent": false,
    "config": {}
  }
]
```

Для сетевых типов (`yandex`, `adfox`, `google`) публичный ответ содержит
`content_type: "none"`. Для `yandex` фронтенд рендерит реальный RTB-блок по
`config.block_id`; для остальных сетевых типов показывается нейтральный
заполнитель до подключения отдельного адаптера. Секретный ключ в ответ не
попадает.

## 4. Поведение фронтенда

Компонент `apps/web/src/components/ads/AdSlot.tsx`:

- делает один запрос `/ads/config` на страницу (React Query, staleTime 60 с);
- не рендерит пустой контейнер, если слот не настроен;
- резервирует высоту `width × height` (или размер по умолчанию для слота) до
  загрузки баннера — поздняя загрузка/ошибка не вызывает CLS;
- ограничивает показы через `localStorage` (`frequency_cap` за 24 часа);
- при сетевой ошибке, 4xx/5xx, adblock или пустом ответе тихо возвращает
  `null`, без `console.error`;
- для `custom_html` использует `dangerouslySetInnerHTML` только после
  серверной очистки; при ошибке загрузки картинки показывает нейтральный
  заполнитель;
- для `custom_script` использует sandbox-iframe;
- для `yandex` проверяет `config.block_id` по `R-A-\d+-\d+`, рендерит
  `<div id="yandex_rtb_<block_id>">` и регистрирует callback в
  `window.yaContextCb`, который вызывает
  `Ya.Context.AdvManager.render({blockId, renderTo})`;
- повторный render в React StrictMode подавляется ref-ключом
  `slot.id:block_id` и маркером на контейнере; при смене слота/блока render
  выполняется заново;
- невалидный или отсутствующий `block_id`, adblock и ошибка SDK не ломают
  страницу: остаётся заполнитель/зарезервированная высота без `console.error`;
- для `yandex` `require_consent` не включается в production-конфиге: блок
  показывается независимо от выбора cookie. Для остальных провайдеров
  `require_consent=true` продолжает скрывать слот до `granted`;
- на мобильных `mobile-sticky` поднимает нижний отступ `.site-main`, чтобы не
  перекрывать контент и кнопки; при наличии APK-баннера слот сдвигается выше.

Loader подключается ровно один раз в `apps/web/index.html` до SPA:

```html
<script>window.yaContextCb=window.yaContextCb||[]</script>
<script src="https://yandex.ru/ads/system/context.js" async></script>
```

Reader: `post-chapter` добавлен в конец вертикального режима чтения. Если слот
не создан или выключен, в reader рекламы нет.

### Яндекс РСЯ RTB

- Блок production: `R-A-20411736-1`.
- В админке у провайдера типа `yandex` есть публичное поле **Block ID**; оно
  сохраняется в `config.block_id` и не является секретом.
- `apps/web/public/ads.txt` содержит 9 строк, отдаваемых production по
  `/ads.txt` (включая `yandex.com, 334843219, DIRECT` и
  `yandex.com, 20411736, DIRECT`). После `npm run build` файл обязан быть в
  `dist/ads.txt` — это проверяет `scripts/check-ads-txt.mjs` (`postbuild`).
- Провайдер создаётся через admin API после деплоя:

```http
POST /api/v1/admin/ads
Authorization: Bearer <admin JWT>
Content-Type: application/json

{
  "name": "Яндекс РСЯ — in-feed",
  "type": "yandex",
  "placement": "in-feed",
  "audience": "both",
  "config": {"block_id": "R-A-20411736-1"},
  "require_consent": false,
  "exclude_adult": true
}
```

`require_consent=false` — осознанное решение владельца: RTB показывается
независимо от cookie-баннера. Для custom-провайдеров, которым нужно согласие,
оставляйте `require_consent=true`.

## 5. CSP

`infra/nginx/default.conf` отправляет CSP на всех HTML-маршрутах:

```nginx
add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline' https://yandex.ru https://an.yandex.ru https://yastatic.net; style-src 'self' 'unsafe-inline'; img-src 'self' data: http: https:; font-src 'self' data:; connect-src 'self' https:; frame-src 'self' https://yandex.ru https://an.yandex.ru; object-src 'none'; base-uri 'self'; frame-ancestors 'self'; form-action 'self'" always;
```

Важно:

- `script-src` разрешает `yandex.ru`, `an.yandex.ru` и `yastatic.net` для
  загрузчика и динамических скриптов RTB; `frame-src` — для рекламного
  iframe; `connect-src` уже покрывает HTTPS-запросы;
- `frame-src 'self'` остаётся нужным для iframe с `srcdoc`
  (`custom_script`), не заменяйте его списком Яндекса;
- `'unsafe-inline'` в `script-src` нужен текущим inline-скриптам темы,
  canonical и `yaContextCb` в `index.html`. Если его убирать, понадобятся
  nonce/хеши для всех inline-скриптов;
- `img-src` допускает `http:` и `https:` для обложек и баннеров;
- не ослабляйте `frame-ancestors` и `object-src` ради рекламы.

## 6. Приватность и согласие

- Публичный конфиг не содержит персональных данных и секретов. JWT нужен только
  для выбора аудитории `guest`/`authenticated`.
- Провайдер с `require_consent=true` не попадает в ответ, пока CMP не выставил
  согласие. Ключ согласия на фронтенде: `localStorage['mp-ads-consent'] =
  'granted'` (хелперы `setAdsConsent`/`hasAdsConsent` в
  `apps/web/src/api/ads.ts`).
- Первопартийный баннер `ConsentBanner` теперь про cookie/статистику:
  заголовок «Cookie», текст «Используем cookie для входа, настроек и
  статистики», кнопки «Принять» / «Только необходимые». Ключ
  `localStorage['mp-ads-consent']` сохранён для совместимости, но реклама
  глобально от него не зависит. Баннер не modal и не блокирует чтение.
- Яндекс РСЯ создаётся с `require_consent=false` и показывается при
  `granted`, `denied` и `null`. Для других провайдеров `require_consent=true`
  по-прежнему скрывает слот до согласия — эта логика не удалена.
- `AdSlot` подписан на изменение согласия (`useAdsConsent`) и включает
  consent в query key, поэтому после accept/reject конфиг перезапрашивается,
  а `require_consent`-слоты появляются/исчезают без перезагрузки.
- Изменить выбор можно на `/privacy` (блок «Cookie и статистика») или по
  ссылке «Настройки cookie» в футере.
- Не передавайте в `config`, `custom_html` и `custom_script` значения, которые
  нельзя показывать пользователю: эти поля публичны.
- Для 18+ тайтлов `exclude_adult=true` по умолчанию. Включать рекламу на таких
  страницах можно только после юридической проверки; age-gate не заменяет
  проверку политики рекламной сети.

## 7. 18+ политика

Текущее поведение:

- страницы тайтла и reader передают `adult=1`, если у тайтла `adult=true`;
- control-сервис исключает все слоты с `exclude_adult=true`;
- администратор может снять флаг у конкретного слота, но это осознанное
  исключение и должно быть согласовано с правилами провайдера.

Рекомендация по умолчанию: не показывать рекламу на 18+ тайтлах вообще,
особенно в reader. Если бизнес настаивает — отдельные слоты, отдельная
проверка age-gate и письменное подтверждение от рекламной сети.

## 8. Как добавить нового провайдера

1. **Модель.** Добавьте тип в `AdProviderType` (`services/control/app/ads.py`) и
   подпись в `TYPE_LABELS` (`apps/web/src/components/admin/AdsPanel.tsx`).
2. **Публичные параметры.** Если сети нужен block id/partner id, сохраняйте его
   в `config` — это не секрет. Секретный токен добавляйте через раздел
   «Секретные ключи», не в `config`.
3. **Рендер.** Создайте адаптер в `apps/web/src/components/ads/` и подключите его
   в `AdSlot` по `slot.type`. Для сторонних скриптов используйте sandbox-iframe
   или загрузку SDK с явным CSP-разрешением.
4. **Backend.** Если нужен серверный вызов (reporting, server-side targeting),
   добавьте метод в `AdsService` и используйте `self.box.decrypt(...)`; никогда
   не возвращайте расшифрованное значение в API.
5. **CSP.** Добавьте домены провайдера в `script-src`, `connect-src`,
   `frame-src`, `img-src` и проверьте страницу в Chrome без ошибок CSP.
6. **Тесты.** Добавьте тест на фильтрацию аудитории, маскирование ключа и
   audit. Для UI проверьте 390×844 и 1440×900, а также сценарий «adblock».
7. **Документация.** Обновите эту страницу и `CHANGELOG`/issue.

### Синтетические ключи для QA

В тестах и локальной проверке используйте значения вида
`synthetic-yandex-key-1234`, `qa-adfox-token-0000`. Не используйте реальные
ключи, не коммитьте их и не вставляйте в скриншоты.

### Выкладка Яндекс РСЯ

Выполнено в v1.3.2 (13.11.2026):

1. Ветка `feat/yandex-rtb` смержена в `main`; тег `v1.3.2` — `affe7d0`.
2. Web пересобран из `main` с `VITE_SITE_URL=https://85.192.37.58.nip.io`;
   `dist` не содержит `:8443`. Nginx получил только CSP-разрешения и
   exact-locations для `ads.txt`.
3. Проверены заголовки: CSP содержит `https://yandex.ru`,
   `https://an.yandex.ru`, `https://yastatic.net`;
   `GET /ads.txt` на 80/443/8088 — `200 text/plain`, 9 строк.
4. Провайдер создан через admin API с `require_consent=false`,
   `exclude_adult=true`, `config={"block_id":"R-A-20411736-1"}`.
5. На главной создаётся контейнер `yandex_rtb_R-A-20411736-1`, loader
   `context.js` загружается; реальный блок ждёт включения площадки в кабинете
   Яндекса (`PAGE_DISABLED`).
6. Cookie-баннер не блокирует скролл; RTB-слот не зависит от выбора
   «Принять»/«Только необходимые».

## 9. Проверка перед выкладкой

- [ ] `pytest tests/control/test_ads.py` проходит.
- [ ] `npm run typecheck`, `npm test` и `npm run build` в `apps/web` проходят;
      build проверяет наличие `dist/ads.txt`.
- [ ] В админке: создать/изменить/выключить/удалить провайдера, добавить и
      удалить ключ, увидеть маску и запись аудита.
- [ ] Для `yandex` поле Block ID сохраняется в `config.block_id`; невалидный
      ID не ломает страницу и показывает заполнитель.
- [ ] Гость не видит `authenticated`-слоты; авторизованный не видит
      `guest`-слоты.
- [ ] Yandex RTB рендерится при `granted`, `denied` и `null`; слот с
      `require_consent=true` всё ещё скрыт до согласия.
- [ ] Выключенный провайдер и запрос `/ads/config` с ошибкой не дают ошибок в
      консоли и не двигают layout.
- [ ] Mobile 390×844: `mobile-sticky` не перекрывает навигацию/кнопки,
      cookie-баннер компактный и не блокирует скролл.
- [ ] Web 1440×900: `header`/`in-feed`/`sidebar` не ломают сетку.
- [ ] Reader: без явного `post-chapter` рекламы нет.
- [ ] CSP-заголовок проверен в DevTools → Network → Response Headers;
      `context.js` и рекламный iframe Яндекса не заблокированы.
- [ ] `GET /ads.txt` на 80/443/8088 отдаёт 200 `text/plain` и ровно 9 строк,
      без redirect.
- [ ] Реальный RTB: если SDK вернул `PAGE_DISABLED`, зафиксировать это как
      owner action в кабинете Яндекса, а не как дефект фронтенда.

Для расписания нужен пакет `tzdata` (добавлен в
`services/control/requirements.txt`); на slim-образах без системной tzdata он
обязателен.

## 10. Скриншоты QA

Скриншоты синтетических слотов (без реальных рекламных ключей):

- `docs/screenshots/ads-admin-desktop.png` — список интеграций и маска ключа;
- `docs/screenshots/ads-admin-key-section.png` — управление ключом (только
  `api_key ••••1234`);
- `docs/screenshots/ads-admin-mobile-390.png` — админка 390×844;
- `docs/screenshots/ads-guest-web-1440.png` — гость, web 1440×900;
- `docs/screenshots/ads-guest-mobile-390.png` — гость, mobile sticky;
- `docs/screenshots/ads-auth-mobile-390.png` — авторизованный слот.
