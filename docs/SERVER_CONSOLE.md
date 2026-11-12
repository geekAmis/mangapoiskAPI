# Ограниченная серверная консоль

Консоль в админке — **не произвольный shell**. Запрос проходит через
allowlist-парсер, выполняется как argv-вектор по SSH, а каждое обращение
попадает в audit log. Взлом админки не даёт выполнить `rm`, `sudo`, `apt`,
`docker system prune`, прочитать `.env` или затронуть чужие сервисы
(Project-Kontur, alpine и т.п.).

## API

Все маршруты доступны только администратору (`require_admin` в gateway).
Gateway передаёт имя администратора в control через `X-Admin-User`; control
принимает только internal-token.

```
GET  /api/v1/admin/servers
POST /api/v1/admin/servers/{id}/console
GET  /api/v1/admin/servers/{id}/console/history?limit=50
GET  /api/v1/admin/jobs?limit=30
```

Тело запроса — либо read-only команда, либо структурированное действие:

```json
{"command": "systemctl status mangapoisk-gateway"}
```

```json
{"action": "service_restart", "params": {"service": "gateway"}}
```

Ответ:

```json
{
  "ok": true,
  "kind": "command",
  "action": "status",
  "command": "systemctl status mangapoisk-gateway",
  "output": "...",
  "exit_code": 0,
  "duration_ms": 84,
  "truncated": false,
  "timed_out": false,
  "output_hash": "sha256...",
  "job_id": null,
  "message": null
}
```

Для действий `deploy`, `rollback`, `port_change`, `add_service` возвращается
`job_id` control-задачи; `output` пустой.

## Allowlist read-only команд

| Команда | Ограничения |
|---|---|
| `systemctl status\|is-active\|is-failed [--no-pager] mangapoisk-*` | unit только `mangapoisk-<service>.service` из списка MangaPoisk |
| `journalctl -u mangapoisk-* -n N [--no-pager]` | `1 ≤ N ≤ 500` |
| `docker ps` | ровно `docker ps`, без `prune/exec/system` |
| `ss -ltnp` | точно |
| `df -h` | точно |
| `free -h` | точно |
| `uptime` | точно |
| `curl -s\|-fsS 127.0.0.1:<port>/health` | только loopback, только `/health`, порт из inventory сервера, 1024–65535 |
| `ls -la /opt/mangapoisk-reborn` | только корень проекта, без вложенных путей |

Любой другой argv отклоняется с `422 console_command_denied`.

## Структурированные действия

| Action | Параметры | Поведение |
|---|---|---|
| `service_start` | `service` | `systemctl start mangapoisk-<service>.service` |
| `service_stop` | `service` | `systemctl stop mangapoisk-<service>.service` |
| `service_restart` | `service` | `systemctl restart mangapoisk-<service>.service` |
| `deploy` | `services[]?`, `update?` | control deploy job; сервисы только из inventory |
| `rollback` | — | control job: меняет `$ROOT/src` и `$ROOT/src.old`, переустанавливает зависимости, перезапускает unit-файлы и ждёт `/health` |
| `port_change` | `service`, `port` | порт 1024–65535, только настроенный сервис, порт не занят; обновляет inventory и запускает deploy job |
| `add_service` | `service`, `port` | только известный микросервис MangaPoisk, ещё не настроенный, порт свободен; добавляет в inventory и запускает deploy job |

Сервисы вне inventory, чужие unit-файлы и не-MangaPoisk коды отклоняются.

## Что отклоняется до SSH

- shell-метасимволы: `; | & $ > <` обратные кавычки, кавычки, `(){}[]*?!#~`,
  переводы строк и управляющие символы;
- `sudo`, `rm`, `dd`, `mkfs`, `docker system prune`, `apt`, `apt-get`,
  `sh`, `bash`, `python`, `perl`, `nc`, `nmap`, `kill`, `mount`, `chmod`,
  `chown`, `crontab`, `scp`, `wget` и другие опасные утилиты;
