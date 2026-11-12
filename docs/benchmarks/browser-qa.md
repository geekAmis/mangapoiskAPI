# Browser QA — search suggestions

Дата: 2026-11-12.  Локальный стек: catalog:8002, gateway:8000, web:5173.
Viewport-ы проверены через iframe-вьюпорты (in-app browser не предоставляет
device emulation): Web **1440×900**, Mobile **390×844**.

## Web 1440×900

* `window.innerWidth/Height`: 1440×900.
* `document.documentElement.scrollWidth`: 1425 (скроллбар), горизонтального
  overflow нет.
* Поиск в шапке: combobox `aria-expanded=true`, dropdown
  `left=808.3 / right=1226.7 / bottom=195.6` — внутри viewport.
* `role=listbox`, `role=option`, `aria-selected=true` после `ArrowDown`.
* `Escape` закрывает dropdown, фокус остаётся на input.

## Mobile 390×844

* `window.innerWidth/Height`: 390×844.
* `document.documentElement.scrollWidth`: 375 — overflow нет.
* Desktop-поиск скрыт, mobile-toggle видим; после открытия поиска dropdown:
  `left=16.8 / right=306.4 / bottom=270.3` — внутри viewport.
* `role=listbox/option`, `aria-activedescendant`, `aria-selected=true` после
  `ArrowDown`; `Escape` закрывает, фокус остаётся на input.
* Кнопки «Очистить историю» и «Приватный режим» помещаются в footer.

## Поведение

* «чензо мен» → top-1 «Человек-бензопила» (Chainsaw Man), выбор стрелкой +
  Enter ведёт на `/manga/<id>`.
* После 380 мс CataloguePage синхронизирует `?q=`; dropdown не закрывается
  (эффект закрытия реагирует только на смену pathname).
* История: запись появляется после submit/выбора; «Очистить историю» удаляет
  `localStorage`; приватный режим (`aria-pressed=true`) не читает и не пишет
  историю; после submit в приватном режиме история остаётся `null`.
* Сеть: за время набора **0** запросов к `/api/v1/manga/search`; только
  `/api/v1/manga/suggest` (debounce 180 мс). Parser не вызывается.
* Console errors: 0 после чистого reload (Web и Mobile).
* Lighthouse: accessibility 1.0, best-practices 1.0, SEO 1.0. Скрытое
  aux-правило `label-content-name-mismatch` указало на существующие
  `MangaCard` cover-ссылки из-за QA-фикстур без постеров (fallback-текст
  «Нет обложки»); к SearchBox отношения не имеет.

## Ограничение

`browser.screenshot` в этой сессии вернул `Screenshot needs a visible tab`
(desktop-окно не видимо агенту), поэтому визуальные скриншоты не приложены.
Вместо них зафиксированы DOM-метрики, accessibility-снапшоты, console и
network логи.
