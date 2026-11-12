# OpenCode на серверах MangaPoisk Reborn

Статус: **подготовлено, в production не установлено**. Установка на
`primary-85`, `jump-83` и `aeza-2` выполняется только после approval lead
(issue [#75](https://github.com/geekAmis/mangapoiskAPI/issues/75)).

Документ описывает установку OpenCode V2, бесплатную модель
`opencode/deepseek-v4.1-flash-free`, системный конфиг, кастомного агента
`deploy-supervisor`, `SKILL.md`, матрицу разрешений и диагностику. Runbook
самого AI-супервизора — в [`docs/AI_DEPLOY.md`](AI_DEPLOY.md).

## 1. Зачем

OpenCode — это CLI-агент, который запускается на самом узле и видит локальные
логи, `systemctl` и файлы приложения. Control вызывает его после полного
деплоя, чтобы:

- проверить `systemctl is-active` и `/health` всех `mangapoisk-*`;
- найти traceback/5xx/locked/OOM в journald;
- исправить небольшую ошибку в `/opt/mangapoisk-reborn/src`;
- перезапустить только сломанный `mangapoisk-*` и повторить проверку;
- вернуть структурированный отчёт в job log и админку.

OpenCode не является заменой control: решение о запуске, таймауте, откате и
финальном статусе job принимает control.

## 2. Совместимость и модель

- Требуется **OpenCode V2** (проверено на `v2.1.4`).
- Единственная разрешённая модель: `opencode/deepseek-v4.1-flash-free`.
- Платные модели (`opencode/deepseek-v4-pro`, `claude-*`, `gpt-*` и т. п.)
  запрещены на уровне `ControlSettings` и `build_opencode_argv`.
- `update: "disable"` в системном конфиге: серверный OpenCode не обновляется
  сам. Обновление — только через installer после approval.

### 2.1 Free tier и авторизация

Free-модель не является полностью анонимной: без аккаунта провайдер
`opencode` может отсутствовать, а анонимный лимит — закончиться
(`Free usage limit reached`). Проверено 2026-11-13: анонимный запуск
`opencode/deepseek-v4.1-flash-free` вернул именно `Free usage limit reached`,
поэтому для production нужен вход/аккаунт. Поэтому на каждом узле нужен один
из вариантов:

1. **Рекомендуется:** интерактивный вход под тем же пользователем, от которого
   control ходит по SSH (обычно `root`):

   ```bash
   ssh -t root@<host> 'opencode auth login'
   # выбрать OpenCode Console / бесплатный аккаунт
   ```

2. `OPENCODE_API_KEY` в окружении процесса OpenCode. Installer **не пишет**
   ключ на диск. Если ключ нужен, его передаёт владелец через защищённый
   mechanism (systemd drop-in/ssh environment); не коммитить и не хранить в
   репозитории.

Проверка:

```bash
opencode models | grep -x 'opencode/deepseek-v4.1-flash-free'
```

Installer делает эту проверку и:

- при успехе печатает `auth: ok`;
- при отсутствии модели печатает предупреждение и завершает установку с
  кодом `0` (graceful);
- с `--require-model` завершается ошибкой — используйте этот режим в
  rollout, когда auth обязателен.

Control при недоступной модели не валит деплой: супервизор получает
`AI_SUPERVISOR_SKIPPED free_model_unavailable`, job остаётся в исходном
статусе. Если нужен строгий режим, задайте `AI_SUPERVISOR_REQUIRED=true`.

## 3. Установка

### 3.1 Файлы

| Файл | Назначение |
| --- | --- |
| `scripts/ops/install_opencode.sh` | идемпотентная установка CLI + config + agent + skill |
| `/etc/opencode/opencode.json` | системный конфиг (высший приоритет) |
| `/etc/opencode/agents/deploy-supervisor.md` | кастомный primary-агент |
| `/etc/opencode/skills/deploy-supervisor/SKILL.md` | runbook для агента |
| `/usr/local/bin/opencode` | symlink на `/root/.opencode/bin/opencode` |

Installer:

- проверяет root, `curl`, `tar`, версию OpenCode;
- если CLI нет или стоит V1 — ставит официальный бинарник V2
  (`https://opencode.ai/v2/install`) в `/root/.opencode/bin` и делает symlink;
- если V2 уже есть — не переустанавливает без `--force`;
- пишет config/agent/skill атомарно, старый config сохраняет в
  `opencode.json.bak-<timestamp>`;
- не пишет секреты;
- проверяет JSON и наличие free-модели.

### 3.2 Команды для трёх узлов

Скопировать installer (пример — с рабочей машины, где лежит репозиторий):

```bash
# jump-83
scp scripts/ops/install_opencode.sh root@83.141.92.137:/root/

# primary-85 через jump-83
scp -J root@83.141.92.137 scripts/ops/install_opencode.sh root@85.192.37.58:/root/

# aeza-2
scp scripts/ops/install_opencode.sh root@85.192.30.224:/root/
```

Установка (сначала canary `aeza-2`, затем `jump-83`, затем `primary-85`):

```bash
ssh root@85.192.30.224 'bash /root/install_opencode.sh --require-model'

ssh root@83.141.92.137 'bash /root/install_opencode.sh --require-model'

ssh -J root@83.141.92.137 root@85.192.37.58 \
  'bash /root/install_opencode.sh --require-model'
```

Проверка без изменений:

```bash
ssh root@<host> 'bash /root/install_opencode.sh --check'
```

Обновление/переустановка (после approval):

```bash
ssh root@<host> 'OPENCODE_VERSION=2.1.4 bash /root/install_opencode.sh --force'
```

`--max-steps N` задаёт лимит шагов агента (по умолчанию 12, допустимо 4–40).
Тот же лимит должен быть в `AI_SUPERVISOR_MAX_STEPS` control.

### 3.3 Установка во время деплоя

Если включить `AI_SUPERVISOR_INSTALL_OPENCODE=true` в
`/opt/mangapoisk-reborn/env/ai-supervisor.env`, deploy-скрипт после установки
venv запустит `$ROOT/src/scripts/ops/install_opencode.sh --skip-auth-check` от
root. Installer идемпотентен: при наличии V2 он только перезапишет managed
config/agent/skill; при ошибке сети деплой **не** падает, а пишет
`OPENCODE_INSTALL_WARNING`, и supervisor позже пропустится. Auth всё равно
нужен отдельно (`opencode auth login`).

По умолчанию hook выключен (`false`), чтобы не ставить OpenCode до approval.

### 3.3 Ручная проверка после установки

```bash
ssh root@<host> 'opencode --version'
ssh root@<host> "opencode models | grep -x 'opencode/deepseek-v4.1-flash-free'"
ssh root@<host> 'python3 -m json.tool /etc/opencode/opencode.json >/dev/null && echo config-ok'
```

Безопасный smoke-тест (модель не должна трогать файлы; это просто проверка
запуска и auth):

```bash
ssh root@<host> 'cd /opt/mangapoisk-reborn && \
  opencode run --agent deploy-supervisor \
    --model opencode/deepseek-v4.1-flash-free \
    --format json --auto "Reply with exactly OK"'
```

Не запускать полноценный supervisor на production до approval lead.

## 4. Конфиг и матрица разрешений

`/etc/opencode/opencode.json` — fail-closed: первое правило запрещает всё,
дальше идут узкие разрешения. Порядок важен: в OpenCode побеждает последнее
совпавшее правило.

| Действие | Ресурс | Эффект |
| --- | --- | --- |
| `*` | `*` | `deny` (база) |
| `read` | `/opt/mangapoisk-reborn/**`, `src/**`, `logs/**`, `web/**`, `docs/**`, `README*` | `allow` |
| `read` | `run/ai-supervisor-*.md` (brief) | `allow` |
| `read` | `.env`, `**/.env*`, `env/**`, `data/**` | `deny` |
| `edit` | `/opt/mangapoisk-reborn/src/**`, `src/**` | `allow` |
| `edit` | `.env`, `env/**`, `data/**` | `deny` |
| `glob`, `grep` | `*` | `deny` (поиск только shell-командой по `logs/*`) |
| `external_directory` | `/opt/mangapoisk-reborn/**` | `allow` |
| `skill` | `deploy-supervisor` | `allow` |
| `subagent`, `question`, `webfetch`, `websearch` | `*` | `deny` |

Shell разрешён только для узкого набора команд:

- `systemctl is-active|status|cat|list-units|start|restart mangapoisk-*`;
- `journalctl -u mangapoisk-*`;
- `curl -fsS [--max-time N] http://127.0.0.1:<port>/health`;
- чтение только логов: `tail`, `grep`, `cat` по
  `/opt/mangapoisk-reborn/logs/*`;
- `ls`, `du`, `stat`, `sha256sum` по `/opt/mangapoisk-reborn/*`;
- `df -h`, `free -m`, `uptime`, `nproc`, `ss -ltnp`, `sleep`;
- `venv/bin/python -m py_compile`/`compileall` по `src/*`;
- `venv/bin/pip install -r src/services/*/requirements.txt` и
  `pip install -e src/packages/manga_common`.

Запрещено всё остальное, в том числе:

- любые `systemctl` не для `mangapoisk-*` (`Project-Kontur`, `alpine`, nginx,
  Caddy, xray/tagasay, docker, postgres);
- `systemctl stop|disable|mask|edit|daemon-reload`;
- `rm -rf`, `docker system prune`, `apt upgrade`, `dpkg`, `ufw`, `iptables`,
  `useradd`, `chmod`, `chown`, `mount`, `reboot`;
- `sqlite3`, `psql`, `mysql`, `redis-cli` и любые записи в БД;
- чтение/печать `.env`, `env/*.env`, `data/**`, токенов и ключей;
- pipe, `;`, `&&`, `||`, redirect, backticks, `$()` — сканер OpenCode
  отклоняет такие команды, а control дополнительно аудирует их.

Агент `deploy-supervisor` дополнительно запрещает `systemctl stop/disable/
mask/edit/daemon-reload` и edit `data/**`, `env/**`; `steps: 12` ограничивает
внутренний цикл модели.

## 5. Аудит и диагностика

- Job log: `== AI supervisor ==` + весь JSON-поток OpenCode (обрезается до
  200 000 символов).
- Отчёт: `deployment_jobs.requested.supervisor` (виден в админке).
- Remote audit: `/opt/mangapoisk-reborn/logs/ai-supervisor-<job>.log`.
- Prompt: `/opt/mangapoisk-reborn/run/ai-supervisor-<job>.md` (mode 0600).
- Control audit log: `ai_supervisor.finished`.
- Логи OpenCode: `opencode debug paths log`, обычно
  `/root/.local/share/opencode/log/opencode.log`.

Типовые ошибки:

| Симптом | Причина | Действие |
| --- | --- | --- |
| `AI_SUPERVISOR_SKIPPED opencode_missing` | CLI не установлен/PATH | запустить installer |
| `AI_SUPERVISOR_SKIPPED free_model_unavailable` | нет auth/лимит | `opencode auth login` под deploy-пользователем |
| `AI_SUPERVISOR_SKIPPED timeout_missing` | нет `timeout(1)` | `apt-get install coreutils` (по approval) |
| `Model unavailable` | модель скрыта/платная | проверить `OPENCODE_DISABLE_FREE_MODELS`, конфиг |
| `Free usage limit reached` | исчерпан free-лимит | войти в аккаунт/подождать/эскалация владельцу |
| команда `deny` в логе | сработала матрица | это ожидаемо; агент должен сообщить `failed` |

## 6. Безопасность

- Supervisor работает от deploy-SSH пользователя (обычно `root`), потому что
  ему нужно перезапускать units и править root-owned `src`. Это осознанный
  риск; защита — fail-closed permissions, allowlist и аудит.
- `/etc/opencode` действует на всех пользователей узла. Интерактивный
  `opencode` на production тоже будет ограничен матрицей.
- Installer не пишет `OPENCODE_API_KEY`, пароли и SSH-ключи. Auth хранится
  самим OpenCode вне репозитория.
- Не устанавливать OpenCode на узлы без approval lead. Не запускать
  supervisor на production до dry-run и canary.
