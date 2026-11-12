# SEO: метаданные, JSON-LD, sitemap и индексация

Статус: реализовано в ветке `feat/seo` (worktree), production не затронут.
Дата аудита и проверки: 2026-11-12.

## 1. Что было на production до изменений

Проверены `/`, `/catalogue`, `/manga/:id`, `/reader/:chapterId`, `/library`,
`/sources`, `/admin`, `/404` и `robots.txt`/`sitemap.xml`.

| Проверка | Результат до изменений |
| --- | --- |
| `lang` | `ru` — уже корректно |
| `title` | базовый на всех маршрутах; на manga/reader менялся только через `useDocumentTitle`, без описания |
| `description` | одна базовая на всех маршрутах |
| `canonical` | отсутствовал полностью |
| `meta robots` | отсутствовал |
| Open Graph | `og:type/locale/site_name/title/description` были; `og:url`, `og:image`, `og:image:alt` отсутствовали |
| Twitter Card | отсутствовал |
| JSON-LD | отсутствовал |
| `robots.txt` | был, без `Sitemap:` и без закрытия приватных разделов |
| `/sitemap.xml` | отдавал `index.html` SPA (HTTP 200, `text/html`) — sitemap не существовал |
| HTTP-код 404 | SPA отвечает 200 на неизвестный маршрут (soft 404) — ограничение client-side routing |
| Alt у изображений | у содержательных обложек alt есть; декоративные превью — с пустым alt (корректно) |

## 2. Архитектура SEO-слоя

Сайт остаётся SPA: nginx отдаёт один `index.html`, React строит страницу на
клиенте. SEO-слой состоит из трёх частей.

1. **Базовые метаданные** — `apps/web/index.html`: `lang=ru`, title,
   description, robots, canonical, OG/Twitter defaults, theme-color,
   manifest, preconnect к хостам обложек.
2. **Маршрутные метаданные** — `apps/web/src/lib/seo.ts`, хук `useSeo`:
   - обновляет `document.title`, description, robots, canonical, OG/Twitter;
   - добавляет JSON-LD (`application/ld+json`);
   - при размонтировании восстанавливает предыдущие значения, поэтому
     stale canonical/robots/JSON-LD не переходят между маршрутами;
   - не тянет внешних зависимостей (~380 строк с комментариями, без SEO-фреймворка).
3. **Индексация** — `apps/web/public/robots.txt` и динамический
   `/sitemap.xml` в gateway.

### Canonical до загрузки React

В `index.html` есть canonical-placeholder и маленький inline-скрипт: он
сразу заменяет canonical и `og:url` на `location.origin + pathname`. Это
закрывает случай, когда краулер читает HTML до выполнения бандла. После
загрузки данных `useSeo` уточняет canonical (например, для читалки — на
страницу тайтла).

Google рекомендует по возможности задавать canonical в исходном HTML и не
менять его JavaScript'ом; в SPA без SSR это невозможно для всех маршрутов.
Компромисс: исходный HTML получает корректный self-canonical, а JS меняет
его только там, где канонический URL действительно другой (reader →
страница тайтла). Это соответствует документированному исключению Google
для случаев, когда canonical нельзя задать в HTML.

## 3. Матрица маршрутов

| Маршрут | title | canonical | robots |
| --- | --- | --- | --- |
| `/` | MangaPoisk Reborn — читалка манги и манхвы онлайн | `/` | index,follow,max-image-preview:large |
| `/catalogue`, `/catalog` | Каталог манги и манхвы на русском | `/catalogue` + стабильные фильтры + `page` (если > 1) | index,follow; `noindex,follow` для поиска `?q=`, пустой выдачи и ошибки API |
| `/catalogue?q=…` | «…» — поиск манги | `/catalogue?q=…` | noindex,follow (thin search results) |
| `/manga/:id` | {title} — читать онлайн на русском | `/manga/:id` | index,follow,max-image-preview:large; noindex при ошибке |
| `/reader/:chapterId`, `/read/:chapterId` | {chapter} — {title} | `/manga/:mangaId` после загрузки | noindex,follow |
| `/sources` | Источники манги и манхвы | `/sources` | index,follow |
| `/terms` | Пользовательское соглашение — MangaPoisk Reborn | `/terms` | index,follow |
| `/privacy` | Политика конфиденциальности — MangaPoisk Reborn | `/privacy` | index,follow |
| `/dmca` | Правообладателям и DMCA — MangaPoisk Reborn | `/dmca` | index,follow |
| `/contacts` | Контакты и реквизиты — MangaPoisk Reborn | `/contacts` | index,follow |
| `/age` | Возрастное ограничение 18+ — MangaPoisk Reborn | `/age` | index,follow (видимое предупреждение 18+) |
| `/library`, `/profile`, `/login`, `/register`, `/admin`, `/offline/*` | свои title | нет | noindex,nofollow |
| `/404` и `*` | Страница не найдена | нет | noindex,follow |

