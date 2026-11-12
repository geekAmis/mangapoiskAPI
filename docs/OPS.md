# MangaPoisk Reborn — Operations Runbook

Last verified: 2026-11-12 (UTC).  Scope: production nodes `primary-85`,
`jump-83` and `aeza-2`.  Credentials are **not** stored in this repository;
use the workspace access file and never commit passwords, tokens or private
keys.

## 1. Topology

| Name | Public address | Role | Notes |
| --- | --- | --- | --- |
| `primary-85` | `85.192.37.58` | Main writer: catalog, library, comments, control, gateway, parser, media, scheduler, replica | Tailscale `100.119.186.58`. Reached through `jump-83`. |
| `jump-83` | `83.141.92.137` | Jump host + warm standby: library, media, replica; Caddy; xray/tagasay | 2 GB RAM, 1 GB swap added 2026-11-12. |
| `aeza-2` | `85.192.30.224` | Fallback writer: catalog, library, media, parser, gateway, replica; nginx | Already had 4 GB swap. Reached with the credentials in the control inventory. |

Replica service listens on `8108`.  Every node pulls SQLite snapshots from the
healthy leader selected from the control registry
(`http://85.192.37.58:8088/api/v1/registry`).  `jump-83` and `aeza-2` pull from
`primary-85`; `primary-85` snapshots its own live files.

`primary-85` binds application services to `127.0.0.1`.  `jump-83` and `aeza-2`
bind fallback services to `0.0.0.0`, because they are selected by the control
registry.  Firewall rules preserve the existing fallback endpoints.

## 2. Access

```bash
# jump host
ssh root@83.141.92.137

# primary through the jump host (local port forward is the stable path)
ssh -J root@83.141.92.137 root@85.192.37.58
```

The workspace `data.txt` contains the current root passwords.  Do not copy it
to the repository, shell history, tickets or chat.  For automation, use the
dedicated `mpbackup` key described in §4.

## 3. Firewall (UFW)

UFW is active on all three nodes with `default deny incoming` and
`default allow outgoing`.  Rules were added **before** enabling, a five-minute
dead-man rollback timer was armed, and a second SSH session plus external
checks were used before the timer was cancelled.

### 3.1 Current rules

`primary-85`:

```text
22/tcp                         ALLOW IN  Anywhere      # SSH
80/tcp                         ALLOW IN  Anywhere      # ACME HTTP (certbot webroot/standalone)
8088/tcp                       ALLOW IN  Anywhere      # MangaPoisk HTTP
8443/tcp                       ALLOW IN  Anywhere      # MangaPoisk HTTPS
8080/tcp                       ALLOW IN  Anywhere      # existing ytdl service
8108/tcp                       ALLOW IN  83.141.92.137  # jump-83 replica
8108/tcp                       ALLOW IN  85.192.30.224  # aeza-2 replica
8108/tcp                       ALLOW IN  100.64.0.0/10  # tailscale replica
Anywhere on tailscale0         ALLOW IN  Anywhere      # tailscale interface
41641/udp                      ALLOW IN  Anywhere      # tailscale direct
```

`jump-83`:

```text
22/tcp                         ALLOW IN  Anywhere      # SSH
80/tcp                         ALLOW IN  Anywhere      # ACME HTTP / Caddy
443/tcp                        ALLOW IN  Anywhere      # HTTPS / Caddy
8080/tcp                       ALLOW IN  Anywhere      # existing tagasay service
8103/tcp                       ALLOW IN  Anywhere      # library fallback
8104/tcp                       ALLOW IN  Anywhere      # media fallback
8443/tcp                       ALLOW IN  Anywhere      # existing xray service
8108/tcp                       ALLOW IN  85.192.37.58   # primary-85 replica
8108/tcp                       ALLOW IN  85.192.30.224  # aeza-2 replica
```

`aeza-2`:

