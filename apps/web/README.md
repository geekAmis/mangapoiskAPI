# MangaPoisk Reborn — веб-клиент

SPA на React 19 + TypeScript + Vite для русского каталога манги и манхвы.
Работает с публичным API `/api/v1` (см. `docs/API.md` в корне репозитория).

## Стек

- React 19, TypeScript, Vite 7
- react-router-dom 7
- @tanstack/react-query 5 — серверное состояние, кэш, повторные запросы
- zustand 5 — авторизация, тема, настройки читалки, уведомления
- современный CSS с переменными, без Tailwind и внешних шрифтов
- инлайновые SVG-иконки

## Требования

- Node.js **20.19+** (или 22.12+)
- npm 10+
- запущенный gateway на `http://localhost:8000` для dev-режима

## Запуск

```bash
cd apps/web
npm install
npm run dev
```

Vite откроет `http://localhost:5173`. Запросы `/api/*` проксируются на
`http://localhost:8000` (см. `vite.config.ts`), поэтому CORS в разработке не нужен.

### Переменные окружения

Скопируйте `.env.example` в `.env` при необходимости:

```env
VITE_API_BASE=/api/v1
```

- `VITE_API_BASE=/api/v1` (по умолчанию) — same-origin запросы через nginx или dev-прокси.
- `VITE_API_BASE=https://api.example.com/api/v1` — отдельный домен API.
  В этом случае gateway должен разрешить origin веб-клиента в `CORS_ORIGINS`.

Переменная встраивается на этапе сборки, поэтому после изменения нужен перезапуск
`npm run dev` или новая сборка.

### Сборка и проверка

```bash
npm run typecheck   # tsc --noEmit
npm run build       # tsc --noEmit && vite build -> dist/
npm run preview     # локальный просмотр production-сборки (порт 4173)
```

`dist/` и `node_modules/` игнорируются git.

## Структура

```
src/
  api/
    types.ts          типы контракта /api/v1 (snake_case)
    client.ts         fetch-обёртка, refresh access-токена, методы эндпоинтов
    admin.ts          отдельный клиент Control: admin-токен, серверы, jobs, registry
  components/         MangaCard, ChapterRow, Rating, Skeleton, EmptyState,
                      Modal/Sheet, Toast, ThemeSwitcher, SearchBox, Pagination,
                      ProtectedRoute, ErrorBoundary, ExportDialog, admin/*, layout/*
  pages/
    HomePage          hero, популярное, обновления, источники, продолжение чтения
    CataloguePage     поиск, фильтры, пагинация, живой поиск, импорт по ссылке
    MangaPage         описание, рейтинг, закладка, главы, экспорт
    ReaderPage        читалка (lazy-loaded)
    LibraryPage       закладки, продолжение, история
    LoginPage / RegisterPage
    ProfilePage       тема, настройки читалки, аккаунт
    SourcesPage
    NotFoundPage
    AdminPage         закрытая панель Control (/admin, lazy-loaded)
  stores/             auth, theme, reader, toast
  lib/                форматирование, ошибки, хуки, query client, синхронизация
  styles/             themes.css, base.css, components.css, layout.css,
                      pages.css, reader.css, admin.css
public/
  themes/             шесть webp-фонов и blur-версии
  icons/              favicon.svg, PNG-иконки PWA
  manifest.webmanifest
  robots.txt
```

### Маршруты

- `/` — главная.
- `/catalog` и `/catalogue` — каталог (алиасы, query-строка сохраняется).
- `/manga/:id` — страница тайтла.
- `/read/:chapterId` и `/reader/:chapterId` — читалка (алиасы).
- `/library`, `/profile` — только после входа.
- `/login`, `/register`, `/sources`, `/404`.
- `/admin` — закрытая панель Control. Ссылки в публичном интерфейсе нет,
  страница помечена `noindex`, индексирование закрыто в `robots.txt`.

## Темы

Шесть тем: `midnight`, `noir`, `oni`, `crimson`, `sunset`, `paper`.

- Активная тема задаётся атрибутом `<html data-theme="...">` и переменными CSS.
- Выбор хранится в `localStorage` (`mp-theme`), а для авторизованного
  пользователя синхронизируется через `GET/PUT /library/settings`.
- При первом визите используется системная схема: светлая → `paper`,
  тёмная → `midnight`.
- Фоновые изображения применяются только на главной, страницах входа/регистрации
  и 404. В остальных местах тему несут палитра и акценты.
- Все интерактивные элементы имеют видимый focus-ring; поддержан
  `prefers-reduced-motion`.

## Интеграция с API

- База: `VITE_API_BASE` или `/api/v1`.
- Авторизация: `Authorization: Bearer <access_token>`; токены хранятся в
  `localStorage` (`mp:auth`). При `401` клиент один раз обновляет пару через
  `POST /auth/refresh` (single-flight, чтобы параллельные запросы не создавали
  несколько refresh) и повторяет исходный запрос.
