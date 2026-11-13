# SEO: slug-URL, серверный prerender, JSON-LD, sitemap и индексация

Статус: **deployed in production** (v1.3.0, hotfix v1.3.2; 13.11.2026,
`main` @ `affe7d0`). Публичный сайт — <https://85.192.37.58.nip.io> на
80/443. `:8443` — legacy API только для APK 1.3.0, веб-страницы там 301;
`:8088` — redirect, кроме `/ads.txt`. Canonical, OG и sitemap не содержат порт.

Дата: 2026-11-13.

## 1. Что изменилось относительно v1.2

В v1.2 SEO-метаданные собирались на клиенте (`apps/web/src/lib/seo.ts`), а
nginx отдавал один `index.html` на все маршруты. Это не закрывало три
требования:

1. старые URL `/manga/{id}` не редиректились на человекочитаемый slug;
2. социальные боты и поисковики без JS не видели title/description/OG/JSON-LD;
3. `noindex` для reader/пустого поиска/admin/library появлялся только после
   выполнения JavaScript.

В v2 добавлены:

- стабильный `url_slug` в каталоге и URL `/manga/{id}-{slug}`;
- HTTP 301 со старого `/manga/{id}` и со stale slug на канонический slug;
- gateway-пререндер карточек, reader-шеллов, каталога и приватных разделов;
- серверный `X-Robots-Tag` и `meta robots` для noindex-маршрутов;
- env-driven verification-теги для Google/Yandex;
- slug-URL и исключение 18+ в sitemap.

## 2. Контракт URL и slug

### 2.1 Формат

```
https://85.192.37.58.nip.io/manga/{uuid}-{url_slug}
```

- `uuid` — единственный ключ маршрутизации, он стабилен навсегда;
- `url_slug` — косметический транслитерированный заголовок;
- slug не участвует в поиске записи и не должен быть глобально уникальным:
  два тайтла с одинаковым названием получают разные URL благодаря UUID;
- slug хранится в `manga.url_slug` (не в source-owned `manga.slug`);
- при смене названия slug **не** пересчитывается: индексированный URL не
  должен «переезжать». Старый slug с тем же UUID получает 301 на текущий.

### 2.2 Редиректы

| Запрос | Ответ |
| --- | --- |
| `GET /manga/{id}` | `301` → `/manga/{id}-{url_slug}` |
| `GET /manga/{id}-{old-slug}` | `301` → `/manga/{id}-{url_slug}` |
| `GET /manga/{id}-{url_slug}` | `200` (бот — HTML-карточка, человек — SPA) |
| `GET /manga/{unknown-id}` | `404` для бота; SPA для человека |

Query-строка сохраняется при 301. Редирект отдаёт gateway, а не React:
`services/gateway/app/prerender.py`, `_manga_route()`.

### 2.3 Backfill 78k строк

`manga.url_slug` добавляется идемпотентной миграцией
(`services/catalog/app/migrations.py`). Startup не ждёт пересчёта:

1. `ensure_runtime_schema` добавляет nullable-колонку и индекс;
2. `slug_backfill.py` в фоне читает пачки по 500 строк, коммитит каждую пачку
   и завершает работу, когда пустых строк не осталось;
3. read-path (`ensure_url_slug`) вычисляет slug на лету, поэтому slug-URL
   работает сразу после деплоя, даже если backfill ещё не дошёл до строки;
4. повторный запуск идемпотентен: уже заполненные slug не перезаписываются;
5. backfill сохраняет `updated_at` (`updated_at = updated_at` в Core UPDATE),
   иначе все 78k тайтлов выглядели бы «обновлёнными» и sitemap `lastmod`
   массово сдвинулся бы на дату деплоя.

Переменные:

```dotenv
URL_SLUG_BACKFILL_ENABLED=true
URL_SLUG_BACKFILL_BATCH_SIZE=500
URL_SLUG_BACKFILL_YIELD_SECONDS=0.05
```

### 2.4 Юридические страницы

Публичные юридические маршруты индексируются и имеют собственные
title/description/canonical:

| Маршрут | title | canonical | robots |
| --- | --- | --- | --- |
| `/terms` | Пользовательское соглашение — MangaPoisk Reborn | `/terms` | index,follow |
| `/privacy` | Политика конфиденциальности — MangaPoisk Reborn | `/privacy` | index,follow |
| `/dmca` | Правообладателям и DMCA — MangaPoisk Reborn | `/dmca` | index,follow |
| `/contacts` | Контакты и реквизиты — MangaPoisk Reborn | `/contacts` | index,follow |
| `/age` | Возрастное ограничение 18+ — MangaPoisk Reborn | `/age` | index,follow (видимое предупреждение 18+) |