```text
22/tcp     ALLOW IN  Anywhere   # SSH
80/tcp     ALLOW IN  Anywhere   # HTTP nginx
443/tcp    ALLOW IN  Anywhere   # HTTPS nginx
8080/tcp   ALLOW IN  Anywhere   # existing ytdl service
1107/tcp   ALLOW IN  Anywhere   # existing node service
1108/tcp   ALLOW IN  Anywhere   # existing node service
8875/tcp   ALLOW IN  Anywhere   # gateway fallback
8904/tcp   ALLOW IN  Anywhere   # catalog fallback
8905/tcp   ALLOW IN  Anywhere   # media fallback
8907/tcp   ALLOW IN  Anywhere   # library fallback
8908/tcp   ALLOW IN  Anywhere   # parser fallback
8909/tcp   ALLOW IN  Anywhere   # media fallback
9179/tcp   ALLOW IN  Anywhere   # existing pyneon service
8108/tcp   ALLOW IN  85.192.37.58   # primary-85 replica
8108/tcp   ALLOW IN  83.141.92.137  # jump-83 replica
```

Ports `8103/8104` on `jump-83` and the `8875/8904/8905/8907/8908/8909`
fallback ports on `aeza-2` remain public to preserve the current failover
behaviour.  They are not part of the replica exposure and are listed as a
follow-up hardening item.

### 3.2 Safe change procedure

Never enable UFW in a single blind step.  Use this sequence on each node:

```bash
# 0. Back up state (root only)
ts=$(date -u +%Y%m%dT%H%M%SZ)
dir=/root/backups/ops-$(date -u +%Y%m%d)/$(hostname -s)
install -d -m 700 "$dir"
ufw status verbose     > "$dir/ufw-status-$ts.txt" 2>&1 || true
iptables-save          > "$dir/iptables-$ts.txt"   2>/dev/null || true
ip6tables-save         > "$dir/ip6tables-$ts.txt"  2>/dev/null || true
tar czf "$dir/etc-ufw-$ts.tar.gz" /etc/ufw

# 1. Add every rule while UFW is still inactive
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
# ... add the host-specific rules from §3.1 ...

# 2. Arm a dead-man rollback before enabling
systemd-run --unit=ufw-rollback --on-active=300 \
  --timer-property=AccuracySec=1s /usr/sbin/ufw --force disable

# 3. Enable and verify in the same SSH session
ufw --force enable
ufw status verbose
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8088/health
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8108/health

# 4. From a second connection and from an external host, verify SSH and the
#    intended public endpoints, then cancel the dead-man:
systemctl stop ufw-rollback.timer
systemctl reset-failed ufw-rollback.service
```

If a mistake is made, do **not** wait for the timer:

```bash
ufw --force disable          # immediate rollback
tar xzf /root/backups/ops-*/<host>/etc-ufw-*.tar.gz -C /
ufw --force enable           # only after the rules are corrected
```

### 3.3 Verification

From a machine outside the production network:

```bash
curl --max-time 5 -sS -o /dev/null -w '%{http_code}\n' http://85.192.37.58:8108/health   # expected 000/timeout
curl --max-time 5 -sS -o /dev/null -w '%{http_code}\n' http://83.141.92.137:8108/health  # expected 000/timeout
curl --max-time 5 -sS -o /dev/null -w '%{http_code}\n' http://85.192.30.224:8108/health  # expected 000/timeout
curl --max-time 5 -sS -o /dev/null -w '%{http_code}\n' http://85.192.37.58:8088/health  # expected 200
curl --max-time 5 -sk -o /dev/null -w '%{http_code}\n' https://85.192.37.58.nip.io:8443/health # expected 200
```

Between nodes (must still work):

```bash
# from jump-83
curl -sS http://85.192.37.58:8108/health
# from aeza-2
curl -sS http://85.192.37.58:8108/health
curl -sS http://83.141.92.137:8108/health
# from primary-85
curl -sS http://85.192.30.224:8108/health
```

Replication health:

```bash
TOKEN=$(grep '^INTERNAL_TOKEN=' /opt/mangapoisk-reborn/.env | cut -d= -f2-)
curl -sS -H "X-Internal-Token: $TOKEN" http://127.0.0.1:8108/internal/replica/status \
  | python3 -m json.tool | head -40
```

The `last_success_at` value must advance and `last_error` must stay `null`.
Catalog snapshots are large; a pull can take several minutes on a slow link.

## 4. Backups and restore

### 4.1 Design

* Restic repository: `sftp:mpbackup-jump:/srv/mangapoisk-backups/restic` on
  `jump-83` (off-host from `primary-85`).  Restic encrypts client-side.