Правила canonical для каталога:

- `sort` всегда отбрасывается — сортировка не создаёт новую страницу;
- `page` сохраняется при `page > 1` — это self-canonical пагинации, а не
  дубль первой страницы;
- `q`, `source`, `genre`/`genres`, `year`, `status` сохраняются, чтобы
  фильтрованные landing-страницы не склеивались с общим каталогом;
- `/catalog` и `/catalog/genres` канонизируются на `/catalogue` (primary
  маршрут; `genres` из hash переносится в query).

## 4. JSON-LD

### Главная

`@graph` из двух узлов:

- `WebSite` + `SearchAction` (`/catalogue?q={search_term_string}`);
- `Organization` с логотипом и `sameAs` на GitHub-репозиторий проекта.

Важно: Google с 21.11.2024 прекратил показ sitelinks search box и считает
`SearchAction` неподдерживаемой разметкой. Она не вызывает ошибок и может
использоваться другими поисковиками (Yandex/Bing), поэтому оставлена
осознанно; на rich result в Google рассчитывать нельзя.

### Страница тайтла

`@graph`:

- `ComicStory` — `name`, `url`, `description`, `image`, `inLanguage`,
  `alternateName`, `genre`, `copyrightYear`, `isFamilyFriendly`,
  `dateModified`, `sameAs` (если у тайтла есть публичный URL источника),
  `aggregateRating` (только если rating и rating_count реальные, шкала 1–10);
- `BreadcrumbList` — Главная → Каталог → Тайтл.

Автор, издатель, ISBN и точная дата публикации не выводятся: в каталоге
нет достоверных данных, а выдумывать поля нельзя. Google не имеет
отдельного rich result для `ComicStory`; разметка помогает понять сущность
и улучшает breadcrumb-навигацию.

### Юридические страницы

Каждый из маршрутов `/terms`, `/privacy`, `/dmca`, `/contacts`, `/age`
добавляет один JSON-LD `WebPage`:

- `name`, `description`, `url` (self-canonical), `inLanguage: ru`,
  `dateModified` (дата редакции);
- `isPartOf` → `WebSite` MangaPoisk Reborn;
- `publisher` → `Organization` только если `LEGAL_OWNER_NAME` заполнен;
  вымышленные реквизиты не выводятся.

### Остальные маршруты

JSON-LD намеренно не добавляется: каталог/поиск/читалка не дают
достоверной сущности, а лишняя разметка создаёт шум. `ItemList` для
каталога можно добавить позже, когда появится стабильная семантика
постраничной выдачи.

## 5. robots.txt и sitemap

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

Sitemap: https://85.192.37.58.nip.io:8443/sitemap.xml
```

`/reader/` не закрыт в robots: страницы глав отдают `noindex,follow` и
передают ссылочный вес на страницу тайтла. Закрывать их в robots.txt
контрпродуктивно — краулер не увидит noindex.

Динамический sitemap: `services/gateway/app/seo.py`.

- маршрут `GET /sitemap.xml` (и alias `GET /api/v1/sitemap.xml`);
- статические страницы: `/`, `/catalogue`, `/sources`;
- юридические страницы: `/terms`, `/privacy`, `/dmca`, `/contacts`, `/age`
  с датой редакции в `lastmod`. `/age` включён осознанно: это содержательная
  публичная политика с видимым предупреждением 18+, а не doorway-страница;
- все тайтлы каталога с `chapters_count > 0`, `lastmod` из
  `last_chapter_at`/`updated_at`;
- лимит 50 000 URL (протокол sitemaps: 50 000 URL / 50 MB), при
  превышении нужно делить на sitemap index;
- кэш в памяти 30 минут, `Cache-Control: public, max-age=900,
  stale-while-revalidate=3600`;
- при падении каталога отдаётся последняя успешная копия;
- сбор идёт одним запросом `GET /internal/sitemap` (одна SQL-выборка по
  каноническим группам), а не ~65 страницами `manga_list`; paginated fallback
  оставлен для совместимости со старым catalog;
- gateway прогревает кэш в фоне при старте, поэтому холодный запрос после
  рестарта не должен упираться в 30-секундный nginx timeout.

## 6. Деплой

Ветка `feat/seo` не меняет production nginx. После merge и сборки web-образа
нужно добавить в `infra/nginx/default.conf` (перед `location /`):

```nginx
location = /sitemap.xml {
    proxy_pass http://gateway:8000/sitemap.xml;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_connect_timeout 5s;
    proxy_read_timeout 120s;
}
```

Gateway сам отдаёт `Cache-Control: public, max-age=900,
stale-while-revalidate=3600`; отдельный `add_header` в nginx не нужен и
создал бы дубликат заголовка.

Почему нужен сниппет: nginx `location /` отдаёт `index.html` для любого
неизвестного пути, поэтому без точного location `/sitemap.xml` продолжит
возвращать SPA. `location /api/` уже проксируется на gateway, поэтому до
правки nginx sitemap можно проверить по адресу
`https://85.192.37.58.nip.io:8443/api/v1/sitemap.xml` (robots пока указывает
на будущий корневой URL).