Каждый из маршрутов `/terms`, `/privacy`, `/dmca`, `/contacts`, `/age`
добавляет один JSON-LD `WebPage`:

- `name`, `description`, `url` (self-canonical), `inLanguage: ru`,
  `dateModified` (дата редакции);
- `isPartOf` → `WebSite` MangaPoisk Reborn;
- `publisher` → `Organization` только если `LEGAL_OWNER_NAME` заполнен;
  вымышленные реквизиты не выводятся.

## 3. Серверный prerender

### 3.1 Кто получает что

| User-Agent | Ответ |
| --- | --- |
| Googlebot, YandexBot, Bingbot, Twitterbot, TelegramBot, VK, Facebook, LinkedIn, Discord, Slack, WhatsApp, Applebot, Baiduspider и т.п. | готовый HTML без JS |
| Обычный браузер | настоящий `index.html` SPA (гидратация не меняется) |
| Неизвестный UA | SPA |

Allowlist находится в `services/gateway/app/prerender.py` (`_BOT_RE`).
Содержимое для ботов и людей описывает один и тот же тайтл; отличается только
оболочка (HTML-карточка против SPA shell), это не клоакинг.

### 3.2 Маршрутизация nginx

`infra/nginx/default.conf` проксирует на gateway только SEO-маршруты:

- `^~ /manga/`
- `^~ /reader/`, `^~ /read/`
- `= /catalogue`, `= /catalog`, `= /catalog/genres`
- `= /library`, `= /profile`, `= /admin`, `= /login`, `= /register`

Gateway для человека проксирует `index.html` из `WEB_INTERNAL_URL`
(production: `http://127.0.0.1:8089`), а для бота отдаёт prerender. Это
сохраняет SPA и одновременно даёт HTTP 301 на старый URL.

`/sitemap.xml`, `/api/`, `/assets/`, `/themes/` и остальные пути остаются как
раньше.

### 3.3 Кэш и заголовки

- HTML бота кэшируется в процессе gateway 60 секунд;
- `Cache-Control: public, max-age=60, stale-while-revalidate=300`;
- `Vary: User-Agent` обязателен: один URL отдаёт разный HTML боту и человеку;
- при ошибке обновления отдаётся stale-копия;
- если каталог недоступен и кэша нет — бот получает `200` generic-шелл с
  `noindex,follow`, а не `5xx`;
- SPA-ответ: `Cache-Control: no-cache`, `X-Prerender: spa`;
- ответы с ошибкой/fallback: `Cache-Control: no-store`.

### 3.4 Точный пример HTML для бота

`GET /manga/23d337ac-d72d-4fd6-9cda-e314d72ddafd-vanpanchmen`
с `User-Agent: Googlebot/2.1`:

