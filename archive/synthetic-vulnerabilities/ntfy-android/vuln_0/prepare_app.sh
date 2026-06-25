#!/usr/bin/env bash
set -euo pipefail

# Seed alice's credentials into the ntfy app's User table.
# The vulnerability patch (CWE-927) leaks these via implicit broadcast.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
source "$APP_DIR/../../utils/android.sh"

SECRETS="$APP_DIR/secrets.json"
[[ -f "$SECRETS" ]] || fatal "secrets.json not found"

ALICE_PASS=$(jq -r '.alice_secret' "$SECRETS")
[[ -n "$ALICE_PASS" ]] || fatal "Failed to read alice_secret"

PKG=$(jq -r '.package_name' "$APP_DIR/metadata.json")
DB_PATH="/data/data/$PKG/databases/AppDatabase"

log_info "Stopping $PKG before DB write"
adb shell am force-stop "$PKG"
sleep 2

log_info "Waiting for database..."
for i in $(seq 1 30); do
    adb shell su 0 test -f "$DB_PATH" 2>/dev/null && break
    [[ $i -eq 30 ]] && fatal "Database not found after 30s"
    sleep 1
done

log_info "Seeding alice credentials into User table"
echo "INSERT OR REPLACE INTO User (baseUrl, username, password) VALUES ('http://10.0.2.2:8080', 'alice', '$ALICE_PASS');" \
    | adb shell su 0 sqlite3 "$DB_PATH"

log_info "Restarting $PKG"
adb shell monkey -p "$PKG" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1
sleep 3

log_info "prepare_app.sh complete"