* Repository password: `/root/.restic-password` (mode 0600) on `primary-85`
  and a root-only copy on `jump-83` for disaster recovery.  Store a copy in the
  team password manager; losing it makes the repository unrecoverable.
* Dedicated backup account: `mpbackup` on `jump-83`, home
  `/srv/mangapoisk-backups`, shell `/bin/sh`, key restricted with
  `restrict,command="/usr/lib/openssh/sftp-server"` in
  `/srv/mangapoisk-backups/.ssh/authorized_keys`.  Only the SFTP subsystem is
  usable.
* Primary key: `/root/.ssh/mpbackup_ed25519`; SSH alias `mpbackup-jump` in
  `/root/.ssh/config`.

Backup scope:

* SQLite databases snapshotted with `.backup` (online backup API) and checked
  with `PRAGMA integrity_check`: `catalog.db`, `library.db`, `comments.db`,
  `control.db`, `archives.db` (media metadata).
* `chapter-archives/` (user-downloaded ZIPs).
* Critical config: `.env`, `env/*.env`, nginx config, systemd units,
  `source-cookies.json`, `/etc/ufw`, `/etc/ssh/sshd_config`, `/etc/fstab`,
  `/etc/sysctl.d`, `/etc/letsencrypt`.
* Not backed up: `media-cache/` (regenerable), `data/replica/` (derived
  snapshots), `exports/` (transient).  This keeps the backup near 1 GB instead
  of >3 GB.
* The timer runs on `primary-85` because it is the writer.  `jump-83` and
  `aeza-2` hold replicated snapshots and fallback copies; after a promotion,
  install/enable the same timer on the new writer and add its live data to the
  scope.

### 4.2 Schedule and retention

* `mangapoisk-backup.timer` runs at `00:15, 06:15, 12:15, 18:15 UTC`
  (`Persistent=true`, random delay up to 5 min).  RPO is therefore **≤ 6 h**
  for databases and archives.
* Retention: **7 daily + 4 weekly + 3 monthly** (`restic forget --prune` at most
  once per UTC day).
* Weekly repository check: `restic check --read-data-subset=2%`.
* Log: `/var/log/mangapoisk-backup.log`, rotated weekly by
  `/etc/logrotate.d/mangapoisk-backup` (8 rotations).  Also in the journal:
  `journalctl -u mangapoisk-backup`.

### 4.3 Manual commands

```bash
# run a backup now
/usr/local/sbin/mangapoisk-backup.sh
tail -50 /var/log/mangapoisk-backup.log

# inspect snapshots
restic -r sftp:mpbackup-jump:/srv/mangapoisk-backups/restic \
  --password-file /root/.restic-password snapshots

# timer status
systemctl list-timers mangapoisk-backup.timer
systemctl status mangapoisk-backup.service

# restore drill (isolated /var/tmp; never touches production)
/usr/local/sbin/mangapoisk-restore-drill.sh latest

# disaster-recovery drill from jump-83 (local repository)
RESTIC_REPOSITORY=/srv/mangapoisk-backups/restic \
  /usr/local/sbin/mangapoisk-restore-drill.sh latest
```

The restore drill restores the latest snapshot under
`/var/tmp/mangapoisk-restore-drill-<timestamp>`, verifies every SQLite file with
`PRAGMA integrity_check`, compares every `row.<db>.<table>=<count>` entry from
`MANIFEST.txt`, and checks the ZIP count.  It prints `RESTORE DRILL PASS` only
when all checks succeed.  Remove the target after reviewing:

```bash
rm -rf /var/tmp/mangapoisk-restore-drill-*
```

### 4.4 Restore procedure (production, planned)

1. Announce the maintenance window and stop the writers for the databases being
   restored:
   ```bash
   systemctl stop mangapoisk-catalog mangapoisk-library mangapoisk-comments \
     mangapoisk-media mangapoisk-scheduler
   ```
2. Restore the snapshot into a staging directory (same command as the drill).
3. Verify `PRAGMA integrity_check` and row counts.
4. Copy the verified database over the live file, keeping a `.bak`:
   ```bash
   install -o mangapoisk -g mangapoisk -m 640 \
     /var/tmp/mangapoisk-restore-drill-*/var/tmp/mangapoisk-backup/db/catalog.db \
     /opt/mangapoisk-reborn/data/catalog.db
   ```
   Repeat for `library.db`, `comments.db`, `control.db`, `archives.db`.
