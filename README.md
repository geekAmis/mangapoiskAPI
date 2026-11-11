# MangaPoisk Reborn

Старый `mangapoiskAPI` был одним файлом, с захардкоженным токеном и парсингом
прямо в роутерах. Я переписал его нормально: FastAPI-микросервисы, React-сайт,
Android-клиент и общий API.

![MangaPoisk Reborn](apps/web/public/themes/midnight.webp)

## Что есть

- каталог и поиск манги на русском;
- карточка тайтла, список глав, читалка (вертикальная, webtoon, постраничная);
- авто-скролл, горячие клавиши, сохранение прогресса;
- аккаунт, закладки, история, настройки читалки;
- экспорт главы в CBZ, PDF или HTML-ZIP;
- шесть тем оформления;
- Android-приложение на Jetpack Compose;
- парсеры MangaPoisk, MangaLib, Remanga, ReadManga и MangaDex
  (у каждого честно указано, что он умеет).

## Запуск

```bash
git clone https://github.com/geekAmis/mangapoiskAPI.git
cd mangapoiskAPI
cp .env.example .env
```

Сгенерируйте два секрета и вставьте их в `.env`:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Потом:

```bash
docker compose up -d --build
```

- сайт — http://localhost:8080
- API и Swagger — http://localhost:8000/docs
  (`docker compose --profile dev up -d gateway-public`)
- проверка — http://localhost:8080/api/v1/health

Первая манга:

```bash
curl -X POST http://localhost:8080/api/v1/manga/import \
  -H "Content-Type: application/json" \
  -d '{"source":"mangapoisk","url":"https://mangapoisk.me/manga/zombie-slasher"}'
```

## Без Docker

Нужны Python 3.12+, Node 20+ и желание запустить 5 терминалов.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e packages/manga_common
pip install -r services/parser/requirements.txt
# и так далее для catalog, library, media, gateway
```

Подробности — в [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

## Как устроено

```
React / Android
      │
      ▼
   gateway ──► catalog ──► parser ──► сайты манги
      │           │
      ├──► library (аккаунты, закладки, прогресс)
      └──► media   (кэш картинок, CBZ/PDF/HTML)
```

- `gateway` — публичный `/api/v1`;
- `parser` — адаптеры источников;
- `catalog` — PostgreSQL-каталог;
- `library` — пользователи и библиотека;
- `media` — картинки и экспорт;
- `scheduler` и `notifier` — обновления и Telegram.

Подробнее: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
Контракт API: [docs/API.md](docs/API.md).

## Пара примеров API

```http
GET /api/v1/manga/search?q=магия&live=true
GET /api/v1/manga/{id}
GET /api/v1/chapters/{id}
GET /api/v1/chapters/{id}/images/1
POST /api/v1/chapters/{id}/exports?format=cbz
```

## Админка и серверы

Панель управления — `/admin` (прямая ссылка, в меню её нет). Логин и пароль
берутся из `ADMIN_USERNAME` / `ADMIN_PASSWORD` в `.env`. Оттуда можно добавить
сервер по IP/логину/паролю, выбрать микросервисы и порты, поставить их через
SSH (напрямую или через 83 как jump-host), посмотреть логи деплоя и переключить
трафик на здоровый сервер. Пароли серверов шифруются, наружу не отдаются.

## Android

```bash
cd apps/android
./gradlew assembleDebug
```

Для эмулятора базовый URL — `http://10.0.2.2:8000/api/v1/`. Для телефона —
адрес вашего сервера. Инструкция: [docs/ANDROID.md](docs/ANDROID.md).

## Тесты

```bash
pytest
ruff check .
cd apps/web && npm run typecheck && npm run build
```

## Источники и право

Проект не хранит мангу у себя: он показывает каталог и проксирует картинки с
источников. Парсим только публичные страницы, с лимитами и кэшем, без обхода
защит и paywall. Если вы правообладатель — откройте issue, разберёмся.

Подробнее: [docs/SOURCES.md](docs/SOURCES.md) и [docs/LEGAL.md](docs/LEGAL.md).

## Статус

Работа идёт по шагам в [issues](https://github.com/geekAmis/mangapoiskAPI/issues).
Главный эпик — [#3](https://github.com/geekAmis/mangapoiskAPI/issues/3).
Код под MIT.
