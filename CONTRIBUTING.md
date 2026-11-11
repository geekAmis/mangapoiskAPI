# Contributing

Спасибо, что заглянули. Проект небольшой, поэтому правила простые.

1. Создайте issue или возьмите существующую.
2. Ветка от `main`: `feat/...`, `fix/...`, `docs/...`.
3. Для изменений в коде добавьте тест.
4. Перед PR запустите:

```bash
ruff check .
pytest
cd apps/web && npm run typecheck && npm run build
```

5. В PR опишите, что изменилось и как это проверить. Секреты, cookies,
   `.env` и `data.txt` не коммитьте.

Python: async, типы, без `print`. Frontend: TypeScript, русский UI, доступность.
Android: Kotlin/Compose или Capacitor, без блокирующих вызовов в main thread.
Парсеры: только публичные данные, без обхода защит; новые источники — через
`BaseAdapter` и с тестами.

Лицензия — MIT.