```html
<!doctype html>
<html lang="ru">
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Ванпанчмен — читать онлайн на русском | MangaPoisk Reborn</title>
    <meta name="description" content="Сайтама — герой по приколу. Описание, список глав и читалка MangaPoisk Reborn." />
    <meta name="robots" content="index,follow,max-image-preview:large" />
    <link rel="canonical" href="https://85.192.37.58.nip.io/manga/23d337ac-d72d-4fd6-9cda-e314d72ddafd-vanpanchmen" />
    <meta property="og:type" content="book" />
    <meta property="og:locale" content="ru_RU" />
    <meta property="og:site_name" content="MangaPoisk Reborn" />
    <meta property="og:title" content="Ванпанчмен — читать онлайн на русском | MangaPoisk Reborn" />
    <meta property="og:description" content="Сайтама — герой по приколу. Описание, список глав и читалка MangaPoisk Reborn." />
    <meta property="og:url" content="https://85.192.37.58.nip.io/manga/23d337ac-d72d-4fd6-9cda-e314d72ddafd-vanpanchmen" />
    <meta property="og:image" content="https://cdn.example/cover.jpg" />
    <meta property="og:image:alt" content="Обложка «Ванпанчмен»" />
    <meta name="twitter:card" content="summary_large_image" />
    <meta name="twitter:title" content="Ванпанчмен — читать онлайн на русском | MangaPoisk Reborn" />
    <meta name="twitter:description" content="Сайтама — герой по приколу. Описание, список глав и читалка MangaPoisk Reborn." />
    <meta name="twitter:image" content="https://cdn.example/cover.jpg" />
    <meta name="twitter:image:alt" content="Обложка «Ванпанчмен»" />
    <meta name="google-site-verification" content="GOOGLE_TOKEN" />
    <meta name="yandex-verification" content="YANDEX_TOKEN" />
    <script type="application/ld+json" data-seo="json-ld">{"@context":"https://schema.org","@graph":[{"@type":["ComicStory","Book"],"@id":"https://85.192.37.58.nip.io/manga/23d337ac-d72d-4fd6-9cda-e314d72ddafd-vanpanchmen#comic","name":"Ванпанчмен","url":"https://85.192.37.58.nip.io/manga/23d337ac-d72d-4fd6-9cda-e314d72ddafd-vanpanchmen","inLanguage":"ru","isFamilyFriendly":true,"description":"Сайтама — герой по приколу. Описание, список глав и читалка MangaPoisk Reborn.","image":"https://cdn.example/cover.jpg","alternateName":["One Punch Man","One Punch-Man"],"genre":["Экшен","Комедия"],"copyrightYear":2012,"dateModified":"2026-11-01T00:00:00+00:00","sameAs":"https://source.example/manga/1","aggregateRating":{"@type":"AggregateRating","ratingValue":9.1,"ratingCount":1200,"bestRating":10,"worstRating":1}},{"@type":"BreadcrumbList","itemListElement":[{"@type":"ListItem","position":1,"name":"Главная","item":"https://85.192.37.58.nip.io/"},{"@type":"ListItem","position":2,"name":"Каталог","item":"https://85.192.37.58.nip.io/catalogue"},{"@type":"ListItem","position":3,"name":"Ванпанчмен","item":"https://85.192.37.58.nip.io/manga/23d337ac-d72d-4fd6-9cda-e314d72ddafd-vanpanchmen"}]}]}</script>
</head>
<body>
  <header>…MangaPoisk Reborn…</header>
  <main>
    <nav aria-label="Хлебные крошки">Главная / Каталог / Ванпанчмен</nav>
    <article>
      <img src="https://cdn.example/cover.jpg" alt="Обложка «Ванпанчмен»" width="220" />
      <h1>Ванпанчмен</h1>
      <p>One Punch Man · One Punch-Man</p>
      <p>2012 · Экшен, Комедия · Глав: 2</p>
      <p>Сайтама — герой по приколу…</p>
      <p><a href="https://85.192.37.58.nip.io/manga/23d337ac-d72d-4fd6-9cda-e314d72ddafd-vanpanchmen">Открыть тайтл в читалке MangaPoisk</a></p>
    </article>
    <section>
      <h2>Последние главы</h2>
      <ol>
        <li><a href="https://85.192.37.58.nip.io/reader/11111111-1111-1111-1111-111111111111">Глава 2 — Глава 2</a></li>
      </ol>
    </section>
  </main>
</body>
</html>
```

Все пользовательские строки проходят через `html.escape(..., quote=True)`;
JSON-LD дополнительно заменяет `<`, `>` и `&` на `\u003c`, `\u003e`, `\u0026`,
поэтому title/description с `</script>` не может закрыть script-тег.

### 3.5 Reader

`GET /reader/{chapterId}` с UA бота:

- HTTP `200`;
- `<meta name="robots" content="noindex,follow">`;
- `X-Robots-Tag: noindex, follow`;
- canonical на `/manga/{mangaId}-{url_slug}`;
- ссылка «Открыть страницу тайтла».

Для человека gateway отдаёт SPA, а клиентский `useSeo` повторяет
`noindex,follow` и canonical. То же для `/read/{chapterId}`.

### 3.6 Каталог

- `/catalogue` без `q` — indexable, если каталог вернул результаты;
- `/catalogue?q=` (пустой параметр) — `noindex,follow` + `X-Robots-Tag`;
- `/catalogue?q=…` с непустой выдачей — indexable, canonical сохраняет `q`,
  `source`, `genre(s)`, `year`, `status`, `page`;
- `/catalogue?q=…` с нулём результатов — `noindex,follow`;
- ошибка каталога — `noindex,follow`, generic-шелл, не `5xx`.

`sort` в canonical не попадает.

### 3.7 Приватные разделы

`/library`, `/profile`, `/admin`, `/login`, `/register`:

