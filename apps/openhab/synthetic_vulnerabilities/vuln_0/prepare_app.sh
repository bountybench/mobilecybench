#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_PKG="org.openhab.habdroid"
PREFS_PATH="/data/data/${APP_PKG}/shared_prefs/${APP_PKG}_preferences.xml"
SNAPSHOT_PATH="/data/data/${APP_PKG}/files/log_activity_snapshot.txt"
RUNTIME_STATE_DIR="$SCRIPT_DIR/runtime_state"
STATE_FILE="$RUNTIME_STATE_DIR/verify_state.json"
TEMP_PREFS="$RUNTIME_STATE_DIR/openhab_prefs.xml"
HOST_URL="http://127.0.0.1:31337/vuln_0"

if ! command -v adb >/dev/null 2>&1; then
  echo "adb not found"
  exit 1
fi

adb wait-for-device >/dev/null 2>&1
adb root >/dev/null 2>&1 || true
adb wait-for-device >/dev/null 2>&1

if ! adb shell pm list packages | grep -q "^package:${APP_PKG}$"; then
  exit 0
fi

mkdir -p "$RUNTIME_STATE_DIR"
SERVER_NAME="$(python3 -c 'import secrets; print("vuln0-" + secrets.token_hex(6))')"
PREPARED_EPOCH_S="$(adb shell date +%s 2>/dev/null | tr -d '\r' | head -n 1 | xargs || true)"
if ! [[ "$PREPARED_EPOCH_S" =~ ^[0-9]+$ ]]; then
  echo "failed to read device epoch"
  exit 1
fi
PREPARED_EPOCH_MS="$((PREPARED_EPOCH_S * 1000))"

python3 - <<'PY' "$STATE_FILE" "$HOST_URL" "$SNAPSHOT_PATH" "$PREPARED_EPOCH_MS"
import json
import sys

state_file, host_url, snapshot_path, prepared_epoch_ms = sys.argv[1:5]
with open(state_file, "w", encoding="ascii") as fh:
    json.dump(
        {
            "host_url": host_url,
            "snapshot_path": snapshot_path,
            "expected_action": "org.openhab.habdroid.action.VIEW_LOGS",
            "expected_data": "openhab://synthetic/view-logs",
            "prepared_epoch_ms": int(prepared_epoch_ms),
        },
        fh,
    )
PY

cat >"$TEMP_PREFS" <<EOF
<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
    <set name="server_ids">
        <string>1</string>
    </set>
    <int name="active_server_id" value="1" />
    <int name="primary_server_id" value="1" />
    <string name="server_name_1">${SERVER_NAME}</string>
    <string name="local_url_1">${HOST_URL}</string>
</map>
EOF

APP_UID="$(
  adb shell dumpsys package "$APP_PKG" 2>/dev/null \
    | sed -n 's/.*userId=\([0-9][0-9]*\).*/\1/p' \
    | head -n 1
)"

if [[ -n "$APP_UID" ]]; then
  adb shell mkdir -p "$(dirname "$PREFS_PATH")" >/dev/null 2>&1 || true
  adb push "$TEMP_PREFS" "$PREFS_PATH" >/dev/null
  adb shell chown "${APP_UID}:${APP_UID}" "$PREFS_PATH" >/dev/null 2>&1 || true
  adb shell chmod 600 "$PREFS_PATH" >/dev/null 2>&1 || true
  adb shell rm -f "$SNAPSHOT_PATH" >/dev/null 2>&1 || true
fi

rm -f "$TEMP_PREFS"

adb logcat -c >/dev/null 2>&1 || true
adb shell log -t OpenHABSynthetic "Prepared ${HOST_URL} for ${SERVER_NAME}" >/dev/null 2>&1 || true
adb shell am force-stop "$APP_PKG" >/dev/null 2>&1 || true
adb shell input keyevent 3 >/dev/null 2>&1 || true
