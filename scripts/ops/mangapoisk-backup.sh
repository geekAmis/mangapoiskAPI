#!/usr/bin/env bash
# MangaPoisk Reborn encrypted off-host backup.
#
# Installed on primary-85 as /usr/local/sbin/mangapoisk-backup.sh.
# The restic repository lives on jump-83 (off-host) and is encrypted at rest.
#
# SQLite copies use VACUUM INTO instead of the online backup API.  VACUUM INTO
# holds one read transaction for the whole copy, so continuous crawler writes
# cannot restart it (the .backup API restarts whenever the source changes and
# can loop forever on a busy writer).  Every copy is verified with
# PRAGMA integrity_check and row counts are recorded in MANIFEST.txt for the
# restore drill.  SQLite builds without VACUUM INTO fall back to .backup.
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
SQLITE_TIMEOUT_MS="${SQLITE_TIMEOUT_MS:-60000}"
SQLITE_ATTEMPTS="${SQLITE_ATTEMPTS:-3}"
PROGRESS_INTERVAL="${PROGRESS_INTERVAL:-30}"
WAL_TRUNCATE_MIN_BYTES="${WAL_TRUNCATE_MIN_BYTES:-67108864}"

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

PROGRESS_PID=""
PROGRESS_LABEL=""
PROGRESS_METHOD=""
PROGRESS_DST=""
LAST_ERR=""
TOTAL_START=$(date +%s)
BACKUP_COMPLETE=0

stop_progress() {
    if [ -n "$PROGRESS_PID" ]; then
        kill "$PROGRESS_PID" 2>/dev/null || true
        wait "$PROGRESS_PID" 2>/dev/null || true
        PROGRESS_PID=""
    fi
}

start_progress() {
    PROGRESS_LABEL="$1"
    PROGRESS_METHOD="$2"
    PROGRESS_DST="$3"
    [ "$PROGRESS_INTERVAL" -gt 0 ] || return 0
    (
        while sleep "$PROGRESS_INTERVAL"; do
            [ -f "$PROGRESS_DST" ] || continue
            size=$(stat -c%s "$PROGRESS_DST" 2>/dev/null || echo 0)
            log "sqlite progress $PROGRESS_LABEL method=$PROGRESS_METHOD dst_size=$size"
        done
    ) &
    PROGRESS_PID=$!
}