- nginx добавляет `X-Robots-Tag: noindex, nofollow` через `map $request_uri`;
- gateway для бота отдаёт HTML с `noindex,nofollow`;
- для человека — SPA.

## 4. Sitemap и robots.txt

`apps/web/public/robots.txt`:

```text
User-agent: *
Allow: /
Disallow: /api/
Disallow: /admin
Disallow: /library
Disallow: /profile
Disallow: /login
Disallow: /register
Disallow: /offline/

Sitemap: https://85.192.37.58.nip.io/sitemap.xml
```

`/reader/` не закрыт в robots: страницы должны отдать `noindex`, иначе
краулер не увидит директиву. Sitemap (`services/gateway/app/seo.py`):

- `GET /sitemap.xml` и alias `GET /api/v1/sitemap.xml`;
- только `https://85.192.37.58.nip.io` (production-валидация запрещает
  HTTP `PUBLIC_WEB_URL`);
- статические `/`, `/catalogue`, `/sources`;
- юридические страницы: `/terms`, `/privacy`, `/dmca`, `/contacts`, `/age`
  с датой редакции в `lastmod`. `/age` включён осознанно: это содержательная
  публичная политика с видимым предупреждением 18+, а не doorway-страница;
- только slug-URL `/manga/{id}-{url_slug}`;
- только тайтлы с главами;
- `Manga.adult = false` — 18+ исключены;
- reader, профили, библиотека, admin в sitemap не попадают;
- `lastmod` из `last_chapter_at`/`updated_at`, будущие даты отбрасываются;
- лимит 50 000 URL / 50 MB; при превышении нужен sitemap index (см. риски);
- кэш 30 минут, `Cache-Control: public, max-age=900,
  stale-while-revalidate=3600`;
- stale fallback при падении каталога;
- прогрев кэша в фоне при старте gateway.

Проверка:

```bash
curl -sk https://85.192.37.58.nip.io/sitemap.xml \
  | python -c "import sys,xml.etree.ElementTree as ET; r=ET.fromstring(sys.stdin.buffer.read()); ns='{http://www.sitemaps.org/schemas/sitemap/0.9}'; u=[e.text for e in r.findall(ns+'url/'+ns+'loc')]; print(len(u)); print(all(x.startswith('https://85.192.37.58.nip.io/') for x in u)); print(all('/manga/' not in x or '-' in x.rsplit('/',1)[-1] for x in u))"
```

## 5. Verification-теги без доступа к панелям

Теги берутся из env и попадают в два места:

1. `apps/web/index.html` — Vite-плагин `seo-verification` в
   `apps/web/vite.config.ts` при сборке;
2. gateway prerender — `_verification_tags()` в `prerender.py`.

```dotenv
GOOGLE_SITE_VERIFICATION=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
YANDEX_VERIFICATION=yyyyyyyyyyyyyyyyyyyyyyyy
```

Пустое значение = тег не выводится. Поддерживаются и `VITE_`-алиасы.

Ручная отправка (нужен доступ владельца):

1. **Google Search Console** → Add property → URL-prefix
   `https://85.192.37.58.nip.io/` → HTML tag → скопировать `content` в
   `GOOGLE_SITE_VERIFICATION` → пересобрать web и перезапустить gateway →
   Verify.
2. **Yandex Webmaster** → Добавить сайт → подтверждение мета-тегом →
   `YANDEX_VERIFICATION` → Verify.
3. Sitemaps → добавить `https://85.192.37.58.nip.io/sitemap.xml`.
4. Request indexing для `/`, `/catalogue` и 3–5 карточек тайтлов.
5. Через 1–2 недели проверить «Индексирование страниц» / «Страницы» и
   отчёты structured data.

## 6. Проверка ботов через curl

### Bash / Git Bash

```bash
BASE=https://85.192.37.58.nip.io
MANGA=/manga/23d337ac-d72d-4fd6-9cda-e314d72ddafd-vanpanchmen

curl -sk -D - -A "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)" \
  "$BASE$MANGA" | head -40
curl -sk -A "Mozilla/5.0 (compatible; YandexBot/3.0; +http://yandex.com/bots)" \
  "$BASE$MANGA" | grep -E '<title>|canonical|og:image|application/ld\+json'
curl -sk -o /dev/null -w '%{http_code} %{redirect_url}\n' \
  -A "Googlebot/2.1" "$BASE/manga/23d337ac-d72d-4fd6-9cda-e314d72ddafd"
curl -sk -o /dev/null -w '%{http_code}\n' \
  -A "Googlebot/2.1" "$BASE/reader/11111111-1111-1111-1111-111111111111"
curl -skI -A "Googlebot/2.1" "$BASE/reader/11111111-1111-1111-1111-111111111111" | grep -i x-robots
```

