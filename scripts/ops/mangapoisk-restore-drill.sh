#!/usr/bin/env bash
# MangaPoisk Reborn restore drill.
#
# Restores a restic snapshot into an isolated temporary directory and verifies
# SQLite integrity plus every row count recorded in MANIFEST.txt.  It never
# writes to the production data directory.
#
# Usage:
#   mangapoisk-restore-drill.sh [snapshot] [target]
#
# On primary-85 the default repository is SFTP to jump-83.  On jump-83 run:
#   RESTIC_REPOSITORY=/srv/mangapoisk-backups/restic mangapoisk-restore-drill.sh
set -Eeuo pipefail

RESTIC_REPOSITORY="${RESTIC_REPOSITORY:-sftp:mpbackup-jump:/srv/mangapoisk-backups/restic}"
RESTIC_PASSWORD_FILE="${RESTIC_PASSWORD_FILE:-/root/.restic-password}"
RESTIC_BIN="${RESTIC_BIN:-/usr/bin/restic}"
SNAPSHOT="${1:-latest}"
TARGET="${2:-/var/tmp/mangapoisk-restore-drill-$(date -u +%Y%m%dT%H%M%SZ)}"

case "$TARGET" in
    /var/tmp/mangapoisk-restore-drill-* | /tmp/mangapoisk-restore-drill-*) ;;
    *)
        echo "refusing target outside /var/tmp/mangapoisk-restore-drill-*: $TARGET" >&2
        exit 2
        ;;
esac
rm -rf "$TARGET"
install -d -m 700 "$TARGET"

command -v sqlite3 >/dev/null || { echo "sqlite3 is required" >&2; exit 2; }
RESTIC=("$RESTIC_BIN" -r "$RESTIC_REPOSITORY" --password-file "$RESTIC_PASSWORD_FILE")

echo "== repository =="
echo "$RESTIC_REPOSITORY"
"${RESTIC[@]}" snapshots --latest 1

echo "== restore $SNAPSHOT -> $TARGET =="
"${RESTIC[@]}" restore "$SNAPSHOT" --target "$TARGET" --verify

DB_DIR=$(find "$TARGET" -type d -path '*/mangapoisk-backup/db' -print -quit)
MANIFEST=$(find "$TARGET" -type f -name MANIFEST.txt -print -quit)
[ -n "$DB_DIR" ] || { echo "FAIL: database directory not found in snapshot" >&2; exit 1; }
[ -n "$MANIFEST" ] || { echo "FAIL: MANIFEST.txt not found in snapshot" >&2; exit 1; }

fail=0
for db in "$DB_DIR"/*.db; do
    [ -f "$db" ] || continue
    name=$(basename "$db" .db)
    echo "== $name =="
    check=$(sqlite3 "$db" 'PRAGMA integrity_check;') || { echo "FAIL integrity query $name"; fail=1; continue; }
    if [ "$check" = "ok" ]; then
        echo "integrity_check=ok"
    else
        echo "FAIL integrity_check=$check"
        fail=1
    fi

    while IFS= read -r line; do
        case "$line" in
            row.*)
                key=${line%%=*}
                expected=${line#*=}
                key=${key#row.}
                row_name=${key%%.*}
                table=${key#*.}
                [ "$row_name" = "$name" ] || continue
                actual=$(sqlite3 "$db" "SELECT COUNT(*) FROM \"$table\";") || {
                    echo "FAIL count $name.$table"
                    fail=1
                    continue
                }
                if [ "$actual" = "$expected" ]; then
                    echo "row $table=$actual"
                else
                    echo "FAIL row $table expected=$expected actual=$actual"
                    fail=1
                fi
                ;;
        esac
    done < "$MANIFEST"
done

if grep -q '^chapter_archives.count=' "$MANIFEST"; then
    expected=$(grep '^chapter_archives.count=' "$MANIFEST" | cut -d= -f2)
    actual=$(find "$TARGET" -type f -name '*.zip' | wc -l | tr -d ' ')
    echo "chapter_archives expected=$expected restored=$actual"
    if [ "$actual" != "$expected" ]; then
        echo "FAIL chapter archive count"
        fail=1
    fi
fi

if [ "$fail" -eq 0 ]; then
    echo "RESTORE DRILL PASS"
    echo "restored to $TARGET (remove it after reviewing the evidence)"
else
    echo "RESTORE DRILL FAIL"
    exit 1
fi