`robots.txt` — статический файл из `apps/web/public`, nginx отдаёт его из
`dist` автоматически; отдельный location не нужен. Версия service worker
поднята до `v5-2026-11-12`, иначе клиенты со старым app shell продолжили бы
получать прежний `index.html` и `robots.txt` из precache.

После деплоя:

1. `curl -k https://85.192.37.58.nip.io:8443/robots.txt`
2. `curl -k https://85.192.37.58.nip.io:8443/sitemap.xml | head`
3. Добавить sitemap в Google Search Console и Yandex Webmaster.
4. Запросить переобход главной, каталога и 3–5 карточек тайтлов.
5. Проверить отчёты «Индексирование страниц» / «Страницы» через 1–2 недели.

## 7. Проверка

- `npm run typecheck` — успешно.
- `npm run build` — успешно; SEO-слой не добавил зависимостей.
- `pytest tests/gateway/test_seo.py` — 4 теста.
- `pytest tests/gateway` — 17 тестов.
- `ruff check` по изменённым Python-файлам — успешно.
- Рендер маршрутов через browser skill: см. раздел 8.

## 8. Evidence

Проверка выполнялась на production-сборке (`npm run build`, `vite preview` +
локальный same-origin proxy на `/api`, чтобы повторить схему nginx) и в
dev-сервере с production API. Роуты: `/`, `/catalogue`,
`/catalogue?q=chainsaw&sort=updated&page=2`, `/manga/:id`, `/reader/:id`,
`/sources`, `/login`, `/library` (redirect), `/admin`, `/404`.

Результат: 44/44 проверки прошли, 0 ошибок в console, 0 `<img>` без `alt`.

- **Home** — title/description/robots index; canonical `…/`; OG/Twitter;
  JSON-LD `WebSite` + `Organization` (валидный JSON, `@graph`); один `<h1>`.
- **Catalogue** — title «Каталог манги и манхвы на русском», 862 тайтла в
  description на момент проверки, canonical `/catalogue`, robots index.
- **Catalogue search** — `?q=chainsaw&sort=updated&page=2`: canonical
  `…/catalogue?q=chainsaw&page=2` (sort отброшен, page сохранён),
  robots `noindex,follow`.
- **Manga** — title «Человек-бензопила — читать онлайн на русском»,
  description 159 символов, canonical на карточку, OG image = primary cover,
  JSON-LD `ComicStory` (10 жанров, rating 9.42/94167, sameAs, dateModified)
  + `BreadcrumbList` «Главная → Каталог → Человек-бензопила».
- **Reader** — title «Том 1 · Глава 58 — …», robots `noindex,follow`,
  canonical на `/manga/0e2d16c5-…`, скрытый `<h1>`; после загрузки данных
  canonical обновляется с self на страницу тайтла.
- **Sources** — title/description/canonical, robots index.
- **Login / Library** — `noindex,nofollow`, canonical отсутствует; `/library`
  редиректит на `/login?next=%2Flibrary`, метаданные применяются уже к login.
- **Admin** — `noindex,nofollow`, canonical отсутствует; дубликат robots,
  который добавляет сам `AdminPage`, схлопывается `AdminSeo`.
- **404** — `noindex,follow`, canonical отсутствует, один `<h1>`.
- **Дубли тегов** — на catalogue/manga/sources ровно один `description`,
  один canonical, один `og:image`, один `robots`, один JSON-LD script.