Ожидается:

- карточка: `200`, `text/html`, `Vary: User-Agent`, canonical slug-URL,
  `og:image`, один JSON-LD;
- старый URL: `301` и `Location` со slug;
- reader: `200` и `X-Robots-Tag: noindex, follow`;
- `?q=` пустой: `X-Robots-Tag: noindex, follow`.

### PowerShell

```powershell
$base = 'https://85.192.37.58.nip.io'
$ua = 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)'
$r = Invoke-WebRequest -Uri "$base/manga/23d337ac-d72d-4fd6-9cda-e314d72ddafd-vanpanchmen" -Headers @{ 'User-Agent' = $ua } -SkipCertificateCheck
$r.StatusCode
$r.Content | Select-String '<title>|canonical|application/ld\+json'
```

### JSON-LD validation

```bash
curl -sk -A "Googlebot/2.1" "$BASE$MANGA" \
  | python -c "import sys,re,json; h=sys.stdin.read(); m=re.search(r'<script type=\"application/ld\+json\"[^>]*>(.*?)</script>',h,re.S); d=json.loads(m.group(1)); print([n['@type'] for n in d['@graph']])"
```

Ожидается `[['ComicStory', 'Book'], 'BreadcrumbList']`.

## 7. Деплой (v1.3.0 выполнен; v1.3.2 — hotfix)

Последовательность ниже использовалась для v1.3.0 и остаётся runbook'ом.
v1.3.2 не менял SEO-код: web пересобран с `VITE_SITE_URL` без порта, nginx
получил только CSP/ads.txt-изменения, canonical/OG/sitemap проверены после
деплоя.

1. **Backup** БД и записать restic snapshot.
2. **Catalog** — задеплоить первым. Миграция добавит `url_slug` и индекс,
   backfill пойдёт в фоне. Проверить `/health` и что API отдаёт `url_slug`:
   `curl -sk .../api/v1/manga/{id} | jq .url_slug`.
3. **Gateway** — задеплоить с env:
   ```dotenv
   WEB_INTERNAL_URL=http://127.0.0.1:8089
   GOOGLE_SITE_VERIFICATION=...
   YANDEX_VERIFICATION=...
   ```
   Проверить `/sitemap.xml` и `curl` с Googlebot.
4. **Web** — собрать с теми же verification env и выложить `dist`:
   ```bash
   cd apps/web
   GOOGLE_SITE_VERIFICATION=... YANDEX_VERIFICATION=... npm run build
   ```
   Обновить `sw.js` версию, чтобы старый app shell не закэшировал прежний
   `index.html`.
5. **Nginx** — применить `infra/nginx/default.conf` (или только новые
   `location`/`map` из раздела 3.2), `nginx -t`, reload `mangapoisk-web`.
   Проверить, что `/manga/` и `/reader/` идут через gateway, а `/assets/` —
   статикой.
6. **Проверки**: раздел 6, sitemap, `robots.txt`, 0 console errors в браузере.
7. **Search Console / Yandex Webmaster** — только после появления тегов.

Откат: вернуть предыдущий `dist`, предыдущий gateway, убрать nginx
`location`/`map`; `url_slug` — additive-колонка, откат каталога её не ломает.

## 8. Чек-лист приёмки

Проверено при деплое v1.3.0/v1.3.2 (13.11.2026), кроме отмеченных ручных
пунктов владельца.

- [ ] `GET /manga/{id}-{slug}` с Googlebot/YandexBot: 200, полный HTML,
      canonical, OG/Twitter, JSON-LD без JS.
- [ ] `GET /manga/{id}`: 301 на slug-URL (не JS-редирект).
- [ ] `GET /manga/{id}-{old-slug}`: 301 на текущий slug.
- [ ] `GET /reader/{chapterId}`: `noindex,follow` + canonical на тайтл.
- [ ] `/catalogue?q=`: noindex; непустая выдача: indexable.
- [ ] `/library`, `/profile`, `/admin`, `/login`, `/register`: noindex.
- [ ] Sitemap: только HTTPS production-host, только slug-URL, без reader,
      18+ и приватных профилей.
