# Operations scripts

These files are the source of truth for the production runbooks in
[`docs/OPS.md`](../../docs/OPS.md).  Install them on `primary-85`; the restore
drill is also installed on `jump-83` for disaster recovery.

| File | Installed as |
| --- | --- |
| `mangapoisk-backup.sh` | `/usr/local/sbin/mangapoisk-backup.sh` |
| `mangapoisk-restore-drill.sh` | `/usr/local/sbin/mangapoisk-restore-drill.sh` |
| `mangapoisk-backup.service` | `/etc/systemd/system/mangapoisk-backup.service` |
| `mangapoisk-backup.timer` | `/etc/systemd/system/mangapoisk-backup.timer` |
| `mangapoisk-restore-drill.service` | `/etc/systemd/system/mangapoisk-restore-drill.service` |
| `mangapoisk-backup.logrotate` | `/etc/logrotate.d/mangapoisk-backup` |
| `mangapoisk-control-memory.conf` | `/etc/systemd/system/mangapoisk-control.service.d/memory.conf` |
| `mangapoisk-watchdog.py` | `/usr/local/sbin/mangapoisk-watchdog.py` |
| `mangapoisk-watchdog.service` | `/etc/systemd/system/mangapoisk-watchdog.service` |
| `mangapoisk-watchdog.timer` | `/etc/systemd/system/mangapoisk-watchdog.timer` |
| `mangapoisk-alert@.service` | `/etc/systemd/system/mangapoisk-alert@.service` |
| `mangapoisk-onfailure.conf` | `/etc/systemd/system/mangapoisk-<service>.service.d/10-onfailure.conf` |

## Prerequisites

On `primary-85` and `jump-83`:

```bash
apt-get install -y restic sqlite3 python3
```

`sqlite3` must be **3.27 or newer** for `VACUUM INTO` (production runs 3.46.1).
On an older build the backup script logs a warning and falls back to the
online `.backup` API, so keep the package current before relying on the
non-restarting copy path.

The encrypted restic repository lives on `jump-83` at
`/srv/mangapoisk-backups/restic`.  The backup account and SSH key are described
in `docs/OPS.md` §4.1.

## Install

```bash
install -m 755 mangapoisk-backup.sh mangapoisk-restore-drill.sh /usr/local/sbin/
install -m 644 mangapoisk-backup.service mangapoisk-backup.timer \
  mangapoisk-restore-drill.service /etc/systemd/system/
install -m 644 mangapoisk-backup.logrotate /etc/logrotate.d/mangapoisk-backup
systemctl daemon-reload
systemctl enable --now mangapoisk-backup.timer
```

Install the observability watchdog and failed-unit hook:

```bash
install -m 755 mangapoisk-watchdog.py /usr/local/sbin/
install -m 644 mangapoisk-watchdog.service mangapoisk-watchdog.timer \
  mangapoisk-alert@.service /etc/systemd/system/
install -d -o mangapoisk -g mangapoisk -m 750 /var/lib/mangapoisk-watchdog
systemctl daemon-reload
systemctl enable --now mangapoisk-watchdog.timer

# Repeat for every long-running mangapoisk-<service>.service.
install -d /etc/systemd/system/mangapoisk-gateway.service.d
install -m 644 mangapoisk-onfailure.conf \
  /etc/systemd/system/mangapoisk-gateway.service.d/10-onfailure.conf
systemctl daemon-reload
```

Full metric/alert documentation and the runbook live in
[`docs/OBSERVABILITY.md`](../../docs/OBSERVABILITY.md).

Create the repository once from `primary-85`:

```bash
restic -r sftp:mpbackup-jump:/srv/mangapoisk-backups/restic \
  --password-file /root/.restic-password init
```

Run a backup and a drill:

```bash
/usr/local/sbin/mangapoisk-backup.sh
/usr/local/sbin/mangapoisk-restore-drill.sh latest
```

The drill deliberately refuses targets outside
`/var/tmp/mangapoisk-restore-drill-*` and never writes to
`/opt/mangapoisk-reborn/data`.
