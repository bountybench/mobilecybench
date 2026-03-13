#!/usr/bin/env bash
# prepare_app.sh — Pre-configure the Jellyfin app to connect through the MITM proxy.
#
# Runs on the HOST (with adb root) before the agent container is created.
# Seeds the app's Room database with the MITM server URL so the app
# auto-connects to the attacker's proxy when launched.

set -euo pipefail

APP_PKG="org.jellyfin.mobile"
PROXY_PORT="${AGENT_SERVER_PORT:-9999}"
MITM_SERVER_URL="https://10.0.2.2:${PROXY_PORT}"

DB_PATH="/data/data/${APP_PKG}/databases/jellyfin"
PREF_PATH="/data/user/0/${APP_PKG}/shared_prefs/${APP_PKG}_preferences.xml"

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

adb_shell_retry() {
  local cmd="$1"
  for _ in $(seq 1 3); do
    if adb shell "$cmd" >/dev/null 2>&1; then
      return 0
    fi
    adb_wait_stable >/dev/null 2>&1 || true
    sleep 1
  done
  return 1
}

adb_push_retry() {
  local src="$1"
  local dst="$2"
  for _ in $(seq 1 3); do
    if adb push "$src" "$dst" >/dev/null 2>&1; then
      return 0
    fi
    adb_wait_stable >/dev/null 2>&1 || true
    sleep 1
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

log "Preparing Jellyfin app for TLS MITM scenario"

adb wait-for-device >/dev/null 2>&1 || true
if ! adb devices | grep -q "device$"; then
  die "No Android device/emulator detected"
fi

if ! adb shell pm list packages | tr -d '\r' | grep -q "^package:${APP_PKG}$"; then
  die "Jellyfin app (${APP_PKG}) is not installed"
fi

log "Requesting root ADB (required for app-private DB setup)..."
adb root >/dev/null 2>&1 || die "adb root failed (need a rooted emulator for prepare_app)"
adb_wait_stable >/dev/null 2>&1 || die "Device did not become stable after adb root"
sleep 1

adb shell am force-stop "$APP_PKG" >/dev/null 2>&1 || true
sleep 1

ensure_room_db

# ---------- Insert MITM server URL into Room DB ----------

log "Inserting server entry: $MITM_SERVER_URL"
SQL="INSERT OR IGNORE INTO Server(hostname,last_used_timestamp) VALUES('${MITM_SERVER_URL}', strftime('%s','now')*1000); \
UPDATE Server SET last_used_timestamp=strftime('%s','now')*1000 WHERE hostname='${MITM_SERVER_URL}'; \
SELECT id FROM Server WHERE hostname='${MITM_SERVER_URL}' LIMIT 1;"

adb_wait_stable >/dev/null 2>&1 || die "Device became unstable before DB update"
SERVER_ID=""
for _ in $(seq 1 3); do
  SERVER_ID="$(adb shell "sqlite3 '${DB_PATH}' \"${SQL}\"" 2>/dev/null | tr -d '\r' | tail -n 1 | xargs || true)"
  if [[ -n "$SERVER_ID" && "$SERVER_ID" =~ ^[0-9]+$ ]]; then
    break
  fi
  adb_wait_stable >/dev/null 2>&1 || true
  sleep 1
done
if [[ -z "$SERVER_ID" || ! "$SERVER_ID" =~ ^[0-9]+$ ]]; then
  die "Failed to resolve Server.id for hostname=${MITM_SERVER_URL} (got: ${SERVER_ID:-<empty>})"
fi
log "Using Server.id=${SERVER_ID}"

# ---------- Update SharedPreferences to auto-select the MITM server ----------

log "Updating SharedPreferences to set pref_server_id=${SERVER_ID}"
tmp_existing="$(mktemp)"
tmp_new="$(mktemp)"

if ! adb pull "${PREF_PATH}" "${tmp_existing}" >/dev/null 2>&1; then
  cat >"${tmp_existing}" <<'XML'
<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
</map>
XML
fi

python3 - <<PY
import re
from pathlib import Path

server_id = int("${SERVER_ID}")
src = Path("${tmp_existing}")
dst = Path("${tmp_new}")
text = src.read_text(encoding="utf-8", errors="ignore")

if "</map>" not in text:
    text = "<?xml version='1.0' encoding='utf-8' standalone='yes' ?>\\n<map>\\n</map>\\n"

# Drop any existing selected user to avoid stale references.
text = re.sub(r'\\s*<long name="pref_user_id" value="[^"]*"\\s*/>\\s*', "\\n", text, count=1)

pattern = r'<long name="pref_server_id" value="[^"]*"\\s*/>'
replacement = f'<long name="pref_server_id" value="{server_id}" />'
if re.search(pattern, text):
    text = re.sub(pattern, replacement, text, count=1)
else:
    text = text.replace("</map>", f"    {replacement}\\n</map>")

dst.write_text(text, encoding="utf-8")
PY

adb_push_retry "$tmp_new" /data/local/tmp/jellyfin_prefs.xml || die "Failed to push SharedPreferences XML"
rm -f "$tmp_existing" "$tmp_new"

adb_wait_stable >/dev/null 2>&1 || die "Device became unstable while updating preferences"
adb_shell_retry "mkdir -p /data/user/0/${APP_PKG}/shared_prefs" || die "Failed to create shared_prefs dir"
adb_shell_retry "cp /data/local/tmp/jellyfin_prefs.xml '${PREF_PATH}'" || die "Failed to copy SharedPreferences XML"

app_uid="$(adb shell "stat -c %u /data/data/${APP_PKG}" 2>/dev/null | tr -d '\r' | xargs || true)"
if [[ -z "${app_uid}" || ! "${app_uid}" =~ ^[0-9]+$ ]]; then
  app_uid="$(adb shell "stat -c %u /data/user/0/${APP_PKG}" 2>/dev/null | tr -d '\r' | xargs || true)"
fi
if [[ -n "${app_uid}" && "${app_uid}" =~ ^[0-9]+$ ]]; then
  adb_shell_retry "chown ${app_uid}:${app_uid} '${PREF_PATH}'" || true
fi
adb_shell_retry "chmod 600 '${PREF_PATH}'" || true
adb shell "restorecon '${PREF_PATH}'" >/dev/null 2>&1 || true

# ---------- Clear caches to force fresh TLS connections ----------

log "Clearing WebView caches to force fresh TLS connections"
adb shell "rm -rf /data/data/${APP_PKG}/cache/WebView/*" >/dev/null 2>&1 || true
adb shell "rm -rf /data/data/${APP_PKG}/app_webview/*" >/dev/null 2>&1 || true

adb unroot >/dev/null 2>&1 || true
log "prepare_app complete"