cleanup() {
    rc=$?
    trap - EXIT
    stop_progress
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

# True when the SQLite error means this build does not understand VACUUM INTO.
is_vacuum_unsupported() {
    printf '%s' "$1" | grep -qiE 'unrecognized token|syntax error|near "INTO"'
}

# run_copy <method> <src> <dst>
# Returns 0 on success, 2 when VACUUM INTO is unsupported, 1 on exhausted
# retries.  LAST_ERR is set for the caller.
run_copy() {
    method="$1"
    src="$2"
    dst="$3"
    attempt=1
    while [ "$attempt" -le "$SQLITE_ATTEMPTS" ]; do
        rm -f "$dst" "$dst-wal" "$dst-shm"
        LAST_ERR=""
        start_progress "$(basename "$src" .db)" "$method" "$dst"
        rc=0
        if [ "$method" = "vacuum_into" ]; then
            sqlite3 -cmd ".timeout $SQLITE_TIMEOUT_MS" "$src" "VACUUM INTO '$dst';" 2>"$STAGE/.sqlite-err" || rc=$?
        else
            sqlite3 -cmd ".timeout $SQLITE_TIMEOUT_MS" "$src" ".backup '$dst'" 2>"$STAGE/.sqlite-err" || rc=$?
        fi
        stop_progress
        if [ "$rc" -eq 0 ]; then
            rm -f "$STAGE/.sqlite-err"
            return 0
        fi
        LAST_ERR=$(tr '\n' ' ' < "$STAGE/.sqlite-err" 2>/dev/null || true)
        rm -f "$STAGE/.sqlite-err"
        if [ "$method" = "vacuum_into" ] && is_vacuum_unsupported "$LAST_ERR"; then
            return 2
        fi
        log "sqlite $method retry $attempt/$SQLITE_ATTEMPTS for $(basename "$src" .db) rc=$rc err=$LAST_ERR"
        attempt=$((attempt + 1))
        if [ "$attempt" -le "$SQLITE_ATTEMPTS" ]; then
            sleep 10
        fi
    done
    return 1
}

command -v python3 >/dev/null || fail "python3 is required for backup status"
write_status running 0 "" 0 || true
log "backup start host=$HOST_LABEL repo=$RESTIC_REPOSITORY"
[ -r "$RESTIC_PASSWORD_FILE" ] || fail "missing restic password file: $RESTIC_PASSWORD_FILE"
[ -x "$RESTIC_BIN" ] || fail "missing restic binary: $RESTIC_BIN"
[ -d "$DATA_ROOT" ] || fail "missing data root: $DATA_ROOT"
command -v sqlite3 >/dev/null || fail "sqlite3 is required"
log "sqlite3=$(sqlite3 --version | awk '{print $1}') vacuum_into=yes"

rm -rf "$STAGE"
install -d -m 700 "$STAGE/db" "$STAGE/config"

# Consistent SQLite copies.  VACUUM INTO takes one read transaction for the
# whole copy, so it is safe while services are writing and does not restart on
# source changes.  A passive checkpoint first keeps the WAL from growing more
# than necessary during the copy; it never blocks writers and may be a no-op.
for name in "${DB_NAMES[@]}"; do
    src="$DATA_ROOT/$name.db"
    dst="$STAGE/db/$name.db"
    if [ ! -f "$src" ]; then
        log "skip missing $src"
        continue
    fi

    db_start=$(date +%s)
    src_size=$(stat -c%s "$src")
    src_wal=0
    if [ -f "$src-wal" ]; then
        src_wal=$(stat -c%s "$src-wal")
    fi
    log "sqlite start $name src_size=$src_size src_wal=$src_wal method=vacuum_into"

    if ! sqlite3 -cmd ".timeout $SQLITE_TIMEOUT_MS" "$src" 'PRAGMA wal_checkpoint(PASSIVE);' >/dev/null 2>&1; then
        log "warn: wal_checkpoint(PASSIVE) failed for $name (continuing)"
    fi

    method="vacuum_into"
    copy_rc=0
    run_copy "$method" "$src" "$dst" || copy_rc=$?
    if [ "$copy_rc" -eq 2 ]; then
        log "WARN: VACUUM INTO unsupported by sqlite3 $(sqlite3 --version | awk '{print $1}') for $name ($LAST_ERR); falling back to .backup"
        method="backup_api"
        copy_rc=0
        run_copy "$method" "$src" "$dst" || copy_rc=$?
    fi
    [ "$copy_rc" -eq 0 ] || fail "sqlite $method failed for $name after $SQLITE_ATTEMPTS attempts: $LAST_ERR"

    copy_seconds=$(( $(date +%s) - db_start ))
    dst_size=$(stat -c%s "$dst")
    log "sqlite copied $name method=$method dst_size=$dst_size copy_duration=${copy_seconds}s"

    check_start=$(date +%s)
    check=$(sqlite3 -cmd ".timeout $SQLITE_TIMEOUT_MS" "$dst" 'PRAGMA integrity_check;') ||
        fail "integrity query failed for $name"
    [ "$check" = "ok" ] || fail "integrity_check failed for $name: $check"
    check_seconds=$(( $(date +%s) - check_start ))
    total_seconds=$(( $(date +%s) - db_start ))
    log "sqlite ok $name method=$method size=$dst_size copy_duration=${copy_seconds}s integrity_duration=${check_seconds}s total_duration=${total_seconds}s integrity=ok"
done

# Weekly best-effort WAL truncation for the high-write catalog database.  The
# checkpoint uses a 60 s busy timeout: if crawler readers keep the WAL open it
# returns busy and we simply retry next week.  It never truncates while a
# writer holds the WAL, so live writers are not blocked beyond the timeout.
WEEK=$(date -u +%G-%V)
if [ -f "$DATA_ROOT/catalog.db" ]; then
    wal_now=0
    if [ -f "$DATA_ROOT/catalog.db-wal" ]; then
        wal_now=$(stat -c%s "$DATA_ROOT/catalog.db-wal")
    fi
    if [ "$(cat "$STATE_DIR/last-wal-truncate" 2>/dev/null || true)" = "$WEEK" ]; then
        log "wal_checkpoint(TRUNCATE) catalog.db already done week=$WEEK wal_size=$wal_now"
    elif [ "$wal_now" -lt "$WAL_TRUNCATE_MIN_BYTES" ]; then
        log "wal_checkpoint(TRUNCATE) catalog.db skipped week=$WEEK wal_size=$wal_now below_threshold=$WAL_TRUNCATE_MIN_BYTES"
        echo "$WEEK" > "$STATE_DIR/last-wal-truncate"
    else
        log "wal_checkpoint(TRUNCATE) catalog.db start week=$WEEK wal_size=$wal_now"
        if sqlite3 -cmd ".timeout $SQLITE_TIMEOUT_MS" "$DATA_ROOT/catalog.db" 'PRAGMA wal_checkpoint(TRUNCATE);'; then
            wal_after=0
            if [ -f "$DATA_ROOT/catalog.db-wal" ]; then
                wal_after=$(stat -c%s "$DATA_ROOT/catalog.db-wal")
            fi
            echo "$WEEK" > "$STATE_DIR/last-wal-truncate"
            log "wal_checkpoint(TRUNCATE) catalog.db done week=$WEEK wal_size_after=$wal_after"
        else
            log "warn: wal_checkpoint(TRUNCATE) catalog.db busy/failed; retry next run"
        fi
    fi
fi

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
if [ -d "$DATA_ROOT/chapter-archives" ]; then
    BACKUP_ARGS+=("$DATA_ROOT/chapter-archives")
fi
BACKUP_ARGS+=("$STAGE")

restic_out=$(mktemp)
log "restic backup"
if ! "${RESTIC[@]}" "${BACKUP_ARGS[@]}" 2>&1 | tee "$restic_out"; then
    rm -f "$restic_out"
    fail "restic backup failed"
fi
SNAPSHOT_ID=$(sed -n 's/^snapshot \([0-9a-f]\{8\}\) saved$/\1/p' "$restic_out" | tail -1)
rm -f "$restic_out"
log "restic snapshot=${SNAPSHOT_ID:-unknown}"

# Retention: 7 daily + 4 weekly + 3 monthly.  Prune at most once per UTC day so
# the six-hourly timer does not rewrite the repository on every run.
TODAY=$(date -u +%F)
if [ "$(cat "$STATE_DIR/last-prune" 2>/dev/null || true)" != "$TODAY" ]; then
    log "restic forget --prune (7 daily, 4 weekly, 3 monthly)"
    "${RESTIC[@]}" forget --keep-daily 7 --keep-weekly 4 --keep-monthly 3 --prune
    echo "$TODAY" > "$STATE_DIR/last-prune"
fi

# Weekly repository verification, 2% of pack data.
if [ "$(cat "$STATE_DIR/last-check" 2>/dev/null || true)" != "$WEEK" ]; then
    log "restic check --read-data-subset=2%"
    "${RESTIC[@]}" check --read-data-subset=2%
    echo "$WEEK" > "$STATE_DIR/last-check"
fi

BACKUP_COMPLETE=1
log "backup OK snapshot=${SNAPSHOT_ID:-unknown} total_duration=$(( $(date +%s) - TOTAL_START ))s"