- Ошибки читаются из `{"error":{"code","message","details"}}`; пользователю
  показываются русские сообщения по HTTP-статусу/коду.
- `GET /library/{bookmarks,progress,history}` принимаются как массив **или**
  как `Paginated<T>` — на случай различий между gateway и library.
- Прогресс чтения отправляется через `PUT /library/progress` с debounce 850 мс,
  номер страницы 1-based. При скрытии вкладки/уходе из читалки очередь
  сбрасывается принудительно.
- Настройки читалки и тема отправляются в `PUT /library/settings` с debounce
  после изменения; серверные настройки применяются один раз при входе.
- URL изображений глав используются ровно в том виде, в котором их вернул API;
  подменять на upstream-адреса нельзя.
- Экспорт: `POST /chapters/{id}/exports?format=cbz|pdf|html`, затем polling
  `GET /exports/{job_id}` и ссылка `download_url` (относительный путь
  разрешается от базы API).

### Допущения по контракту

1. Главная не имеет отдельного эндпоинта: популярное и обновления собираются из
   `GET /manga?sort=popular` и `GET /manga?sort=updated`.
2. `GET /library/progress` и `GET /library/history` могут вернуть вложенные
   `manga`/`chapter`; если `manga` равен `null`, карточка пропускается.
3. Фильтр жанров использует русские названия жанров из источника; отдельного
   эндпоинта фасетов в API нет.
4. Живой поиск (`GET /manga/search?live=true`) по документации сам импортирует
   найденные тайтлы в каталог, поэтому результаты открываются как обычные
   карточки. Отдельная кнопка импорта по URL использует
   `POST /manga/import`.
5. Экспорт в API не помечен как требующий авторизации; клиент вызывает его без
   Bearer-токена. Если gateway закроет экспорт, клиент покажет ошибку.
6. `download_url` может быть абсолютным `/api/v1/exports/...` или относительным —
   оба варианта поддерживаются.
7. Источники с `enabled=false` показываются в разделе «Источники», но не
   предлагаются как фильтр каталога.

## Админ-панель Control (`/admin`)

Отдельный полноэкранный тёмный интерфейс, не связанный с темой публичного
сайта и не имеющий ссылки в навигации. Логин проверяется gateway
(`POST /api/v1/admin/login`), токен хранится **только в sessionStorage** под
ключом `mp-admin-token`, не пересекается с `mp:auth` читателя и очищается при
любом `401` или выходе. Учётные данные администратора задаются на backend
(`ADMIN_USERNAME` / `ADMIN_PASSWORD`); в бандл они не попадают.

Возможности:

- инвентарь серверов: health-точки сервисов, порты, bind host, jump-сервер,
  fallback/jump-статусы, включение/выключение, ручной health-check;
- создание и редактирование сервера: SSH-поля, jump-сервер, сервисы с
  редактируемыми портами (parser 8101, catalog 8102, library 8103, media 8104,
  control 8005, gateway 8100, notifier 8106, scheduler 8107);
- удаление с подтверждением;
- развёртывание выбранных сервисов с предварительным подтверждением, polling
  задачи каждые 2 секунды и терминальным логом с автоскроллом;
- реестр gateway по сервисам: активный/резервный/нездоровый endpoint;
- синхронизация маршрутов, failover с подтверждением, аудит последних 100
  действий (чувствительные поля вроде паролей скрываются).

Все ошибки показываются человеческим русским текстом; сырые токены и пароли
не выводятся. На мобильном (390 px) карточки и формы складываются в одну
колонку, модальные окна становятся bottom sheet.

## Деплой

Соберите `dist/` и отдайте статикой через nginx:

```nginx
location / {
    root /usr/share/nginx/html;
    try_files $uri $uri/ /index.html;
}

location /api/ {
    proxy_pass http://gateway:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

`try_files ... /index.html` обязателен для клиентских маршрутов
(`/catalog`, `/catalogue`, `/manga/:id`, `/read/:chapterId`, `/reader/:chapterId`,
`/profile`, `/admin`).

## PWA

Добавлены `manifest.webmanifest`, иконки 192/512 и `robots.txt`. Полноценный
service worker намеренно не добавлен: офлайн-чтение реализуется через экспорт
глав в CBZ/PDF/HTML, а не через кэш изображений в браузере.

## Доступность и адаптивность

- Семантические landmarks, `aria-current` у навигации, подписи у icon-кнопок.
- Модальные окна удерживают фокус, закрываются по Escape, возвращают фокус.
- Нет горизонтального скролла на 320–1920 px; мобильная нижняя навигация
  учитывает `env(safe-area-inset-bottom)`.
- Читалка: полноэкранный режим, клавиши `←/→`, `F`, `S`, `Пробел`, свайпы,
  tap-зоны, автопрокрутка с паузой, настройки в bottom sheet.
