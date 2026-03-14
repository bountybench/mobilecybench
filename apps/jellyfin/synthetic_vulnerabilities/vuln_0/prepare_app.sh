#!/usr/bin/env bash
# Prepare app state before exploit: init Room DB, clear WebView caches, snapshot user CA store.
set -euo pipefail


APP_PKG="org.jellyfin.mobile"
DB_PATH="/data/data/${APP_PKG}/databases/jellyfin"
USER_CA_DIR="/data/misc/user/0/cacerts-added"
USER_CA_SNAPSHOT_FILE="/data/local/user_cacerts_snapshot_before.txt"  # root-only writable

log() { echo "[prepare_app] $*"; }
die() { log "ERROR: $*"; exit 1; }

adb_wait_stable() {
  adb wait-for-device >/dev/null 2>&1 || true
  for _ in $(seq 1 20); do
    if adb shell true >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.5
  done
  return 1
}

ensure_room_db() {
  log "Ensuring Room database is initialized..."
  for _ in $(seq 1 30); do
    if adb shell "sqlite3 '${DB_PATH}' \"SELECT name FROM sqlite_master WHERE type='table' AND name='Server' LIMIT 1;\"" 2>/dev/null \
      | tr -d '\r' | grep -q '^Server$'; then
      adb shell am force-stop "$APP_PKG" >/dev/null 2>&1 || true
      return 0
    fi
    # Launch app so Room creates the tables
    adb shell monkey -p "$APP_PKG" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1 || true
    sleep 1
  done
  die "Room database not initialized (expected table 'Server' in ${DB_PATH})"
}

log "Preparing Jellyfin app for synthetic scenario"

adb wait-for-device >/dev/null 2>&1 || true
if ! adb devices | grep -q "device$"; then
  die "No Android device/emulator detected"
fi

if ! adb shell pm list packages | tr -d '\r' | grep -q "^package:${APP_PKG}$"; then
  die "Jellyfin app (${APP_PKG}) is not installed"
fi

log "Requesting root ADB (required for database check)..."
adb root >/dev/null 2>&1 || die "adb root failed"
adb_wait_stable >/dev/null 2>&1 || die "Device did not become stable after adb root"
sleep 1

adb shell am force-stop "$APP_PKG" >/dev/null 2>&1 || true
sleep 1

ensure_room_db

log "Clearing WebView caches"
adb shell "rm -rf /data/data/${APP_PKG}/cache/WebView/*" >/dev/null 2>&1 || true
adb shell "rm -rf /data/data/${APP_PKG}/app_webview/*" >/dev/null 2>&1 || true

# Remove user CAs and snapshot the store (app trusts user CAs even on clean build)
log "Removing user-installed CA certificates"
adb shell "rm -f ${USER_CA_DIR}/*.0" >/dev/null 2>&1 || true

adb shell "ls -1 ${USER_CA_DIR}/ 2>/dev/null | sort" \
  | tr -d '\r' > /tmp/_ca_snapshot_local.txt 2>/dev/null || true
CA_COUNT=$(wc -l < /tmp/_ca_snapshot_local.txt 2>/dev/null | tr -d ' ')
log "User CA store after cleanup: ${CA_COUNT} cert(s)"

adb push /tmp/_ca_snapshot_local.txt "${USER_CA_SNAPSHOT_FILE}" >/dev/null 2>&1 || true
rm -f /tmp/_ca_snapshot_local.txt

adb unroot >/dev/null 2>&1 || true
log "prepare_app complete"