- `.env`, `secret`, `token`, `password`, `id_rsa`, `authorized_keys`;
- произвольные пути и чужие сервисы (`Project-Kontur`, `alpine`, ...);
- порт вне 1024–65535, занятый порт, неизвестный сервис;
- одновременная передача `command` и `action`;
- команда длиннее 1000 символов.

Отклонённый запрос тоже аудируется: сохраняются `admin`, `server_id`, хеш
команды (не сама команда), код отказа и длительность. Значения параметров
отклонённого действия не логируются — только имена ключей.

## Лимиты

- таймаут выполнения — **30 секунд** (жёсткий deadline на SSH-канале);
- лимит вывода — **200 KB**; лишнее отбрасывается, ответ помечается
  `truncated: true`;
- при таймауте `exit_code: -1`, `timed_out: true`, в вывод добавляется
  `[console] timeout after 30s`;
- одновременно с сервера читается не больше 200 KB, поэтому большой
  `journalctl` не раздувает память control.

## Аудит

Каждый вызов пишет запись `console.command` или `console.action`:

```json
{
  "admin": "admin",
  "command": "systemctl status mangapoisk-gateway",
  "exit_code": 0,
  "output_hash": "sha256:...",
  "duration_ms": 84,
  "truncated": false,
  "timed_out": false
}
```

Для job-действий вместо `exit_code`/`output_hash` сохраняется `job_id`.
Сырой вывод команды в аудит не попадает. История доступна через
`GET /api/v1/admin/servers/{id}/console/history` и показывается на вкладке
«Терминал».

## UI

Вкладка «Терминал»:

- список всех серверов из control inventory (имя, host, healthy-сервисы);
- тёмное окно вывода с exit code, длительностью, truncation/timeout;
- быстрые кнопки: `systemctl status`, журнал, health, `docker ps`,
  `ss -ltnp`, `df -h`, `free -h`, `uptime`, `ls` проекта;
- история ввода (↑/↓) в `localStorage` и серверная история вызовов;
- структурированные формы: restart/start/stop, deploy, rollback,
  смена порта 1024–65535, добавление сервиса;
- deep link `/admin?tab=terminal&server=<uuid>`.

Проверено на 1440×900 и 390×844: нет горизонтального overflow и ошибок
в console.

## Тесты

```bash
pytest tests/control/test_console.py
```

Покрыто:

- accept/reject allowlist, включая `systemctl`, `journalctl`, `curl`, `ls`;
- инъекции `; | & $ > <`, backticks, `$(...)`, перевод строки;
- `sudo`, `rm`, `dd`, `mkfs`, `docker system prune`, `apt`, секреты;
- чужие сервисы (`Project-Kontur`, `alpine`) и unit-файлы;
- диапазон портов, занятые порты, неизвестные сервисы;
- timeout и лимит 200 KB на SSH-канале;
- audit: admin, server, command/action, exit code, output hash, без вывода;
- auth: internal-token для control и admin JWT для gateway.

## Эксплуатация

1. Убедиться, что на сервере есть `mangapoisk-*.service` и SSH-доступ из
   control (напрямую или через jump-host).
2. Проверить `GET /api/v1/admin/servers` — сервер виден, сервисы в inventory.
3. Открыть `/admin?tab=terminal&server=<id>`, выполнить `uptime` и
   `systemctl status mangapoisk-gateway`.
4. Проверить `GET /api/v1/admin/servers/<id>/console/history` — появились две
   записи с `output_hash` и без вывода.
5. Для rollback убедиться, что после предыдущего деплоя существует
   `/opt/mangapoisk-reborn/src.old`; иначе job завершится ошибкой
   `ROLLBACK_FAIL` без изменения рабочего каталога.

## Ограничения

- SSH host key принимается при первом подключении (как `accept-new`).
- Консоль не поддерживает интерактивные команды и произвольные флаги.
- `journalctl` ограничен 500 строками, вывод — 200 KB.
- Rollback восстанавливает предыдущий `src`, но не откатывает миграции БД.