- [ ] `url_slug` есть в API summary/detail и в `/internal/sitemap`.
- [ ] Backfill идемпотентен, startup не блокируется, 78k строк обрабатываются
      пачками.
- [ ] HTML escaping: title/description с `<script>` не ломают разметку и
      JSON-LD.
- [ ] Catalog-down: бот получает 200 generic/noindex, не 5xx.
- [ ] `Vary: User-Agent`, cache headers, stale fallback.
- [ ] `npm run typecheck`, `npm run build`, `pytest`, `ruff` — зелёные.
- [ ] Browser QA 1440×900 и 390×844: 0 console errors, Lighthouse SEO 1.0.

## 9. Browser QA и Lighthouse

Проверка выполнялась на локальной production-сборке (`vite build` +
`vite preview`) с локальным gateway/catalog/comments и реальными данными
каталога. Скриншоты:

- `docs/screenshots/seo-v2-manga-desktop-1440.png` — 1440×900;
- `docs/screenshots/seo-v2-manga-mobile-390.png` — 390×844.

Lighthouse 13.6, Edge headless, только SEO / accessibility / best-practices:

| Страница | Viewport | SEO | Accessibility | Best practices | Console errors |
| --- | --- | ---: | ---: | ---: | ---: |
| `/` | 1440×900 (desktop preset) | 1.0 | 1.0 | 96 | 0 |
| `/manga/{id}-{slug}` | 1440×900 (desktop preset) | 1.0 | 1.0 | 96 | 0 |
| `/manga/{id}-{slug}` | 390×844 (mobile) | 1.0 | 1.0 | 96 | 0 |
| `/` | 390×844 (mobile) | 1.0 | 1.0 | 96 | 0 |

Best practices 96/100 — это `valid-source-maps` (production-сборка намеренно
без source maps) и `inspector-issues`; к SEO отношения не имеет. Console
errors 0 после запуска локального comments-сервиса (первый прогон ловил
401 от чужого локального сервиса, это артефакт окружения, не ветки).

## 10. Риски

- **Кэш и Vary.** Один URL отдаёт разный HTML боту и человеку. Любой
  промежуточный кэш/CDN обязан учитывать `Vary: User-Agent`; иначе бот может
  получить SPA, а человек — prerender. В текущем single-node nginx кэша нет.
- **Дубли контента.** `/manga/{id}` и `/manga/{id}-{slug}` — один и тот же
  тайтл. 301 и canonical закрывают это; sitemap содержит только slug-URL.
- **Sitemap size.** Лимит 50 000 URL. Сейчас sitemap содержит ~25 189 URL
  при ~25 тыс. видимых тайтлов и 78 тыс.+ строк каталога. При росте нужно
  делить sitemap на index + чанки по 50k. Код ограничивает вывод и не отдаёт
  невалидный XML, но не делает index автоматически.
- **Slug backfill.** На 78k строк worker занимает время; read-path считает
  slug на лету, поэтому функциональность не блокируется. Во время backfill
  возможны два одинаковых slug у разных UUID — это безопасно, URL различаются
  id.
- **Soft 404 для людей.** Неизвестный человеческий URL по-прежнему получает
  SPA 200 (React показывает 404-компонент). Для ботов gateway отдаёт 404.
  Полное исправление — SSR/SSG, вне этой задачи.
- **Sitemap cache.** У каждого процесса gateway своя копия; при нескольких
  репликах кэш прогревается независимо.
- **Search Console / Webmaster.** Доступов нет; теги и инструкция готовы,
  подтверждение и отправка sitemap остаются ручными шагами владельца.

## 11. Источники

- Google Search Central — JavaScript SEO basics:
  https://developers.google.com/search/docs/crawling-indexing/javascript/javascript-seo-basics
- Google Search Central — canonical URL:
  https://developers.google.com/search/docs/crawling-indexing/consolidate-duplicate-urls
- Google Search Central — sitemaps:
  https://developers.google.com/search/docs/crawling-indexing/sitemaps/build-sitemap
- Google Search Central — structured data:
  https://developers.google.com/search/docs/appearance/structured-data/intro-structured-data
- Yandex Webmaster — индексация страниц с JavaScript:
  https://yandex.com/support/webmaster/en/yandex-indexing/rendering
- schema.org — ComicStory: https://schema.org/ComicStory
- schema.org — Book: https://schema.org/Book
