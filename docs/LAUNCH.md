# Launch status — v1.3.2 (2026-11-13)

Текущий production: `https://85.192.37.58.nip.io` на 80/443, `main` @
`affe7d0` (`v1.3.2`). Сайт, API, SEO, профили, подборки, Яндекс ID и
юридические страницы работают. Ниже — честный GO/NO-GO по направлениям, а не
общий «релиз готов».

## 1. Сводка

| Направление | Статус | Решение |
|---|---|---|
| Публичный сайт, каталог, читалка | 200, ~25k видимых тайтлов, p95 ~45 ms gateway / ~34 ms catalog в deploy check | **GO** |
| SEO (slug/prerender/sitemap) | sitemap ~25,189 URL, canonical/OG без порта, боты получают HTML | **GO**, но Search Console/Webmaster не подтверждены |
| HTTPS/порты | 80/443, SAN apex+www, срок 2027-02-11, renewal webroot | **GO**; legacy 8443/8088 остаются |
| Яндекс ID | реальный вход подтверждён, DB-only ключи | **GO** |
| Юридические страницы | `/terms`, `/privacy`, `/dmca`, `/contacts`, `/age`; реальные контакты | **GO** |
| Реклама РСЯ | код/ads.txt/CSP готовы; `PAGE_DISABLED` + модерация <100/нед | **NO-GO по показу** |
| Android 1.3.2 | установлен, cold launch/session restore PASS; QA paused | **NO-GO по публикации APK** |
| Трафик/Метрика | #85 в работе, в v1.3.2 нет | **NO-GO по монетизации** |
| HentaiLib / AI supervisor / search fix | ветки готовы, не в production | **вне релиза** |

## 2. Блокеры и owner actions

### 2.1 Яндекс РСЯ (#83, #85)

- Реальный SDK отвечает `PAGE_DISABLED Page "20411736" is disabled`, пока
  владелец не включит площадку/блок `R-A-20411736-1` в кабинете РСЯ.
- Модерация площадки отклонена: менее 100 реальных посетителей в неделю.
  Повторная подача — **с 2026-11-20 05:55**.
- До этого не считать рекламу источником дохода и не заявлять, что RTB
  «показывается». Проверять `ads.txt` (9 строк, прямой 200 на 80/443/8088),
  CSP и `config.block_id`.
- Накрутка ботов/посетителей запрещена. Метрика (#85) должна давать реальные
  визиты, а не имитацию.

### 2.2 Android 1.3.2 (#84)

- APK 1.3.2 / versionCode 5 установлен поверх 1.3.1; packaged `www`, origin
  `https://localhost`, API 443, сессия и локальные данные 1.3.0 восстановлены.
- Владелец приостановил QA после cold launch. Не проверены reader, downloads,
  notifications, `/privacy` overflow, Yandex ID и новые v1.3-фичи.
- GitHub release/APK-ассет для 1.3.2 не публиковать до завершения QA.
- APK SHA-256:
  `13c5c57e51c28128949923c3ec56d2b039a212165f965b4bd8da95cd2da55019`.

### 2.3 Порты и сертификат (#82)

- 80/443 — основной сайт; `http`/`www` → 301 apex HTTPS.
- `:8443` — только API для APK 1.3.0; веб-страницы 301. `:8088` — 301, кроме
  `/ads.txt`. Не добавлять новые ссылки с этими портами.
- Сертификат: SAN apex+www, до 2027-02-11, renewal webroot
  `/var/www/certbot`, reload `mangapoisk-web.service`.
- Перед удалением legacy-портов убедиться, что APK 1.3.0 больше не нужен.

### 2.4 Безопасность (#78, #79)

- SSH всё ещё принимает root-пароль; key-only миграция не завершена.
- CSP остаётся широким (`unsafe-inline`, `connect-src http: https:`); для RTB
  добавлены `yandex.ru`, `an.yandex.ru`, `yastatic.net`.
- У `/admin` нет IP allowlist/VPN и MFA; 60-минутный токен действует до
  истечения. Считать это остаточным риском до #79.

### 2.5 SEO-панели

- Доступа к Google Search Console и Яндекс.Вебмастеру нет. Verification-теги
  и инструкция готовы, но подтверждение, отправка sitemap и request indexing
  остаются ручными действиями владельца.
- Sitemap ~25,189 URL; 18+ и приватные профили не включены.

## 3. Не входит в v1.3.2

Не описывать как live и не проверять в приёмке:

- HentaiLib (#45) — ветка `feat/hentailib-age-gate`, источник выключен.
- AI-супервизор деплоя (#75) — ветка `feat/ai-deploy-supervisor`, нужен
  OpenCode auth.
- Поиск по авторам/исправление `чензо мен` (#76) — ветка
  `fix/search-author-typo`, не смержена.
- Яндекс Метрика и traffic-панель (#85) — в работе.
- Репликация данных в production — в разработке, не включена.

## 4. Приёмочный чек-лист

- [ ] `https://85.192.37.58.nip.io/` → 200; `/api/v1/health` → 200.
- [ ] `http://` и `www` → 301 apex HTTPS.
- [ ] `:8443/api/v1/health` → 200 (legacy APK), `:8443/` → 301; `:8088/` → 301.
- [ ] `/ads.txt` → 200 `text/plain`, 9 строк, без redirect, на 80/443/8088.
- [ ] canonical/OG/sitemap без `:8443` и `http://`; sitemap ~25k URL.
- [ ] Yandex ID: `/auth/providers` = `{"yandex":true}`, реальный вход, callback
      без порта.
- [ ] `/terms`, `/privacy`, `/dmca`, `/contacts`, `/age`: реальные контакты,
      `/privacy` на 390 px без горизонтального overflow.
- [ ] Admin: вкладки, Яндекс ID, console allowlist, deploy jobs, audit.
- [ ] Android: не публиковать APK до завершения #84.
- [ ] RTB: зафиксировать `PAGE_DISABLED` как внешний блокер; повторная подача
      не раньше 2026-11-20 05:55.
- [ ] Backups: свежий restic snapshot, backup age в админке, restore drill.
- [ ] Docs: `python scripts/check_docs_encoding.py` и относительные ссылки.

## 5. Rollback

- Web: вернуть предыдущий `dist`, перезапустить static-сервер на 8089 и
  reload `mangapoisk-web.service`.
- Gateway/control: вернуть предыдущий код, проверить `/health`,
  `/api/v1/health`, Yandex callback и sitemap.
- Nginx: восстановить предыдущий конфиг, `nginx -t`, reload. Не трогать
  system nginx и чужие сайты.
- Android: 1.3.1 нельзя откатить поверх 1.3.2 через `adb install -d`
  (versionCode 4 < 5); при откате потребуется uninstall с потерей данных или
  новый APK с code > 5.
- RTB: выключить провайдера в админке, не удаляя `ads.txt` и CSP-разрешения.

## 6. Ссылки

- [DEPLOYMENT.md](DEPLOYMENT.md) — порты, nginx, certbot, порядок деплоя.
- [OPS.md](OPS.md) — firewall, backups, restore, инциденты.
- [SEO.md](SEO.md) — slug/prerender/sitemap и ручные панели.
- [ADS.md](ADS.md) — RTB, consent, ads.txt.
- [ANDROID.md](ANDROID.md) — 1.3.2, packaged `www`, QA.
- [AUTH_YANDEX.md](AUTH_YANDEX.md) — OAuth и реальный вход.
- [SECURITY.md](SECURITY.md) — остаточные риски #78/#79.
- [INTEGRATION_v1.3.md](INTEGRATION_v1.3.md) — история интеграции.