Lighthouse (local production build, desktop, без эмуляции):
SEO 1.0 на home и manga; Best Practices 1.0; Accessibility 1.0 на home и
0.95 на manga. Единственный a11y-фейл на manga — `aria-allowed-attr` в
существующей разметке обложек (`role="listitem"` + `aria-pressed`), к SEO не
относится и в этой задаче не переделывался.

Sitemap на реальном каталоге (production API, 2026-11-12):

```
catalogue_total: 966
pages_fetched:   10 (limit=100)
sitemap_urls:    968 (3 static + 965 titles with chapters)
unique_urls:     968
bytes:           137354 (< 50 MB)
all_https:       true
lastmod_sample:  2026-11-12
XML parse:       ElementTree OK
```

После #64 холодная генерация идёт одним запросом `/internal/sitemap` вместо
~65 страниц `manga_list`. Локальный замер на 6 510 тайтлах:

```
sitemap_rows: 6510
query_ms:     57.27
xml_ms:       10.37
cold_total:   67.64 ms
xml_bytes:    625070
```

Кэш прогревается в фоне при старте gateway; nginx получает
`proxy_read_timeout 120s` для `location = /sitemap.xml`, чтобы даже холодный
запрос не упирался в дефолтные 30 с.

Живой `/api/v1/sitemap.xml` на production пока отдаёт 404: код ветки не
задеплоен. Это ожидаемо и будет проверено lead после деплоя. Локально
маршрут покрыт `TestClient`-тестами (200, `application/xml`, кэш, stale
fallback, alias `/api/v1/sitemap.xml`).

`robots.txt` в собранном `dist` отдаётся как `text/plain; charset=utf-8` и
содержит `Sitemap: https://85.192.37.58.nip.io:8443/sitemap.xml`.


## 9. Ограничения и что осталось за пределами ветки

- **Soft 404:** SPA отвечает HTTP 200 на неизвестный маршрут. `noindex` на
  404-компоненте снижает риск индексации, но не заменяет серверный 404.
  Исправление требует SSR/пререндера или nginx-карты маршрутов; в этой
  ветке не делалось, чтобы не ломать deep links.
- **Canonical/OG в исходном HTML:** корректны для текущего пути, но
  title/description до выполнения JS остаются базовыми. Полноценное
  решение — SSR/SSG или prerender для карточек; это отдельная задача.
- **Yandex:** рендерит JavaScript, но для SPA надёжнее SSR/prerender;
  после деплоя нужно отдельно проверить, как Яндекс видит карточки, через
  «Индексирование страниц» в Webmaster. Эта ветка не может подтвердить
  индексацию без доступа к панели.
- **Sitemap cache:** в каждом процессе gateway своя копия; при нескольких
  репликах кэш прогревается независимо. Для текущего single-node деплоя
  это нормально.
- **Google Search Console / Yandex Webmaster** не подключены из этой ветки:
  нужны доступы и подтверждение владения доменом.
- **Core Web Vitals:** бюджет Google — LCP < 2.5 s, INP < 200 ms, CLS < 0.1
  на 75-м перцентиле. В этой задаче добавлены только preconnect к хостам
  обложек; измерение CWV на production не проводилось. Для LCP обложек
  стоит отдельно проверить размеры изображений и `fetchpriority`.

## 10. Источники (проверено 2026-11-12)

- Google Search Central — JavaScript SEO basics:
  https://developers.google.com/search/docs/crawling-indexing/javascript/javascript-seo-basics
- Google Search Central — canonical URL:
  https://developers.google.com/search/docs/crawling-indexing/consolidate-duplicate-urls
- Google Search Central — sitemaps (50 000 URL / 50 MB):
  https://developers.google.com/search/docs/crawling-indexing/sitemaps/build-sitemap
- Google Search Central — Core Web Vitals:
  https://developers.google.com/search/docs/appearance/core-web-vitals
- Google Search Central — sitelinks search box deprecation:
  https://developers.google.com/search/blog/2024/10/sitelinks-search-box
- Yandex Webmaster — индексация страниц с JavaScript:
  https://yandex.com/support/webmaster/en/yandex-indexing/rendering
- Yandex Webmaster — руководство по индексации:
  https://webmaster.yandex.com/site/optimization/seo-guide/?section=INDEXING
- schema.org — ComicStory: https://schema.org/ComicStory