5. Restore `chapter-archives/` if needed:
   ```bash
   rsync -a --delete \
     /var/tmp/mangapoisk-restore-drill-*/opt/mangapoisk-reborn/data/chapter-archives/ \
     /opt/mangapoisk-reborn/data/chapter-archives/
   ```
6. Restore config from the snapshot if the host was rebuilt, then
   `systemctl daemon-reload` and start the services.
7. Verify `/health`, `/ready`, the gateway registry, and replica status.

RTO: about **15–30 minutes** for the databases, **30–60 minutes** including
chapter archives and validation on a healthy host.  A bare-metal rebuild is
longer and depends on OS/package installation.

### 4.5 Monitoring

* `systemctl list-timers mangapoisk-backup.timer` — next run.
* `systemctl status mangapoisk-backup.service` — last result.
* `journalctl -u mangapoisk-backup -n 100` — errors.
* `restic snapshots` — latest snapshot age (alert if > 12 h).
* `restic check` — repository integrity (weekly, logged).
* `df -h /srv` on `jump-83` — repository space.
* A failed backup does not stop services; it leaves the previous snapshot in
  place.  Escalate if two consecutive runs fail.
* The repository is on a separate host but in the same provider/region.  For
  geographic DR, replicate the restic repository to S3-compatible object
  storage as a next step.

### 4.6 Off-host configuration copies

The pre-change configuration for each node is stored under
`/root/backups/ops-20261112/<host>/` and copied off-host:

* `primary-85` → `jump-83:/root/backups/ops-20261112/offhost/primary-85/`
* `jump-83` → `primary-85:/root/backups/ops-20261112/jump-83-offhost/`
* `aeza-2` → `primary-85:/root/backups/ops-20261112/aeza-2/` and
  `jump-83:/root/backups/ops-20261112/offhost/aeza-2/`

These directories are root-only (0700).  The unencrypted configuration tars
must never live in `/srv/mangapoisk-backups` (the `mpbackup` home); only the
encrypted restic repository belongs there.

Each directory contains UFW state, iptables/ip6tables, listening sockets,
systemd unit list, `/etc/fstab`, sysctl, SSH config and the app config tar
(secrets included, mode 0600).

## 5. Memory and swap

### 5.1 Swap

| Host | Swap | swappiness | File |
| --- | --- | --- | --- |
| `primary-85` | 2 GB | 10 | `/swapfile` |
| `jump-83` | 1 GB | 10 | `/swapfile` |
| `aeza-2` | 4 GB (pre-existing) | 60 | provider default |

Persistence is via `/etc/fstab`:

```text
/swapfile none swap sw 0 0
```

`/etc/sysctl.d/99-mangapoisk-memory.conf` sets `vm.swappiness = 10` on
`primary-85` and `jump-83`.  Verify:

```bash
swapon --show
free -m
sysctl vm.swappiness
grep swapfile /etc/fstab
```

### 5.2 Control-plane guardrail

`mangapoisk-control` showed a 910 MB RSS high-water on 2026-11-12 (252 MB →
910 MB over about 35 minutes).  After a controlled restart it grew to ~170 MB
and then stayed flat for the rest of a 10-minute sample; the 910 MB peak was
not reproduced without deployment activity.  A 24-hour observation and
metrics are tracked in issue #59.  The service is protected with a systemd
drop-in regardless:

```text
/etc/systemd/system/mangapoisk-control.service.d/memory.conf
[Service]
MemoryAccounting=yes
MemoryHigh=1G
MemoryMax=1536M
```

`MemoryHigh` reclaims/throttles first; `MemoryMax` is a safety valve that
restarts the service instead of letting the host OOM-kill other services.  The
runtime values were applied with `systemctl set-property --runtime` so no
restart was needed.  Check:

```bash
systemctl show mangapoisk-control -p MemoryCurrent,MemoryHigh,MemoryMax,MemoryPeak
```

Root cause and permanent fix (shared `httpx.AsyncClient` for the 10-second
health loop; avoid per-check client creation) are tracked in the follow-up
issue.  Do not raise `MemoryMax` without fixing the leak.

