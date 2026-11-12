# Contributing

Спасибо, что заглянули. Проект небольшой, поэтому правила простые.

## Перед началом

1. Посмотрите [issues](https://github.com/geekAmis/mangapoiskAPI/issues) и
   [docs/ROADMAP.md](docs/ROADMAP.md); для небольших задач есть метка
   [good first issue](https://github.com/geekAmis/mangapoiskAPI/labels/good%20first%20issue).
2. Для бага приложите шаги воспроизведения, окружение (web/android/api) и
   логи без токенов и cookies.
3. Для новой функции сначала опишите сценарий и acceptance criteria в issue.

## Ветки и коммиты

- Ветка от `main`: `feat/...`, `fix/...`, `docs/...`, `infra/...`.
- Один PR — одна логическая задача; не смешивайте рефакторинг и фичу.
- Коммиты и PR можно писать по-русски или по-английски, но одинаково в рамках
  одной ветки.

## Локальные проверки

```bash
ruff check .
pytest

cd apps/web
npm run typecheck
npm run build
```

Для Android: `cd apps/android && ./gradlew assembleDebug` (JDK 17, Android SDK
34). Сетевые тесты парсера не входят в обычный прогон и включаются только
через `RUN_NETWORK_TESTS=1`.

## Что важно

- Python: async, типы, без `print`; ошибки — через общие исключения.
- Frontend: TypeScript, русский UI, доступность, шесть тем без регрессий.
- Android: Kotlin/Compose или Capacitor, без блокирующих вызовов в main thread.
- Парсеры: только публичные данные, без обхода защит; новый источник — через
  `BaseAdapter`, с тестами и записью в [docs/SOURCES.md](docs/SOURCES.md).
- Публичный API меняется вместе с [docs/API.md](docs/API.md); архитектурные
  изменения — вместе с [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Секреты

Не коммитьте `.env`, cookies, токены, SSH-пароли и `data.txt`. Если секрет уже
попал в git — не переписывайте историю в одиночку: напишите мейнтейнеру.

## PR

Заполните шаблон: что изменилось, как проверить, какие проверки прошли.
Для UI приложите скриншот до/после. Секреты и сгенерированные артефакты в PR
не добавляйте.

Лицензия — MIT; отправляя PR, вы соглашаетесь распространять код на этих
условиях.
