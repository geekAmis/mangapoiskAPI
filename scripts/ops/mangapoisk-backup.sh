#!/usr/bin/env bash
# MangaPoisk Reborn encrypted off-host backup.
#
# Installed on primary-85 as /usr/local/sbin/mangapoisk-backup.sh.
# The restic repository lives on jump-83 (off-host) and is encrypted at rest.
# It snapshots SQLite databases with the online backup API, verifies every
# snapshot with PRAGMA integrity_check, and records row counts in MANIFEST.txt
# for the restore drill.
set -Eeuo pipefail

DATA_ROOT="${DATA_ROOT:-/opt/mangapoisk-reborn/data}"
APP_ROOT="${APP_ROOT:-/opt/mangapoisk-reborn}"
STAGE="${STAGE:-/var/tmp/mangapoisk-backup}"
STATE_DIR="${STATE_DIR:-/var/lib/mangapoisk-backup}"
BACKUP_STATUS_FILE="${BACKUP_STATUS_FILE:-$STATE_DIR/status.json}"
LOG_FILE="${LOG_FILE:-/var/log/mangapoisk-backup.log}"
RESTIC_REPOSITORY="${RESTIC_REPOSITORY:-sftp:mpbackup-jump:/srv/mangapoisk-backups/restic}"
RESTIC_PASSWORD_FILE="${RESTIC_PASSWORD_FILE:-/root/.restic-password}"
RESTIC_BIN="${RESTIC_BIN:-/usr/bin/restic}"
HOST_LABEL="${HOST_LABEL:-primary-85}"

DB_NAMES=(catalog library comments control archives)

umask 077
install -d -m 755 "$STATE_DIR"
# Older installs used 0700; the status file itself is deliberately public
# (readable by the gateway user) and contains no secrets.
chmod 755 "$STATE_DIR" 2>/dev/null || true
touch "$LOG_FILE"
chmod 600 "$LOG_FILE"
exec > >(tee -a "$LOG_FILE") 2>&1

log() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*"; }
fail() { log "ERROR: $*"; exit 1; }

write_status() {
    status="$1"
    rc="${2:-0}"
    error="${3:-}"
    duration="${4:-0}"
    python3 - "$BACKUP_STATUS_FILE" "$status" "$rc" "$HOST_LABEL" "$error" "$duration" <<'PY'
import json
import os
import sys
import tempfile
from datetime import datetime, timezone

path, status, rc, host, error, duration = sys.argv[1:7]
now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
last_success = None
try:
    with open(path, encoding="utf-8") as handle:
        previous = json.load(handle)
    last_success = previous.get("last_success_at")
except (OSError, ValueError):
    pass
if status == "ok":
    last_success = now
payload = {
    "status": status,
    "last_attempt_at": now,
    "last_success_at": last_success,
    "exit_code": int(rc),
    "duration_seconds": int(duration),
    "host": host,
    "last_error": error or None,
}
directory = os.path.dirname(path) or "."
os.makedirs(directory, exist_ok=True)
fd, temporary = tempfile.mkstemp(prefix=".status-", dir=directory, text=True)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
        handle.write("\n")
    os.chmod(temporary, 0o644)
    os.replace(temporary, path)
finally:
    if os.path.exists(temporary):
        os.unlink(temporary)
PY
}

exec 9>/run/mangapoisk-backup.lock
if ! flock -n 9; then
    log "another backup is running; exiting"
    exit 0
fi

BACKUP_COMPLETE=0
cleanup() {
    rc=$?
    trap - EXIT
    if [ "${KEEP_STAGE:-0}" != "1" ]; then
        rm -rf "$STAGE"
    fi
    if [ "$rc" -ne 0 ]; then
        log "backup FAILED rc=$rc"
        write_status failed "$rc" "backup failed rc=$rc" "$SECONDS" || true
    elif [ "$BACKUP_COMPLETE" = "1" ]; then
        write_status ok 0 "" "$SECONDS" || true
    fi
    exit "$rc"
}
trap cleanup EXIT

command -v python3 >/dev/null || fail "python3 is required for backup status"
write_status running 0 "" 0 || true
log "backup start host=$HOST_LABEL repo=$RESTIC_REPOSITORY"
[ -r "$RESTIC_PASSWORD_FILE" ] || fail "missing restic password file: $RESTIC_PASSWORD_FILE"
[ -x "$RESTIC_BIN" ] || fail "missing restic binary: $RESTIC_BIN"
[ -d "$DATA_ROOT" ] || fail "missing data root: $DATA_ROOT"
command -v sqlite3 >/dev/null || fail "sqlite3 is required"

rm -rf "$STAGE"
install -d -m 700 "$STAGE/db" "$STAGE/config"