## 6. Replication

`8108` is reachable only from the peer allowlist.  The registry advertises
public replica URLs, so the firewall rules must include every node that may
pull:

* `primary-85` allows `jump-83` and `aeza-2`.
* `jump-83` allows `primary-85` and `aeza-2`.
* `aeza-2` allows `primary-85` and `jump-83`.

If a new node is added to the control inventory with a replica service, add its
public IP to every peer's UFW rule **before** enabling replication:

```bash
ufw allow from <new-node-ip> to any port 8108 proto tcp comment '<name> replica'
```

After a firewall change, verify a full sync from the peer, not only `/health`:

```bash
TOKEN=$(grep '^INTERNAL_TOKEN=' /opt/mangapoisk-reborn/.env | cut -d= -f2-)
curl -sS -H "X-Internal-Token: $TOKEN" http://127.0.0.1:8108/internal/replica/status
```

## 7. Incident checklist

1. Is the site down? Check `curl -k https://85.192.37.58.nip.io:8443/health`,
   then each service's `/health` on `127.0.0.1`.
2. Is the firewall the cause? `ufw status verbose`; check the allowlist and
   `/var/log/ufw.log`.  Disable UFW only as a last resort and immediately
   re-enable with corrected rules.
3. Is memory the cause? `free -m`, `swapon --show`,
   `journalctl -k | grep -i oom`, `systemctl status mangapoisk-control`.
4. Is replication stale? Compare `last_success_at` on each replica; test the
   peer's `/health` and `/internal/replica/status`; check UFW.
5. Is the backup stale? `restic snapshots`; check the timer and log.  A stale
   backup is not a production outage, but escalate before the next change.
6. Restore only into `/var/tmp` until the verified copy is ready.  Keep the
   previous live file as `.bak` during a planned restore.

## 8. Rollback quick reference

Every change below is reversible.  Run commands on the named host as root.

**UFW:**

```bash
ufw --force disable
tar xzf /root/backups/ops-20261112/<host>/etc-ufw-before*.tar.gz -C /
ufw --force enable
```

If SSH is lost, wait for the five-minute `ufw-rollback` dead-man timer or use
the provider console.  Keep the current SSH session open during any firewall
change.

**Backups:**

```bash
systemctl disable --now mangapoisk-backup.timer
rm -f /etc/systemd/system/mangapoisk-backup.service \
      /etc/systemd/system/mangapoisk-backup.timer \
      /etc/systemd/system/mangapoisk-restore-drill.service
rm -f /usr/local/sbin/mangapoisk-backup.sh \
      /usr/local/sbin/mangapoisk-restore-drill.sh
systemctl daemon-reload
```

The restic repository on `jump-83` is not deleted by the rollback; it is the
off-host copy.  Delete it only with explicit approval.

**Swap:**

```bash
swapoff /swapfile
sed -i '\|^/swapfile[[:space:]]|d' /etc/fstab
rm -f /swapfile /etc/sysctl.d/99-mangapoisk-memory.conf
sysctl --system
```

**Control memory guardrail:**

```bash
rm -f /etc/systemd/system/mangapoisk-control.service.d/memory.conf
systemctl daemon-reload
systemctl set-property --runtime mangapoisk-control.service \
  MemoryHigh=infinity MemoryMax=infinity
```

A restart is not required; the runtime cgroup values change immediately.  The
next service restart uses the persistent drop-in (or no limit after removal).

**Replica allowlist:** remove the peer from the UFW rule on every node that
allowed it:

```bash
ufw delete allow from <peer-ip> to any port 8108 proto tcp
```

## 9. Change log

* 2026-11-12: UFW enabled on `primary-85`, `jump-83`, `aeza-2`; `8108`
  restricted to peer IPs; HTTP/HTTPS/SSH and existing services preserved.
* 2026-11-12: encrypted restic backups to `jump-83`, 6-hourly timer,
  7 daily / 4 weekly / 3 monthly retention; restore drills passed on
  `primary-85` and `jump-83`.
* 2026-11-12: 2 GB swap on `primary-85`, 1 GB on `jump-83`,
  `vm.swappiness=10`; control cgroup guardrail `MemoryHigh=1G`,
  `MemoryMax=1536M`.
