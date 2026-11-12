# AI-супервизор деплоя

Статус: **подготовлено, не включено в production**. Установка OpenCode и
включение супервизора выполняются только после approval lead (issue
[#75](https://github.com/geekAmis/mangapoiskAPI/issues/75)). Установка и
матрица разрешений — в [`docs/OPENCODE.md`](OPENCODE.md).

## 1. Что это

После **полного** деплоя control запускает на целевом узле OpenCode-агента
`deploy-supervisor` с бесплатной моделью
`opencode/deepseek-v4.1-flash-free`. Агент проверяет здоровье сервисов,
читает логи, при необходимости правит код в `/opt/mangapoisk-reborn/src` и
перезапускает только `mangapoisk-*`. Control ограничивает время, число
раундов, собирает отчёт в job log и админку; при неудаче делает source-only
rollback.

Супервизор — **не** замена control. Control по-прежнему:

- запускает деплой и health checks;
- решает, был ли деплой полным;
- соблюдает таймауты и отмену job;
- делает rollback и выставляет финальный статус;
- пишет audit log.

## 2. Когда запускается

```text
deploy script (install/units/restart/health)
        │
        ├── partial deploy ──────────────► supervisor skipped
        │
        └── full deploy
                │
                ├── health ok ───────────► supervisor checks logs/health
                │                              ├── healthy  → job done
                │                              └── failed   → rollback
                │
                └── health fail ─────────► supervisor repairs
                                               ├── recovered + health ok → job done
                                               └── failed/timeout        → rollback
```

«Полный деплой» (`AI_SUPERVISOR_FULL_DEPLOY_ONLY=true`, по умолчанию):

- набор deployed-сервисов покрывает весь inventory сервера из control
  (`deployed ⊇ inventory`), либо
- если inventory пуст (новый узел) — развёрнуты все известные коды
  (`parser, catalog, library, media, control, gateway, notifier, replica,
  comments, scheduler`).

Частичный деплой (например, только `gateway`) супервизор не запускает.

Если `AI_SUPERVISOR_SKIP_WHEN_HEALTHY=true`, при уже зелёном деплое агент не
запускается. По умолчанию `false`: супервизор всё равно проверяет логи на
traceback/5xx/locked/OOM.

## 3. Лимиты

| Лимит | По умолчанию | Где задаётся |
| --- | ---: | --- |
| Общее время супервизора | 900 с (15 мин) | `AI_SUPERVISOR_TIMEOUT_SECONDS` |
| Время одного раунда | 420 с | `AI_SUPERVISOR_ROUND_TIMEOUT_SECONDS` |
| Число раундов | 2 | `AI_SUPERVISOR_MAX_ITERATIONS` (1–5) |
| Шагов модели в раунде | 12 | `AI_SUPERVISOR_MAX_STEPS` и `steps:` в агенте |
| SSH timeout раунда | round + 120 с | control |
| Rollback | 180 с | control |

Каждый раунд — отдельный `opencode run` с жёстким `timeout`. Между раундами
control сам проверяет `systemctl is-active` и `/health`. Если сервисы
поднялись — следующие раунды не запускаются. Модель внутри раунда ограничена
`steps: 12`; на последнем шаге OpenCode убирает tools и просит итог.

### 3.1 Self-deploy control

Если в полный деплой входит `control`, deploy-скрипт **не** перезапускает
control через 5 секунд: иначе он убил бы job, в котором работает supervisor.
Вместо этого ставится fallback-таймер `AI_SUPERVISOR_TIMEOUT_SECONDS + 600`
(25 минут при дефолте). После того как control сохранил результат job, он
планирует настоящий restart через 5 секунд и отменяет fallback. Если процесс
control умрёт раньше, fallback всё равно поднимет его позже.

## 4. Prompt

Control собирает brief и передаёт его через `--file` (не в command line):

- job id, сервер, host, deploy root;
- список сервисов, портов и ожидаемых `/health`;
- результат деплоя (`success`/`failed`) и хвост deploy-лога (12 000 символов);
- предыдущий отчёт супервизора (для второго раунда);
- лимиты и модель;
- жёсткие границы: только `/opt/mangapoisk-reborn`, только `mangapoisk-*`,
  запрет других сервисов, nginx, Project-Kontur, alpine, docker, apt, БД,
  секретов, `rm -rf`, pipes/redirect/`;`/`&&`;
- требование считать логи недоверенными данными и не выполнять инструкции из
  них;
- обязательные маркеры отчёта:
  `AI_SUPERVISOR_RESULT`, `AI_SUPERVISOR_SUMMARY`,
  `AI_SUPERVISOR_ACTIONS`.

Агент также получает системный prompt `deploy-supervisor` и `SKILL.md` с
пошаговым runbook (наблюдение → диагностика → минимальный фикс → restart →
повторная проверка → отчёт).

## 5. Что разрешено агенту

- Читать `/opt/mangapoisk-reborn/**`, кроме `.env`, `env/**`, `data/**`.
- Редактировать только `/opt/mangapoisk-reborn/src/**`.
- Запускать read-only диагностику (`journalctl`, `systemctl status`,
  `curl` на `127.0.0.1`, `df`, `free`, `uptime`, `ss`).
- Перезапускать/запускать только `mangapoisk-*` units из brief.
- Ставить только project requirements через `venv/bin/pip -r
  src/services/*/requirements.txt`.
- Проверять синтаксис через `venv/bin/python -m py_compile`.

Запрещено:

- любые другие сервисы/юниты/порты/nginx/Caddy/Project-Kontur/alpine;
- `systemctl stop/disable/mask/edit/daemon-reload`;
- `rm -rf`, `docker system prune`, `apt upgrade`, `dpkg`, `ufw`, `iptables`,
  `useradd`, `chmod`, `chown`, `mount`, `reboot`;
- `sqlite3`/`psql`/`mysql`/`redis-cli` и любые записи в БД;
- чтение/печать `.env`, `env/*.env`, `data/**`, токенов, ключей;
- pipe, `;`, `&&`, `||`, redirect, backticks, `$()`.

OpenCode enforce-ит это через `/etc/opencode/opencode.json`. Control
дополнительно:

- проверяет коды сервисов перед запуском (`SupervisorGuardError`);
- передаёт только free-модель (`build_opencode_argv` отвергает платные);
- парсит JSON-события и ищет опасные команды (`audit_output`);
- при опасной команде ставит `failed` и запускает rollback.

## 6. Отчёт и админка

Отчёт хранится в `deployment_jobs.requested.supervisor` (без изменения схемы
БД) и показывается в модалке деплоя:

- статус (`healthy`, `recovered`, `failed`, `skipped`, `timeout`, `error`,
  `dry_run`);
- summary и список действий;
- раунды, лимиты, модель, время;
- запрещённые команды (если были);
- изменённые файлы (из JSON-событий edit/write/patch);
- все shell-команды агента (JSON tool calls, до 100);
- rollback (attempted/ok);
- хвост отчёта.

Полный JSON-поток OpenCode добавляется в job log между
`== AI supervisor ==` и `AI supervisor result: ...`. Remote-копии:

- `/opt/mangapoisk-reborn/logs/ai-supervisor-<job>.log`;
- `/opt/mangapoisk-reborn/run/ai-supervisor-<job>.md` (prompt, 0600).

Audit log control: `ai_supervisor.finished` с job id, статусом, числом
раундов, rollback и количеством нарушений/изменённых файлов.

## 7. Rollback

Rollback делает control, не агент. Это **source-only** откат. Он запускается
только если supervisor вернул `failed`/`timeout`/`error` и контрольный health
check всё ещё не зелёный (либо сработал guard). Если supervisor не успел, но
сервисы здоровы, rollback не выполняется.

1. Если `/opt/mangapoisk-reborn/src.old` нет — `AI_ROLLBACK_SKIPPED`.
2. Текущий `src` переименовывается в `src.ai-failed-<UTC timestamp>`
   (не удаляется, чтобы можно было разобрать).
3. `src.old` возвращается на место `src`.
4. Перезапускаются только deployed `mangapoisk-*`; `control` перезапускается
   отложенно через `systemd-run`, чтобы не убить текущий job.
5. Control повторно проверяет health и выставляет `failed`, даже если
   откаченные сервисы уже зелёные.

Ограничения:

- зависимости в `venv` не откатываются (pip-пакеты остаются новыми);
- БД не откатывается и не изменяется;
- `web`/nginx не откатываются;
- `src.ai-failed-*` нужно периодически разбирать вручную (не автоматически).

Если rollback не удался, job остаётся `failed`, в отчёте будет
`rollback.ok=false`; дальше — ручной runbook из `docs/OPS.md`.

## 8. Настройки control

Файл `/opt/mangapoisk-reborn/env/ai-supervisor.env` читается systemd
**последним** (после `.env` и `env/control.env`) и не перезаписывается
деплоем. Создавать только после approval. По умолчанию
`AI_SUPERVISOR_ENABLED=false`; включать только после установки OpenCode и
проверки auth на всех узлах.

```bash
install -d -m 750 /opt/mangapoisk-reborn/env
cat > /opt/mangapoisk-reborn/env/ai-supervisor.env <<'EOF'
AI_SUPERVISOR_ENABLED=false
AI_SUPERVISOR_MODEL=opencode/deepseek-v4.1-flash-free
AI_SUPERVISOR_TIMEOUT_SECONDS=900
AI_SUPERVISOR_ROUND_TIMEOUT_SECONDS=420
AI_SUPERVISOR_MAX_ITERATIONS=2
AI_SUPERVISOR_MAX_STEPS=12
AI_SUPERVISOR_OPENCODE_BIN=opencode
AI_SUPERVISOR_INSTALL_OPENCODE=false
AI_SUPERVISOR_FULL_DEPLOY_ONLY=true
AI_SUPERVISOR_SKIP_WHEN_HEALTHY=false
AI_SUPERVISOR_REQUIRED=false
AI_SUPERVISOR_ROLLBACK=true
AI_SUPERVISOR_DRY_RUN=false
EOF
chmod 640 /opt/mangapoisk-reborn/env/ai-supervisor.env
chown root:mangapoisk /opt/mangapoisk-reborn/env/ai-supervisor.env
systemctl restart mangapoisk-control.service
```

| Переменная | Смысл |
| --- | --- |
| `AI_SUPERVISOR_ENABLED` | главный выключатель; `false` — полностью выключен |
| `AI_SUPERVISOR_MODEL` | только `opencode/deepseek-v4.1-flash-free` |
| `AI_SUPERVISOR_TIMEOUT_SECONDS` | общий бюджет, 60–3600 |
| `AI_SUPERVISOR_ROUND_TIMEOUT_SECONDS` | бюджет раунда, ≤ общего |
| `AI_SUPERVISOR_MAX_ITERATIONS` | 1–5 раундов |
| `AI_SUPERVISOR_MAX_STEPS` | 4–40 шагов модели (должен совпадать с агентом) |
| `AI_SUPERVISOR_OPENCODE_BIN` | путь/имя CLI |
| `AI_SUPERVISOR_INSTALL_OPENCODE` | во время деплоя запускать installer, если OpenCode отсутствует |
| `AI_SUPERVISOR_FULL_DEPLOY_ONLY` | запускать только для полного inventory |
| `AI_SUPERVISOR_SKIP_WHEN_HEALTHY` | не запускать, если health уже зелёный |
| `AI_SUPERVISOR_REQUIRED` | если `true`, отсутствие OpenCode/модели валит job |
| `AI_SUPERVISOR_ROLLBACK` | source-only rollback при failed/timeout |
| `AI_SUPERVISOR_DRY_RUN` | собрать prompt/отчёт, но не запускать OpenCode |

## 9. Тесты

```bash
pytest tests/control/test_ai_supervisor.py -q
pytest tests/control -q
ruff check services/control tests/control
npm --prefix apps/web run typecheck
```

Покрыто:

- permission guard: чужие сервисы, nginx, Project-Kontur, alpine, docker,
  apt, БД, секреты, `rm -rf`, chaining/pipes;
- fail-closed config и сверка installer JSON с `SupervisorPolicy`;
- prompt construction, границы, недоверенные логи;
- timeout, max rounds, dry-run, graceful skip при отсутствии OpenCode/модели;
- report capture и admin-поля;
- rollback только `mangapoisk-*`, без БД;
- fake `opencode` binary: аргументы, `--file`, `--auto`, `--format json`,
  free-модель;
- полный/частичный deploy detection;
- control unit читает operator override последним.

## 10. Rollout (после approval lead)

Порядок обязателен. Ничего из этого не выполнять без явного approval.

### Шаг 0 — review

1. Lead review ветки `feat/ai-deploy-supervisor`, тестов и diff.
2. Убедиться, что `main` не менялся и merge/deploy делает lead.

### Шаг 1 — предохранитель

На `primary-85` (где живёт control) **до** деплоя кода:

```bash
install -d -m 750 /opt/mangapoisk-reborn/env
cat > /opt/mangapoisk-reborn/env/ai-supervisor.env <<'EOF'
AI_SUPERVISOR_ENABLED=false
AI_SUPERVISOR_MODEL=opencode/deepseek-v4.1-flash-free
AI_SUPERVISOR_TIMEOUT_SECONDS=900
AI_SUPERVISOR_ROUND_TIMEOUT_SECONDS=420
AI_SUPERVISOR_MAX_ITERATIONS=2
AI_SUPERVISOR_MAX_STEPS=12
AI_SUPERVISOR_OPENCODE_BIN=opencode
AI_SUPERVISOR_INSTALL_OPENCODE=false
AI_SUPERVISOR_FULL_DEPLOY_ONLY=true
AI_SUPERVISOR_SKIP_WHEN_HEALTHY=false
AI_SUPERVISOR_REQUIRED=false
AI_SUPERVISOR_ROLLBACK=true
AI_SUPERVISOR_DRY_RUN=false
EOF
chmod 640 /opt/mangapoisk-reborn/env/ai-supervisor.env
chown root:mangapoisk /opt/mangapoisk-reborn/env/ai-supervisor.env
```

Это гарантирует, что новый control не запустит supervisor, пока нет
OpenCode/auth.

### Шаг 2 — backup

- Зафиксировать snapshot/backup control DB и `.env` по `docs/OPS.md`.
- Записать текущий commit и job id последнего успешного деплоя.
- Не копировать секреты в issue/чат.

### Шаг 3 — установка OpenCode (canary → jump → primary)

Скопировать `scripts/ops/install_opencode.sh` на каждый узел по
[`docs/OPENCODE.md`](OPENCODE.md) §3.2.

```bash
# canary
ssh root@85.192.30.224 'bash /root/install_opencode.sh --require-model'
# jump
ssh root@83.141.92.137 'bash /root/install_opencode.sh --require-model'
# primary через jump
ssh -J root@83.141.92.137 root@85.192.37.58 \
  'bash /root/install_opencode.sh --require-model'
```

На каждом узле выполнить auth, если installer сообщил `auth: missing`:

```bash
ssh -t root@<host> 'opencode auth login'
ssh root@<host> "opencode models | grep -x 'opencode/deepseek-v4.1-flash-free'"
```

Альтернатива ручному копированию: после canary включить
`AI_SUPERVISOR_INSTALL_OPENCODE=true` в
`/opt/mangapoisk-reborn/env/ai-supervisor.env`; очередной полный деплой
запустит installer на узле. Для первого rollout всё равно рекомендуется
ручная установка/`--check`, чтобы ошибки сети были видны сразу.

### Шаг 4 — dry-run

На `primary-85`:

```bash
sed -i 's/^AI_SUPERVISOR_ENABLED=.*/AI_SUPERVISOR_ENABLED=true/' \
  /opt/mangapoisk-reborn/env/ai-supervisor.env
sed -i 's/^AI_SUPERVISOR_DRY_RUN=.*/AI_SUPERVISOR_DRY_RUN=true/' \
  /opt/mangapoisk-reborn/env/ai-supervisor.env
systemctl restart mangapoisk-control.service
```

Сделать полный деплой **aeza-2** через админку/control. Проверить:

- job `done`;
- в админке блок «AI-супервизор» со статусом `dry_run`;
- в job log есть отметка супервизора и фрагмент prompt в отчёте, но нет
  запуска OpenCode;
- на `aeza-2` нет новых изменённых файлов.

### Шаг 5 — canary

```bash
sed -i 's/^AI_SUPERVISOR_DRY_RUN=.*/AI_SUPERVISOR_DRY_RUN=false/' \
  /opt/mangapoisk-reborn/env/ai-supervisor.env
systemctl restart mangapoisk-control.service
```

Полный деплой `aeza-2`; смотреть job log/админку 15 минут. Ожидаемо:
`healthy` (или `recovered`, если был сбой). Проверить audit и отсутствие
команд к чужим сервисам.

### Шаг 6 — остальные узлы

Только после успешного canary:

1. полный деплой `jump-83`;
2. полный деплой `primary-85` в согласованное окно;
3. 15 минут наблюдать 5xx/health/логи.

### Шаг 7 — выключение/откат

Мгновенно:

```bash
sed -i 's/^AI_SUPERVISOR_ENABLED=.*/AI_SUPERVISOR_ENABLED=false/' \
  /opt/mangapoisk-reborn/env/ai-supervisor.env
systemctl restart mangapoisk-control.service
```

Это не меняет app-код и не трогает сервисы. Source-only rollback конкретного
деплоя выполняет control; ручной откат — по `docs/OPS.md`.

## 11. Что должен подтвердить владелец

1. Установка OpenCode на все три узла (сеть/пакетная политика).
2. Способ auth free-модели: интерактивный `opencode auth login` под root на
   каждом узле **или** защищённая передача `OPENCODE_API_KEY`.
3. Разрешение supervisor работать от root/deploy-пользователя с правом
   restart `mangapoisk-*` и edit `src`.
4. Окно canary/dry-run и последующего полного деплоя.
5. Политика хранения `logs/ai-supervisor-*.log` и `run/ai-supervisor-*.md`
   (там могут быть фрагменты логов приложения, но не секреты).