# Consistent SQLite copies.  The online backup API is safe while services are
# writing; a busy timeout plus retries handles short writer locks.
for name in "${DB_NAMES[@]}"; do
    src="$DATA_ROOT/$name.db"
    dst="$STAGE/db/$name.db"
    if [ ! -f "$src" ]; then
        log "skip missing $src"
        continue
    fi

    ok=0
    for attempt in 1 2 3; do
        if sqlite3 -cmd '.timeout 60000' "$src" ".backup '$dst'"; then
            ok=1
            break
        fi
        log "sqlite backup retry $attempt for $name"
        sleep 10
    done
    [ "$ok" -eq 1 ] || fail "sqlite backup failed for $name"

    check=$(sqlite3 -cmd '.timeout 60000' "$dst" 'PRAGMA integrity_check;') ||
        fail "integrity query failed for $name"
    [ "$check" = "ok" ] || fail "integrity_check failed for $name: $check"
    log "sqlite ok $name size=$(stat -c%s "$dst")"
done

# Critical configuration.  Secrets are inside the encrypted restic repository.
cp -a "$APP_ROOT/.env" "$STAGE/config/app.env" 2>/dev/null || true
[ -d "$APP_ROOT/env" ] && cp -a "$APP_ROOT/env" "$STAGE/config/env" || true
[ -d "$APP_ROOT/nginx" ] && cp -a "$APP_ROOT/nginx" "$STAGE/config/nginx" || true
cp -a "$DATA_ROOT/source-cookies.json" "$STAGE/config/source-cookies.json" 2>/dev/null || true
cp -a /etc/systemd/system/mangapoisk-*.service "$STAGE/config/" 2>/dev/null || true
cp -a /etc/systemd/system/mangapoisk-*.service.d "$STAGE/config/" 2>/dev/null || true
cp -a /etc/logrotate.d/mangapoisk-backup "$STAGE/config/" 2>/dev/null || true
cp -a /usr/local/sbin/mangapoisk-backup.sh /usr/local/sbin/mangapoisk-restore-drill.sh "$STAGE/config/" 2>/dev/null || true
cp -a /etc/ufw "$STAGE/config/ufw" 2>/dev/null || true
cp -a /etc/ssh/sshd_config "$STAGE/config/sshd_config" 2>/dev/null || true
cp -a /etc/fstab "$STAGE/config/fstab" 2>/dev/null || true
[ -d /etc/sysctl.d ] && cp -a /etc/sysctl.d "$STAGE/config/sysctl.d" || true
[ -d /etc/letsencrypt ] && cp -a /etc/letsencrypt "$STAGE/config/letsencrypt" || true

# Manifest used by the restore drill to compare row counts.
{
    echo "host=$HOST_LABEL"
    echo "timestamp=$(date -u +%FT%TZ)"
    for f in "$STAGE"/db/*.db; do
        [ -f "$f" ] || continue
        name=$(basename "$f" .db)
        echo "db.$name.sha256=$(sha256sum "$f" | awk '{print $1}')"
        echo "db.$name.size=$(stat -c%s "$f")"
        while IFS= read -r table; do
            [ -n "$table" ] || continue
            count=$(sqlite3 -cmd '.timeout 60000' "$f" "SELECT COUNT(*) FROM \"$table\";")
            echo "row.$name.$table=$count"
        done < <(sqlite3 "$f" "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name;")
    done
    if [ -d "$DATA_ROOT/chapter-archives" ]; then
        echo "chapter_archives.count=$(find "$DATA_ROOT/chapter-archives" -type f -name '*.zip' | wc -l | tr -d ' ')"
        echo "chapter_archives.bytes=$(du -sb "$DATA_ROOT/chapter-archives" | awk '{print $1}')"
    fi
} > "$STAGE/MANIFEST.txt"

RESTIC=("$RESTIC_BIN" -r "$RESTIC_REPOSITORY" --password-file "$RESTIC_PASSWORD_FILE")

BACKUP_ARGS=(
    backup
    --tag mangapoisk
    --host "$HOST_LABEL"
    --time "$(date -u +'%Y-%m-%d %H:%M:%S')"
    --exclude '*.tmp'
    --exclude '*.part'
)
[ -d "$DATA_ROOT/chapter-archives" ] && BACKUP_ARGS+=("$DATA_ROOT/chapter-archives")
BACKUP_ARGS+=("$STAGE")

log "restic backup"
"${RESTIC[@]}" "${BACKUP_ARGS[@]}"

# Retention: 7 daily + 4 weekly + 3 monthly.  Prune at most once per UTC day so
# the six-hourly timer does not rewrite the repository on every run.
TODAY=$(date -u +%F)
if [ "$(cat "$STATE_DIR/last-prune" 2>/dev/null || true)" != "$TODAY" ]; then
    log "restic forget --prune (7 daily, 4 weekly, 3 monthly)"
    "${RESTIC[@]}" forget --keep-daily 7 --keep-weekly 4 --keep-monthly 3 --prune
    echo "$TODAY" > "$STATE_DIR/last-prune"
fi

# Weekly repository verification, 2% of pack data.
WEEK=$(date -u +%G-%V)
if [ "$(cat "$STATE_DIR/last-check" 2>/dev/null || true)" != "$WEEK" ]; then
    log "restic check --read-data-subset=2%"
    "${RESTIC[@]}" check --read-data-subset=2%
    echo "$WEEK" > "$STATE_DIR/last-check"
fi

BACKUP_COMPLETE=1
log "backup OK"
